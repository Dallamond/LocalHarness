"""Autopiloto: una lista de parches que LocalHarness va haciendo solo durante horas (p. ej. mientras estás en clase).

Habla con LocalHarness por su API (tiene que estar abierto) y, por cada parche de la lista:
1. comprueba que los modelos locales siguen arrancados (si alguno se cayó, lo vuelve a arrancar con su último modelo);
2. crea una tarea normal con el agente elegido (en la oficina se ve igual que si la lanzaras tú);
3. espera a que acabe, con un tope de tiempo (si se pasa, la para: así un encargo colgado no se come la noche);
4. si dejó cambios, pasa los tests en su worktree: si pasan, la aprueba y la integra; si no, le pide UNA vez que lo
   arregle con la salida de los tests, y si siguen fallando, la descarta;
5. apunta todo (resultado, tiempos, coste, encargos y tokens de cada modelo local) en un informe Markdown que se
   reescribe después de cada parche, y en un estado JSON que permite retomarlo donde se quedó.
Para cuando se acaba la lista, el tiempo o el presupuesto, o tras 3 fallos seguidos (p. ej. límite del plan de Claude).
Mientras corre, Windows no se suspende (SetThreadExecutionState). Todo lo demás (pensamientos, respuestas) ya queda
en la base de datos de cada tarea para analizarlo después.

Uso: python -m localharness autopilot --project poeta --agent "Jefe de obra" --list autopilot/poeta.md
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

OPEN = ("running", "pending")
NOTE = ("\n\n(AUTOPILOTO: nadie va a contestar hasta dentro de horas. No hagas preguntas ni pidas permiso: decide tú, "
        "termina el parche y deja los tests pasando. Sigue ENCARGO.md. Termina con un informe corto: qué hizo cada "
        "modelo local, qué falló o repetiste y qué queda pendiente.)")
LOAD_WAIT_S = 420  # lo que espera a un modelo que está cargando antes de lanzar un parche
GRACE_S = 300  # margen sobre el tope de LocalHarness antes de que el autopiloto cancele él
CLOSE_MIN = 10  # minutos para cerrar un parche al que se le acabó el tiempo
CLOSE_MSG = ("Se te acabó el tiempo de este parche. NO empieces nada nuevo: en como mucho {minutes} minutos deja "
             "pasando `{check}` con lo que ya está hecho (si una parte no llega, quítala o recórtala con un `edit` en "
             "vez de terminarla), añade la línea del CHANGELOG si falta y termina con el informe. Lo que no dé tiempo, "
             "a «Pendiente».")


class ApiError(RuntimeError):
    pass


def http(base: str) -> Callable[[str, str, dict | None], dict | list]:
    def call(method: str, path: str, body: dict | None = None) -> dict | list:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise ApiError(f"{method} {path}: HTTP {e.code} {e.read()[:300].decode('utf-8', 'replace')}") from None
        except OSError as e:
            raise ApiError(f"{method} {path}: {e} (¿está abierto LocalHarness?)") from None
    return call


def read_list(path: Path) -> list[str]:
    """Una línea por parche: «- texto», «* texto» o «1. texto». Lo demás (títulos, notas) se ignora."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.+)$", line)
        if m and m.group(1).strip():
            out.append(m.group(1).strip())
    return out


def keep_awake(on: bool) -> None:
    """Windows: que el PC no se suspenda mientras corre (la pantalla sí puede apagarse)."""
    try:
        import ctypes
        flags = 0x80000000 | (0x00000001 if on else 0)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


def no_quick_edit() -> None:
    """Windows: quita la «edición rápida» de esta consola. Con ella, un clic en la ventana empieza a seleccionar texto
    y congela el proceso en el siguiente print hasta que pulses Esc (así se quedó parado el 08/10 en la tarea 1)."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        h = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            k32.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080)  # sin ENABLE_QUICK_EDIT_MODE, con EXTENDED_FLAGS
    except (AttributeError, OSError):
        pass


def run_check(command: str, cwd: str, timeout: float = 300) -> tuple[bool, str]:
    parts = command.split()
    exe = shutil.which(parts[0]) or parts[0]
    try:
        p = subprocess.run([exe, *parts[1:]], cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, f"«{command}» tardó más de {timeout:.0f} s"
    except OSError as e:
        return False, f"no se pudo ejecutar «{command}»: {e}"
    out = (p.stdout + p.stderr).strip()
    return p.returncode == 0, out[-3000:]


@dataclass
class Result:
    n: int
    text: str
    task_ids: list[int] = field(default_factory=list)
    outcome: str = ""  # integrado | sin cambios | descartado | tiempo agotado | falló
    seconds: float = 0.0
    cost: float = 0.0
    check: str = ""
    retried: bool = False
    final: str = ""
    models: dict = field(default_factory=dict)  # servidor → {encargos, fallidos, tokens, segundos, modelo}
    rescued: bool = False  # se le acabó el tiempo y se le pidió que cerrara con lo que tenía


class Autopilot:
    def __init__(self, api: Callable, project: str, agent: str, items: list[str], *, hours: float = 6,
                 budget: float = 5.0, task_minutes: float = 30, check: str = "node --test", state: Path,
                 report: Path, say: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, checker: Callable = run_check,
                 reload: Callable[[], list[str]] | None = None):
        self.api, self.items, self.check, self.reload = api, items, check, reload
        self.hours, self.budget, self.task_s = hours, budget, task_minutes * 60
        self.state_path, self.report_path, self.say, self.sleep, self.clock = state, report, say, sleep, clock
        self.checker = checker
        projects = api("GET", "/api/projects")
        self.project = next((p for p in projects if p["name"] == project or str(p["id"]) == str(project)), None)
        if not self.project:
            raise ApiError(f"No hay ningún proyecto llamado {project!r}")
        agents = api("GET", "/api/agents")
        self.agent = next((a for a in agents if a["name"] == agent or str(a["id"]) == str(agent)), None)
        if not self.agent:
            raise ApiError(f"No hay ningún agente llamado {agent!r}")
        self.results: list[Result] = []
        self.started_at = datetime.now()
        try:
            st = json.loads(state.read_text(encoding="utf-8"))
            self.results = [Result(**r) for r in st.get("results", [])]
        except (OSError, ValueError, TypeError):
            pass

    # --- modelos locales
    def ensure_locals(self) -> None:
        try:
            info = self.api("GET", "/api/llama")
        except ApiError as e:
            self.say(f"  (no pude mirar los modelos locales: {e})")
            return
        cfg = info.get("config") or {}
        for srv in info.get("servers") or []:
            if srv["status"]["state"] not in ("off", "failed"):
                continue
            last = cfg.get("last") if srv["id"] == "principal" else (cfg.get("last_by_server") or {}).get(srv["id"])
            if not last or not last.get("model"):
                continue
            self.say(f"  {srv['name']} estaba {srv['status']['state']}: lo arranco otra vez ({Path(last['model']).stem})")
            try:
                self.api("POST", "/api/llama/start", {"path": last["model"], "server": srv["id"],
                                                     "options": last.get("options") or None})
            except ApiError as e:
                self.say(f"  no pude: {e}")
        self.wait_loaded()

    def wait_loaded(self, limit: float = LOAD_WAIT_S) -> None:
        """Si algún modelo está cargando, espera a que termine antes de lanzar el parche (gpt-oss-20b: ~3 min; el
        08/10 un parche entero se fue en 503 «Loading model»)."""
        t0 = self.clock()
        told = False
        while self.clock() - t0 < limit:
            try:
                servers = self.api("GET", "/api/llama").get("servers") or []
            except ApiError:
                return
            loading = [s["name"] for s in servers if (s.get("status") or {}).get("state") in ("loading", "starting")]
            if not loading:
                return
            if not told:
                self.say(f"  espero a que termine de cargar: {', '.join(loading)}")
                told = True
            self.sleep(5)

    def infra_failure(self, r: "Result") -> bool:
        """¿Falló por la infraestructura (API, modelo cargando o caído) sin que los modelos llegaran a trabajar?
        Esos parches se repiten una vez en vez de darlos por perdidos."""
        if r.outcome.startswith("falló:"):
            return True
        if r.outcome != "sin cambios":
            return False
        tokens = sum((m.get("tokens") or 0) for m in (r.models or {}).values())
        failed = sum((m.get("fallidos") or 0) for m in (r.models or {}).values())
        return tokens == 0 and failed > 0

    # --- una tarea hasta que acaba (o se pasa de tiempo)
    def wait(self, tid: int, limit: float | None = None) -> dict:
        """Hasta que la tarea acaba. El tope es algo mayor que el de LocalHarness (Ajustes → minutos por tarea) para
        que pare él primero: así la tarea queda en «timeout» con su sesión y se puede pedir que cierre."""
        t0 = self.clock()
        limit = limit or self.task_s + GRACE_S
        while True:
            t = self.api("GET", f"/api/tasks/{tid}")
            if t["status"] not in OPEN:
                return t
            if self.clock() - t0 > limit:
                self.say(f"  #{tid} lleva más de {limit / 60:.0f} min: la paro")
                try:
                    self.api("POST", f"/api/tasks/{tid}/cancel")
                except ApiError:
                    pass
                self.sleep(5)
                return {**self.api("GET", f"/api/tasks/{tid}"), "timed_out": True}
            self.sleep(10)

    def start_when_free(self, body: dict) -> dict:
        for _ in range(60):  # una tarea por repo: si queda otra en marcha (tuya), espera
            try:
                return self.api("POST", "/api/tasks", body)
            except ApiError as e:
                if "409" not in str(e):
                    raise
                self.sleep(30)
        raise ApiError("el proyecto lleva 30 min ocupado por otra tarea")

    def adoptable(self, n: int) -> dict | None:
        """Si el autopiloto se cerró a mitad de un parche, su tarea sigue viva: se retoma en vez de lanzar otra
        (que chocaría con ella en el mismo repo y repetiría el parche). Una que se quedó sin tiempo también: se le
        pide que cierre con lo que tiene."""
        try:
            tasks = self.api("GET", "/api/tasks")
        except ApiError:
            return None
        return next((t for t in tasks if t.get("project_id") == self.project["id"]
                     and str(t.get("title") or "").startswith(f"Autopiloto {n}/")
                     and t.get("status") in (*OPEN, "review", "timeout")), None)

    def models_of(self, tids: list[int]) -> dict:
        out: dict = {}
        for tid in tids:
            try:
                evs = self.api("GET", f"/api/tasks/{tid}/events")
            except ApiError:
                continue
            for e in evs:
                d = e.get("data") or {}
                tool = str(d.get("tool") or "")
                if e.get("kind") != "delegate" or tool in ("local_prepare", "local_execute_plan", "run_checks"):
                    continue
                m = out.setdefault(str(d.get("server") or "principal"),
                                   {"encargos": 0, "fallidos": 0, "tokens": 0, "segundos": 0.0, "modelo": None})
                m["encargos"] += 1
                m["fallidos"] += 0 if d.get("ok", True) else 1
                m["tokens"] += int(d.get("completion_tokens") or 0)
                # gen_seconds incluye la espera en la cola del servidor: con tok/s se cuenta solo lo que generó
                tokens, tps = int(d.get("completion_tokens") or 0), float(d.get("tps") or 0)
                m["segundos"] += tokens / tps if tokens and tps else float(d.get("gen_seconds") or d.get("seconds") or 0)
                m["modelo"] = d.get("model") or m["modelo"]
        return out

    # --- un parche
    def patch(self, n: int, text: str) -> Result:
        r = Result(n=n, text=text)
        t0 = self.clock()
        # el número del parche lo pone el agente siguiendo CHANGELOG.md (la lista no sabe cuántos hay ya)
        prompt = f"Nuevo parche (el siguiente número según CHANGELOG.md): {text}{NOTE}"
        t = self.adoptable(n)
        if t:
            self.say(f"  sigo con la tarea #{t['id']}, que ya estaba en marcha (se reinició el autopiloto)")
        else:
            t = self.start_when_free({"project_id": self.project["id"], "agent_id": self.agent["id"],
                                      "prompt": prompt, "title": f"Autopiloto {n}/{len(self.items)}: {text}"[:80]})
            self.say(f"  tarea #{t['id']}")
        tid = t["id"]
        r.task_ids.append(tid)
        t = self.wait(tid)
        if t.get("timed_out") or t["status"] == "timeout":
            # el 08/10 se tiraron así 3 parches de 18 con 20-27 encargos hechos cada uno: mejor que cierre
            self.say(f"  se le acabó el tiempo: le pido que cierre en {CLOSE_MIN} min con lo que tenga")
            r.rescued = True
            try:
                self.api("POST", f"/api/tasks/{tid}/reply", {"message": CLOSE_MSG.format(minutes=CLOSE_MIN,
                                                                                         check=self.check)})
                self.sleep(5)
                t = self.wait(tid, CLOSE_MIN * 60 + GRACE_S)
            except ApiError as e:
                self.say(f"  no pude: {e}")
        if t.get("timed_out") or t["status"] == "timeout":
            r.outcome = "tiempo agotado"
        elif t["status"] == "review":
            ok, out = self.checker(self.check, t["worktree"]) if self.check else (True, "")
            if not ok:
                self.say("  los tests fallan: le pido que lo arregle (una vez)")
                r.retried = True
                self.api("POST", f"/api/tasks/{tid}/reply", {
                    "message": f"`{self.check}` falla en tu worktree. Arréglalo (sin preguntar) y déjalo pasando:\n\n{out}"})
                self.sleep(5)
                t = self.wait(tid)
                ok, out = (self.checker(self.check, t["worktree"]) if t["status"] == "review" and not t.get("timed_out")
                           else (False, out))
            r.check = ("pasan" if ok else "fallan") + (f"\n{out[-1500:]}" if out and not ok else "")
            if ok:
                try:
                    self.api("POST", f"/api/tasks/{tid}/approve")
                    self.api("POST", f"/api/tasks/{tid}/merge", {"confirm": True})
                    r.outcome = "integrado"
                except ApiError as e:
                    r.outcome = f"no se pudo integrar: {e}"
            else:
                try:
                    self.api("POST", f"/api/tasks/{tid}/reject")
                except ApiError:
                    pass
                r.outcome = "descartado (tests)"
        elif t["status"] == "done":
            r.outcome = "sin cambios"
        elif t["status"] == "merged":  # la integraste tú desde la oficina
            r.outcome = "integrado"
        elif t["status"] in ("rejected", "discarded"):
            r.outcome = "descartado (a mano)"
        else:
            r.outcome = f"falló ({t['status']})"
        t = self.api("GET", f"/api/tasks/{tid}")
        r.cost = float(t.get("cost_usd") or 0)
        r.final = (t.get("final") or "").strip()[:1500]
        r.seconds = round(self.clock() - t0)
        r.models = self.models_of(r.task_ids)
        return r

    # --- bucle
    def run(self) -> list[Result]:
        deadline = self.clock() + self.hours * 3600
        done = {r.n for r in self.results}
        fails = 0
        keep_awake(True)
        no_quick_edit()
        try:
            n = 0
            while True:
                if self.reload:  # la lista se puede alargar (o corregir) con el autopiloto en marcha
                    try:
                        self.items = self.reload() or self.items
                    except (OSError, ValueError):
                        pass
                n += 1
                if n > len(self.items):
                    break
                text = self.items[n - 1]
                if n in done:
                    continue
                spent = sum(r.cost for r in self.results)
                if self.clock() > deadline:
                    self.say("Se acabó el tiempo.")
                    break
                if spent >= self.budget:
                    self.say(f"Se acabó el presupuesto ({spent:.2f} $ de {self.budget:.2f} $).")
                    break
                self.say(f"[{datetime.now():%H:%M}] Parche {n:03d}/{len(self.items)}: {text}")
                self.ensure_locals()
                for attempt in range(2):
                    try:
                        r = self.patch(n, text)
                    except ApiError as e:
                        r = Result(n=n, text=text, outcome=f"falló: {e}")
                    if attempt or not self.infra_failure(r):
                        break
                    self.say(f"  → {r.outcome}: los modelos no llegaron a trabajar; lo repito una vez")
                    self.sleep(30)
                    self.ensure_locals()
                self.results.append(r)
                self.save()
                self.say(f"  → {r.outcome} · {r.seconds / 60:.1f} min · {r.cost:.3f} $")
                fails = fails + 1 if r.outcome.startswith(("falló", "tiempo")) else 0
                if fails >= 3:
                    self.say("3 parches seguidos fallando: paro (¿límite del plan de Claude o modelos caídos?).")
                    break
        finally:
            keep_awake(False)
            self.save()
        return self.results

    # --- informe
    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"project": self.project["name"], "agent": self.agent["name"],
                                               "results": [r.__dict__ for r in self.results]},
                                              ensure_ascii=False, indent=1), encoding="utf-8")
        self.report_path.write_text(self.report(), encoding="utf-8")

    def report(self) -> str:
        rs = self.results
        total_s = sum(r.seconds for r in rs) or 1
        lines = [f"# Autopiloto · {self.project['name']} · {self.started_at:%d/%m/%Y %H:%M}", "",
                 f"Agente: **{self.agent['name']}** · parches: {len(rs)} de {len(self.items)} · integrados: "
                 f"{sum(r.outcome == 'integrado' for r in rs)} · coste: {sum(r.cost for r in rs):.2f} $ · "
                 f"tiempo: {total_s / 3600:.1f} h", "",
                 "| Parche | Resultado | Min | Coste | Tareas | Reintento |", "|---|---|---|---|---|---|"]
        for r in rs:
            closed = " (cerrado al límite)" if r.rescued else ""
            lines.append(f"| {r.n:03d} {r.text[:60]} | {r.outcome}{closed} | {r.seconds / 60:.1f} | {r.cost:.3f} $ | "
                         f"{', '.join(f'#{t}' for t in r.task_ids)} | {'sí' if r.retried else ''} |")
        per: dict = {}
        for r in rs:
            for srv, m in r.models.items():
                a = per.setdefault(srv, {"encargos": 0, "fallidos": 0, "tokens": 0, "segundos": 0.0, "modelo": None})
                for k in ("encargos", "fallidos", "tokens", "segundos"):
                    a[k] += m[k]
                a["modelo"] = m["modelo"] or a["modelo"]
        if per:
            lines += ["", "## Modelos locales", "",
                      "| Modelo | Encargos | Fallidos | Tokens | Generando | % del tiempo | tok/s medio |",
                      "|---|---|---|---|---|---|---|"]
            for srv, a in per.items():
                lines.append(f"| {srv} ({a['modelo'] or '?'}) | {a['encargos']} | {a['fallidos']} | {a['tokens']} | "
                             f"{a['segundos'] / 60:.1f} min | {100 * a['segundos'] / total_s:.0f} % | "
                             f"{a['tokens'] / a['segundos'] if a['segundos'] else 0:.1f} |")
            lines.append("")
            lines.append("«% del tiempo» = tiempo generando de ese modelo (tokens ÷ su velocidad, sin la espera en "
                         "cola) frente al tiempo total: lo que falta hasta 100 % es su GPU parada.")
        for r in rs:
            lines += ["", f"## Parche {r.n:03d}: {r.text}", "", f"**{r.outcome}** · tareas "
                      f"{', '.join(f'#{t}' for t in r.task_ids)} · tests: {r.check.splitlines()[0] if r.check else '—'}"]
            if r.check and "\n" in r.check:
                lines += ["", "```", r.check.split("\n", 1)[1], "```"]
            if r.final:
                lines += ["", "> " + r.final.replace("\n", "\n> ")]
        return "\n".join(lines) + "\n"
