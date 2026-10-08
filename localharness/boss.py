"""Jefe local: el modo 100 % local. Hace lo que hacía el jefe Claude en el autopiloto, pero con los modelos locales y
como una tubería fija en vez de un agente libre (los bucles de agente local se atascaban: el 08/10, 29 llamadas a
`local_agent` y 93 min casi todos parados). Pasos:

1. contexto: normas del proyecto (ENCARGO.md, README…), mapa del repo y final del CHANGELOG;
2. elegir archivos: el modelo fuerte dice qué archivos necesita ver el plan (JSON validado);
3. planificar: bloques edit/write con instrucciones autocontenidas (mcp_local.plan_blocks, validado);
4. ejecutar: los bloques van a la vez a los modelos libres (mcp_local.execute_plan, con su arreglo automático);
5. comprobar y arreglar: si los tests fallan, un plan de arreglo con la salida delante (hasta FIX_ROUNDS);
6. revisar: el modelo fuerte lee el diff contra el encargo (JSON ok/problemas); si hay problemas, una ronda más;
7. informe: qué se hizo, qué falló y qué queda.

Todo lo que se pide a los modelos queda en el log de encargos (`LH_LOG`), así que la oficina, el panel de
analítica y el informe del autopiloto lo ven igual que con Claude. Coste: 0 $.
"""

import json
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from localharness.mcp_local import ToolError, check_failed, strip_fence

FIX_ROUNDS = 3        # rondas de arreglo tras el plan (además de la del propio execute_plan)
REVIEW_ROUNDS = 1     # rondas de corrección tras la revisión
MAX_FILES = 8         # archivos que puede pedir el planificador
RULE_FILES = ("ENCARGO.md", "AGENTS.md", "CLAUDE.md", "README.md")
MAX_RULES = 6000
MAX_DIFF = 24_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
# gpt-oss con razonamiento «medium» se quedó en bucle eligiendo archivos (el 08/10, 4.800 tokens repitiendo «We
# can't open file…»): el jefe piensa en «low», con tope de tokens, y repite una vez si se corta
EFFORT = "low"
MAX_SELECT_TOKENS = 3000
MAX_REVIEW_TOKENS = 4000

SELECT_SCHEMA = {
    "type": "object",
    "properties": {"files": {"type": "array", "maxItems": MAX_FILES, "items": {"type": "string"}},
                   "why": {"type": "string"}},
    "required": ["files"],
}
SYSTEM_SELECT = (
    "Eres el jefe técnico de un equipo de modelos locales. Antes de planificar, elige qué archivos EXISTENTES del "
    "repo hay que leer para hacer bien la tarea: los que hay que cambiar, los que sirven de ejemplo o plantilla "
    f"(un archivo parecido ya hecho) y los tests relacionados. Como mucho {MAX_FILES}, solo rutas que estén en el "
    "MAPA. Responde SOLO con el JSON.")

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"},
                   "problems": {"type": "array", "items": {"type": "string"}},
                   "summary": {"type": "string"}},
    "required": ["ok", "problems", "summary"],
}
SYSTEM_REVIEW = (
    "Eres el revisor de un equipo de modelos locales. Te paso la TAREA, las NORMAS del proyecto y el DIFF de lo que "
    "se ha hecho. Di si cumple la tarea y las normas. `problems`: solo fallos CONCRETOS y comprobables en el diff "
    "(algo que pide la tarea y falta, código roto, un test que no comprueba nada, una norma incumplida), cada uno "
    "con el archivo y qué cambiar; nada de gustos ni mejoras opcionales. Si todo está bien: ok=true y problems=[]. "
    "`summary`: dos o tres frases de qué se ha hecho. Responde SOLO con el JSON.")


class Boss:
    def __init__(self, server, check: str = "", say: Callable[[str], None] = lambda text: None,
                 deadline: float | None = None):
        self.s = server
        self.root: Path = server.root
        self.check = check
        self.say = say
        self.deadline = deadline  # time.monotonic() tope: entre pasos se para si se pasa
        self.notes: list[str] = []  # lo que va al informe

    # --- utilidades
    def late(self) -> bool:
        return self.deadline is not None and time.monotonic() > self.deadline

    def think(self, tool: str, task: str, fn, light: bool = False):
        """Un encargo de «pensar» del jefe, apuntado en el log de encargos como cualquier otro. Planificar y revisar
        van al modelo fuerte; lo de leer y clasificar (`light`: elegir archivos) al rápido, que si no se quedaba
        parado mientras el fuerte lo hacía todo."""
        s = self.s
        entry: dict = {"tool": f"jefe_local/{tool}", "at": time.time(), "task": task[:300]}
        t0 = time.monotonic()
        order = s.route("local_ask" if light else "local_agent")
        s.order = order
        s.use(order[0])
        s.current = {"tool": entry["tool"], "task": entry["task"], "server": s.server_id}
        try:
            try:
                result, stats = fn()
            except ToolError as e:
                if "bucle" not in str(e) and "pensando" not in str(e) and "no vale" not in str(e):
                    raise
                self.say(f"{tool}: {str(e).split(';')[0]} — lo intento otra vez")
                result, stats = fn()
            entry.update(stats, ok=True, server=s.server_id)
            return result
        except ToolError as e:
            entry.update(ok=False, error=str(e), server=s.server_id)
            raise
        finally:
            entry["seconds"] = round(time.monotonic() - t0, 1)
            s._log(entry)

    def rules(self) -> str:
        parts = []
        for name in RULE_FILES:
            p = self.root / name
            if p.is_file():
                parts.append(f"### {name}\n{p.read_text(encoding='utf-8', errors='replace')[:MAX_RULES]}")
            if sum(len(x) for x in parts) > MAX_RULES:
                break
        log = self.root / "CHANGELOG.md"
        if log.is_file():
            tail = log.read_text(encoding="utf-8", errors="replace")[-1500:]
            parts.append(f"### Final de CHANGELOG.md (para saber el número siguiente)\n…{tail}")
        return "\n\n".join(parts)[: MAX_RULES + 1600]

    def existing(self, paths) -> list[str]:
        out = []
        for p in paths or []:
            p = str(p).strip().replace("\\", "/").removeprefix("./")
            try:
                if p and (self.root / p).resolve().is_file() and (self.root / p).resolve().is_relative_to(self.root):
                    out.append(p)
            except (OSError, ValueError):
                continue
        return list(dict.fromkeys(out))

    def mentioned(self, task: str) -> list[str]:
        """Archivos del repo que la tarea nombra (por ruta o por nombre): entran siempre. El 08/10 el modelo eligió
        el kit de tests para un parche que nombraba noche.js, buscar.html e index.html."""
        out = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or any(part in SKIP_DIRS for part in p.relative_to(self.root).parts):
                continue
            rel = p.relative_to(self.root).as_posix()
            if re.search(rf"(?<![\w/.-]){re.escape(rel)}(?![\w-])", task) or (
                    "/" in rel and re.search(rf"(?<![\w/.-]){re.escape(p.name)}(?![\w-])", task)
                    and not (self.root / p.name).is_file()):
                out.append(rel)
        return out

    def run_check(self) -> str:
        if not self.check:
            return ""
        self.say(f"Comprobando: {self.check}")
        t0 = time.monotonic()
        out = self.s.run_check(self.check)
        self.s._log({"tool": "run_checks", "at": time.time(), "task": self.check, "ok": True,
                     "exit": out.split("\n", 1)[0], "seconds": round(time.monotonic() - t0, 1)})
        return out

    def named_files(self, output: str) -> list[str]:
        """Rutas del repo que aparecen en la salida de los tests (el archivo del test que falla, el del error…)."""
        found = re.findall(r"[\w./\\-]+\.(?:mjs|cjs|js|ts|py|html|css|json|md)", output)
        rel = []
        for f in found:
            f = f.replace("\\", "/")
            if "/task-" in f:  # rutas absolutas de un worktree: lo que va detrás de la carpeta de la tarea
                f = f.split("/task-", 1)[1].split("/", 1)[-1]
            rel.append(f.split("file:///")[-1])
        return self.existing(rel)

    def diff(self) -> str:
        """Lo cambiado en el worktree (también los archivos nuevos), contra el último commit."""
        try:
            subprocess.run(["git", "add", "-A"], cwd=self.root, capture_output=True, timeout=60)
            p = subprocess.run(["git", "diff", "--cached", "--no-color", "-U2"], cwd=self.root,
                               capture_output=True, timeout=60)
            out = p.stdout.decode("utf-8", "replace")
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return out if len(out) <= MAX_DIFF else out[:MAX_DIFF] + "\n[… diff recortado]"

    # --- pasos
    def select_files(self, task: str, rules: str) -> list[str]:
        from localharness.repomap import repo_map

        def ask():
            raw, stats = self.s.complete(SYSTEM_SELECT, f"NORMAS:\n{rules}\n\nTAREA:\n{task}\n\nMAPA DEL REPO:\n"
                                                        f"{repo_map(self.root)[:14000]}", schema=SELECT_SCHEMA,
                                         effort=EFFORT, max_tokens=MAX_SELECT_TOKENS)
            try:
                files = json.loads(strip_fence(raw)).get("files") or []
            except (ValueError, AttributeError):
                files = []
            return self.existing(files)[:MAX_FILES], stats
        named = self.mentioned(task)
        try:
            files = self.think("elegir_archivos", task, ask, light=True)
        except ToolError as e:  # sin la lista, el planificador sigue teniendo el mapa del repo
            self.notes.append(f"- Elegir archivos: no salió ({str(e).split(';')[0]}); se planificó solo con el mapa")
            files = []
        files = list(dict.fromkeys([*named, *files]))[:MAX_FILES]
        self.say(f"Archivos para el plan: {', '.join(files) or 'ninguno'}")
        return files

    def plan_and_run(self, task: str, files: list[str], rules: str, label: str) -> dict:
        """Planifica y ejecuta. Devuelve {ok, text, written, check}."""
        self.say(f"{label}: planificando…")
        try:
            blocks = self.think(f"planificar ({label})", task, lambda: self._plan(task, files, rules))
        except ToolError as e:
            self.notes.append(f"- {label}: el plan no salió ({e})")
            return {"ok": False, "text": str(e), "written": [], "check": ""}
        self.say(f"{label}: {len(blocks)} bloques — " + "; ".join(
            f"{b.get('kind')} {b.get('path') or b.get('title') or ''}" for b in blocks)[:300])
        text, stats = self.s.execute_plan(blocks, self.check)
        self.s._log({"tool": "local_execute_plan", "at": time.time(), "task": f"plan: {stats['ok']} de "
                     f"{stats['blocks']} bloques", **stats, "blocks_ok": stats["ok"], "ok": True})
        written = [b["path"] for b in blocks if b.get("kind") in ("edit", "write") and b.get("path")]
        self.notes.append(f"- {label}: {stats['ok']} de {stats['blocks']} bloques bien"
                          + (f", {stats.get('auto_fix')} arreglo(s) automático(s)" if stats.get("auto_fix") else "")
                          + (": " + ", ".join(dict.fromkeys(written)) if written else ""))
        check = text.rsplit("## Comprobación:", 1)[-1] if "## Comprobación:" in text else ""
        out = check.split("```", 2)[1].strip() if check.count("```") >= 2 else ""
        return {"ok": stats["ok"] == stats["blocks"], "text": text, "written": written,
                "check": out, "check_ok": stats.get("check_ok")}

    def _plan(self, task: str, files: list[str], rules: str) -> tuple[list, dict]:
        """El plan y, en el log, sus bloques (el chat enseña a quién fue cada uno y cómo salió)."""
        blocks, stats = self.s.plan_blocks(task, files, rules, EFFORT)
        for b in blocks:
            self.add_template(b)
        return blocks, {**stats, "plan": [{k: b.get(k) for k in ("id", "kind", "path", "title", "after")}
                                          for b in blocks]}

    def add_template(self, b: dict) -> None:
        """Un archivo NUEVO en una carpeta con otros del mismo tipo (blog/parche-061.html junto a parche-060.html)
        se escribe copiando la estructura del más reciente. El 08/10 la entrada de blog salió sin el pie común y los
        tests de todas las entradas fallaron: el modelo no había visto ninguna."""
        path = str(b.get("path") or "")
        if b.get("kind") != "write" or not path or (self.root / path).exists():
            return
        target = self.root / path
        if not target.parent.is_dir():
            return
        siblings = sorted((p for p in target.parent.iterdir() if p.is_file() and p.suffix == target.suffix
                           and p.name != target.name), key=lambda p: (p.stat().st_mtime, p.name))
        # el más parecido de nombre (parche-060 para parche-061) y, si no hay, el último tocado
        stem = re.sub(r"\d+", "", target.stem)
        alike = [p for p in siblings if re.sub(r"\d+", "", p.stem) == stem] or siblings
        if not alike:
            return
        tpl = alike[-1].relative_to(self.root).as_posix()
        b["files"] = list(dict.fromkeys([tpl, *(b.get("files") or [])]))
        b["instructions"] = (f"{b.get('instructions') or ''}\n\nPLANTILLA: copia la estructura de `{tpl}` (mismas "
                             "etiquetas, clases, ids, scripts y enlaces comunes); cambia solo el contenido propio.")

    def fix_task(self, task: str, output: str) -> str:
        return (f"ARREGLO. La tarea original era:\n{task}\n\nYa está hecha en parte, pero la comprobación "
                f"`{self.check}` falla así:\n```\n{output[-3000:]}\n```\nHaz SOLO los cambios mínimos (bloques "
                "`edit`) para que pase, en los archivos que señala el error. Si el fallo está en un test, corrígelo "
                "para que compruebe lo que pide la tarea mirando el contenido real de los archivos; no lo vacíes ni "
                "lo relajes hasta no comprobar nada. Si falta algo que pide la tarea (un enlace, una línea del "
                "CHANGELOG…), añádelo.")

    def review(self, task: str, rules: str) -> dict:
        diff = self.diff()
        if not diff.strip():
            return {"ok": False, "problems": ["no hay ningún cambio en el repo"], "summary": ""}

        def ask():
            raw, stats = self.s.complete(SYSTEM_REVIEW, f"TAREA:\n{task}\n\nNORMAS:\n{rules}\n\nDIFF:\n{diff}",
                                         schema=REVIEW_SCHEMA, effort=EFFORT, max_tokens=MAX_REVIEW_TOKENS)
            try:
                data = json.loads(strip_fence(raw))
            except ValueError:
                data = {"ok": True, "problems": [], "summary": "(la revisión no devolvió JSON)"}
            return data, stats
        return self.think("revisar", task, ask)

    # --- todo
    def run(self, task: str) -> str:
        rules = self.rules()
        files = self.select_files(task, rules)
        res = self.plan_and_run(task, files, rules, "Plan")
        touched = list(dict.fromkeys([*files, *res["written"]]))
        check_out = res["check"]
        rounds = 0
        while self.check and check_out and check_failed(check_out) and rounds < FIX_ROUNDS and not self.late():
            rounds += 1
            self.say(f"Los tests fallan: arreglo {rounds} de {FIX_ROUNDS}")
            fix_files = list(dict.fromkeys([*self.named_files(check_out), *touched]))[:MAX_FILES]
            res = self.plan_and_run(self.fix_task(task, check_out), fix_files, rules, f"Arreglo {rounds}")
            touched = list(dict.fromkeys([*touched, *res["written"]]))
            check_out = res["check"] or self.run_check()
        verdict = {"ok": True, "problems": [], "summary": ""}
        if not self.late():
            self.say("Revisando el diff contra el encargo…")
            try:
                verdict = self.review(task, rules)
            except ToolError as e:
                verdict = {"ok": True, "problems": [], "summary": f"(no se pudo revisar: {e})"}
            for n in range(REVIEW_ROUNDS):
                if verdict.get("ok") or not verdict.get("problems") or self.late():
                    break
                self.say(f"La revisión pide cambios: {'; '.join(verdict['problems'])[:300]}")
                problems = "\n".join(f"- {p}" for p in verdict["problems"])
                fix = (f"CORRECCIONES DE LA REVISIÓN. La tarea era:\n{task}\n\nEl revisor encontró estos problemas "
                       f"en lo hecho:\n{problems}\n\nCorrígelos con cambios mínimos (bloques `edit`).")
                res = self.plan_and_run(fix, touched[:MAX_FILES], rules, f"Corrección {n + 1}")
                touched = list(dict.fromkeys([*touched, *res["written"]]))
                check_out = res["check"] or self.run_check()
                try:
                    verdict = self.review(task, rules)
                except ToolError:
                    break
        return self.report(verdict, check_out)

    def report(self, verdict: dict, check_out: str) -> str:
        green = bool(check_out) and not check_failed(check_out)
        head = ("Hecho por el jefe local (sin Claude). "
                + (f"`{self.check}` pasa." if green else
                   f"`{self.check}` sigue fallando." if self.check and check_out else "Sin comprobación."))
        lines = [head, "", verdict.get("summary") or "", "", "**Qué hizo cada paso**", *self.notes]
        if verdict.get("problems"):
            lines += ["", "**Pendiente según la revisión local**", *[f"- {p}" for p in verdict["problems"]]]
        if self.check and check_out and not green:
            lines += ["", "**Salida de los tests**", "```", check_out[-1500:], "```"]
        if self.late():
            lines += ["", "(Se acabó el tiempo de la tarea: se paró entre pasos.)"]
        return "\n".join(x for x in lines if x is not None).strip()


def detect_check(root: Path) -> str:
    """La orden de tests del repo si no se configuró: `npm test` si package.json la define (así corre también el
    pretest: en poeta regenera los índices, y con `node --test` el jefe perseguía fallos de archivos generados),
    node --test si no; unittest si hay tests de Python."""
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            has_test = bool((json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}).get("test"))
        except (OSError, ValueError, AttributeError):
            has_test = False
        return "npm test" if has_test else "node --test"
    if (root / "pyproject.toml").is_file() or any((root / "tests").glob("test_*.py")) or any(root.glob("test_*.py")):
        return "python -m unittest"
    return ""


PROPOSE_SCHEMA = {
    "type": "object",
    "properties": {"patches": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string"}}},
    "required": ["patches"],
}
SYSTEM_PROPOSE = (
    "Eres el jefe de producto de un proyecto que hacen solos dos modelos locales, parche a parche. Propón los "
    "SIGUIENTES parches. Cada uno es una sola línea que se pueda hacer en un rato y comprobar con tests: qué archivos "
    "crear o cambiar, las funciones con su nombre exacto y qué devuelven, y qué casos tienen que probar los tests. "
    "Lo que mejor sale a estos modelos: código con funciones puras y tests, herramientas en tools/, datos JSON, "
    "cambios repetidos en muchos archivos. Lo que peor: prosa larga (relatos, adivinanzas, poemas largos) y archivos "
    "enormes. Sigue la hoja de ruta y las normas del proyecto si las hay. No repitas nada de lo ya hecho ni lo que ya "
    "existe en el MAPA. Responde SOLO con el JSON.")


def propose_patches(server, done: list[str], n: int = 5) -> list[str]:
    """Modo continuo del autopiloto: cuando se acaba la lista, el modelo fuerte propone los `n` parches siguientes
    mirando las normas, el CHANGELOG, el mapa del repo y lo que ya se hizo. [] si no sale nada válido."""
    from localharness.repomap import repo_map
    boss = Boss(server)
    rules = boss.rules()
    done_text = "\n".join(f"- {t[:160]}" for t in done[-40:])
    user = (f"NORMAS DEL PROYECTO:\n{rules}\n\nYA HECHO (lo último):\n{done_text}\n\nMAPA DEL REPO:\n"
            f"{repo_map(server.root)[:12000]}\n\nPropón {n} parches nuevos.")

    def ask():
        raw, stats = server.complete(SYSTEM_PROPOSE, user, schema=PROPOSE_SCHEMA, effort=EFFORT, max_tokens=4000)
        try:
            items = json.loads(strip_fence(raw)).get("patches") or []
        except (ValueError, AttributeError):
            items = []
        return items, stats
    try:
        items = boss.think("proponer_parches", f"{n} parches nuevos", ask)
    except ToolError:
        return []
    seen = {t.strip().lower() for t in done}
    out = []
    for t in items:
        t = " ".join(str(t).split()).lstrip("-• ").strip()
        if len(t) >= 30 and t.lower() not in seen:
            out.append(t[:700])
            seen.add(t.lower())
    return out[:n]
