"""Jefe local: el modo 100 % local. Hace lo que hacía el jefe Claude en el autopiloto, pero con los modelos locales y
como una tubería fija en vez de un agente libre (los bucles de agente local se atascaban: el 08/10, 29 llamadas a
`local_agent` y 93 min casi todos parados). Pasos:

1. contexto: normas del proyecto (ENCARGO.md, README…), mapa del repo y final del CHANGELOG;
2. elegir archivos: el modelo fuerte dice qué archivos necesita ver el plan (JSON validado);
3. planificar: bloques edit/write con instrucciones autocontenidas (mcp_local.plan_blocks, validado);
4. ejecutar: los bloques van a la vez a los modelos libres (mcp_local.execute_plan, con su arreglo automático);
5. comprobar y arreglar: si los tests fallan, un plan de arreglo con la salida delante (hasta FIX_ROUNDS);
6. revisar: el modelo fuerte lee el diff contra el encargo (JSON ok/problemas); si hay problemas, hasta dos rondas;
7. informe: qué se hizo, qué falló y qué queda.

Lo que se aprendió el 09/10 (autopiloto «mario», 40 parches): con solo `npm test` como puerta se integraron 39, pero
22 tenían la revisión en contra y el juego no arrancaba (módulos con errores de sintaxis, un JSON en vez de código,
marcas de un bloque de edición dentro de render.js) porque ningún test los importaba; 33 de 52 planes no traían los
tests que pedía la tarea. Por eso ahora:
- guardias deterministas tras cada ronda (`gates`): marcas de edición, módulos JS que no cargan o importan lo que no
  existe, Python que no compila. Cuentan como tests que fallan: entran en las rondas de arreglo;
- si al final quedan guardias o problemas de la revisión, el parche se RECHAZA (`rejected`): no se integra;
- los tests que nombra la tarea y el plan olvida se añaden solos y se escriben desde la tarea, a la vez que el código
  (`spec`), con la skill tests-de-especificacion;
- un `edit` de un archivo pequeño se hace reescribiéndolo (editar fallaba el 24 % de las veces a gpt-oss; reescribir,
  ninguna);
- las rondas de arreglo solo tocan lo que ya se tocó, lo que nombra el error y lo que nombra la tarea (se iban a
  12 archivos y creaban duplicados como mapa.mjs).

Todo lo que se pide a los modelos queda en el log de encargos (`LH_LOG`), así que la oficina, el panel de
analítica y el informe del autopiloto lo ven igual que con Claude. Coste: 0 $.
"""

import json
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from localharness.edits import MARKER
from localharness.mcp_local import ToolError, check_failed, is_test_path, strip_fence

FIX_ROUNDS = 3        # rondas de arreglo tras el plan (además de la del propio execute_plan)
REVIEW_ROUNDS = 2     # rondas de corrección tras la revisión (si después sigue en contra, se rechaza)
REWRITE_UNDER = 4000  # un `edit` de un archivo más pequeño que esto (caracteres) se hace reescribiéndolo entero
REJECTED = "Rechazado por el jefe local"  # primera línea del informe de un parche que no debe integrarse
GATE_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".py", ".html", ".css", ".json"}
GATE_TIMEOUT = 60
# lo que delata que un módulo JS no carga (sí: un error de sintaxis o un import roto; no: `document is not defined`
# al cargar un main.js de navegador en Node)
LOAD_ERRORS = ("SyntaxError", "does not provide an export named", "Cannot find module", "ERR_MODULE_NOT_FOUND",
               "Unexpected token", "Cannot find package")
NODE_IMPORT = r"""
import { pathToFileURL } from "node:url";
for (const f of JSON.parse(process.argv[1])) {
  try { await import(pathToFileURL(f).href); }
  catch (e) { console.log(JSON.stringify({ f, name: e && e.name, code: e && e.code, m: String(e && e.message || e).split("\n")[0] })); }
}
process.exit(0);
"""
PATH_TOKEN = re.compile(r"(?<![\w/.-])((?:[\w-]+/)*[\w.-]+\.(?:mjs|cjs|js|ts|py|html|css|json|md))(?![\w-])")
IMPORT_FROM = re.compile(r"""(?:from|import)\s*\(?\s*['"](\.{1,2}/[^'"]+)['"]""")
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
    "con el archivo y qué cambiar; nada de gustos ni mejoras opcionales. Mira sobre todo: que cada archivo exporte "
    "las funciones con el nombre y los parámetros que dice la tarea; que importe todo lo que usa y desde el archivo "
    "que lo exporta; que sea código y no un JSON o texto; que los tests comprueben los valores exactos que da la "
    "tarea (no otros inventados) y que no se haya cambiado un test o metido un número fijo para que pase. Si todo "
    "está bien: ok=true y problems=[]. Si hay problemas, el parche NO se integra: no pidas lo que la tarea no pide. "
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
        self.rejected: list[str] = []  # por qué no debe integrarse (vacío = se puede integrar)
        self._skills: dict | None = None

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

    def skill(self, name: str) -> str:
        """El cuerpo de una skill del catálogo (skills/), para pegarlo en un encargo; "" si no está."""
        if self._skills is None:
            from localharness.context import load_skills
            try:
                self._skills = load_skills()
            except OSError:
                self._skills = {}
        s = self._skills.get(name)
        return f"\n\nREGLAS ({name}):\n{s.body.strip()}" if s else ""

    def task_paths(self, task: str) -> list[str]:
        """Rutas de archivo que nombra la tarea (existan o no): `src/estrella.js`, `tests/mapa.test.mjs`…"""
        return list(dict.fromkeys(m.group(1).removeprefix("./") for m in PATH_TOKEN.finditer(task)))

    def changed(self) -> list[str]:
        """Archivos cambiados o nuevos en el worktree (contra el último commit), que sigan existiendo."""
        try:
            p = subprocess.run(["git", "-c", "core.quotepath=off", "status", "--porcelain", "-uall"], cwd=self.root,
                               capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return []
        out = []
        for line in p.stdout.decode("utf-8", "replace").splitlines():
            path = line[3:].split(" -> ")[-1].strip().strip('"')
            if path and (self.root / path).is_file():
                out.append(path)
        return out

    def importers(self, targets: set[str]) -> list[str]:
        """Módulos JS del repo (no tests) que importan alguno de `targets`: si jugador.js deja de exportar
        crearJugador, el que se rompe es partida.js, que no se tocó."""
        out = []
        for p in sorted([*self.root.rglob("*.js"), *self.root.rglob("*.mjs")]):
            rel = p.relative_to(self.root)
            if any(part in SKIP_DIRS for part in rel.parts) or is_test_path(rel.as_posix()):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for spec in IMPORT_FROM.findall(text):
                try:
                    dep = (p.parent / spec).resolve().relative_to(self.root.resolve()).as_posix()
                except ValueError:
                    continue
                if dep in targets:
                    out.append(rel.as_posix())
                    break
        return out

    def gates(self) -> list[str]:
        """Guardias que no dependen de los tests del proyecto: lo que el 09/10 se integró roto con `npm test` en
        verde. Devuelve los problemas (vacío = todo bien)."""
        import shutil
        import sys
        problems: list[str] = []
        changed = [p for p in self.changed() if Path(p).suffix.lower() in GATE_SUFFIXES]
        for rel in changed:
            try:
                text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if MARKER.search(text):
                problems.append(f"{rel}: tiene líneas <<<<<<< / ======= / >>>>>>> de un bloque de edición mal "
                                "aplicado; quítalas y deja el código que toca")
        js = [p for p in changed if Path(p).suffix in (".js", ".mjs") and not is_test_path(p)]
        node = shutil.which("node")
        if js and node:
            module = Path(js[0]).suffix == ".mjs"
            try:
                module = module or json.loads((self.root / "package.json").read_text(encoding="utf-8")).get(
                    "type") == "module"
            except (OSError, ValueError, AttributeError):
                pass
            targets = list(dict.fromkeys([*js, *self.importers(set(js))]))
            if module:
                try:
                    p = subprocess.run([node, "--input-type=module", "-e", NODE_IMPORT, json.dumps(targets)],
                                       cwd=self.root, capture_output=True, timeout=GATE_TIMEOUT)
                    for line in p.stdout.decode("utf-8", "replace").splitlines():
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        if any(k in f"{e.get('name')} {e.get('code')} {e.get('m')}" for k in LOAD_ERRORS):
                            problems.append(f"{e['f']}: no carga como módulo: {e['m'][:200]}")
                except (OSError, subprocess.TimeoutExpired):
                    pass
            else:
                for rel in targets:
                    try:
                        p = subprocess.run([node, "--check", rel], cwd=self.root, capture_output=True, timeout=30)
                    except (OSError, subprocess.TimeoutExpired):
                        continue
                    if p.returncode:
                        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
                        problems.append(f"{rel}: error de sintaxis: {(err[-1] if err else '')[:200]}")
        for rel in (p for p in changed if p.endswith(".py")):
            try:
                p = subprocess.run([sys.executable, "-m", "py_compile", rel], cwd=self.root, capture_output=True,
                                   timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if p.returncode:
                err = p.stderr.decode("utf-8", "replace").strip().splitlines()
                problems.append(f"{rel}: no compila: {(err[-1] if err else '')[:200]}")
        return problems

    def verify(self, res: dict | None = None) -> str:
        """La salida de la comprobación (la que ya trae `res` o una nueva) con las guardias delante: si alguna
        falla, cuenta como tests que fallan, aunque `npm test` pase."""
        out = (res or {}).get("check") or self.run_check()
        problems = self.gates()
        if not problems:
            return out
        self.say(f"Guardias: {'; '.join(problems)[:300]}")
        rest = out.split("\n", 1)[1] if out.startswith("código de salida ") and "\n" in out else out
        return ("código de salida 1\nGUARDIAS DEL JEFE LOCAL (fallan aunque los tests pasen):\n"
                + "\n".join(f"- {p}" for p in problems) + (f"\n\n{rest}" if rest.strip() else ""))

    def shape_plan(self, task: str, blocks: list, scope: set[str] | None = None) -> list:
        """Ajusta el plan del modelo antes de ejecutarlo. `scope` (rondas de arreglo): solo esos archivos.
        Sin `scope` (plan principal): añade los tests que nombra la tarea y el plan olvidó."""
        named = self.task_paths(task)
        named_tests = [p for p in named if is_test_path(p)]
        out, dropped, gone = [], [], set()
        stems = {p.with_suffix("").as_posix() for p in (Path(x) for x in self.existing_code())}
        for b in blocks:
            path = str(b.get("path") or "")
            kind = b.get("kind")
            if kind in ("edit", "write") and path:
                exists = (self.root / path).is_file()
                if scope is not None and path not in scope:
                    dropped.append(path)
                    gone.add(str(b.get("id")))
                    continue
                if scope is None and not exists and path not in named and (
                        Path(path).with_suffix("").as_posix() in stems  # mapa.mjs al lado de mapa.js
                        or (Path(path).suffix == ".md" and Path(path).name not in ("CHANGELOG.md", "README.md"))):
                    dropped.append(path)
                    gone.add(str(b.get("id")))
                    continue
                if kind == "edit" and exists and (self.root / path).stat().st_size < REWRITE_UNDER:
                    b["kind"] = "write"
                if path in named_tests:
                    b["spec"] = True
                    b["after"] = []
                    b["instructions"] = (f"{b.get('instructions') or ''}\n\nCASOS EXACTOS (de la tarea original; "
                                         f"cópialos tal cual):\n{task}{self.skill('tests-de-especificacion')}")
                elif Path(path).suffix in (".js", ".mjs") and not is_test_path(path):
                    b["instructions"] = f"{b.get('instructions') or ''}{self.skill('modulos-es')}"
                if scope is not None:
                    b["instructions"] = f"{b.get('instructions') or ''}{self.skill('cambios-minimos')}"
            out.append(b)
        for b in out:  # lo que dependía de un bloque descartado ya no espera a nada (si no, el plan entero falla)
            if isinstance(b.get("after"), list):
                b["after"] = [a for a in b["after"] if str(a) not in gone]
        if scope is None:
            have = {str(b.get("path") or "") for b in out}
            example = next((t for t in self.existing_code() if is_test_path(t)), None)
            for k, path in enumerate((p for p in named_tests if p not in have and not (self.root / p).exists()), 1):
                out.append({"id": f"spec-test-{k}", "kind": "write", "path": path, "after": [], "spec": True,
                            "title": f"tests de la tarea: {path}",
                            "files": [example] if example else [],
                            "instructions": (f"Escribe el archivo de tests {path} con los casos que pide para él la "
                                             "TAREA de abajo (solo los de este archivo). El código que se prueba lo "
                                             "está escribiendo otro a la vez siguiendo la misma tarea: impórtalo "
                                             "con las rutas y los nombres que da la tarea. Si hay un test de ejemplo "
                                             "en ARCHIVOS DE CONTEXTO, sigue su estilo.\n\nTAREA:\n"
                                             f"{task}{self.skill('tests-de-especificacion')}")})
                self.notes.append(f"- El plan no traía {path}: se añadió (se escribe desde la tarea, a la vez)")
        if dropped:
            self.notes.append(f"- Fuera del plan (no se tocan): {', '.join(dict.fromkeys(dropped))}")
            self.say(f"Bloques fuera de alcance, descartados: {', '.join(dict.fromkeys(dropped))}")
        return out

    def existing_code(self) -> list[str]:
        out = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if p.is_file() and not any(part in SKIP_DIRS for part in rel.parts) and p.suffix in GATE_SUFFIXES:
                out.append(rel.as_posix())
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

    def plan_and_run(self, task: str, files: list[str], rules: str, label: str, scope: set[str] | None = None,
                     spec: str | None = None) -> dict:
        """Planifica y ejecuta. Devuelve {ok, text, written, check}. `scope`: archivos que puede tocar (rondas de
        arreglo). `spec`: la tarea original, de la que salen los tests que nombra (por defecto, `task`)."""
        self.say(f"{label}: planificando…")
        try:
            blocks = self.think(f"planificar ({label})", task, lambda: self._plan(task, files, rules))
        except ToolError as e:
            self.notes.append(f"- {label}: el plan no salió ({e})")
            return {"ok": False, "text": str(e), "written": [], "check": ""}
        blocks = self.shape_plan(spec or task, blocks, scope)
        if not blocks:
            self.notes.append(f"- {label}: ningún bloque dentro de lo que se podía tocar")
            return {"ok": False, "text": "", "written": [], "check": ""}
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
                f"`{self.check or 'de las guardias'}` falla así:\n```\n{output[-3000:]}\n```\nHaz SOLO los cambios "
                "mínimos para que pase, en los archivos que señala el error. Los casos y valores que da la tarea son "
                "la especificación: si un test los comprueba bien y falla, arregla el CÓDIGO; no cambies el valor "
                "esperado ni metas números fijos o casos especiales para que pase. Corrige un test solo si contradice "
                "a la tarea, y entonces para que compruebe exactamente lo que ella dice; no lo vacíes ni lo relajes. "
                "No crees archivos que la tarea no nombre. Si falta algo que pide la tarea (una línea del "
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
        check_out = self.verify(res)
        rounds = 0
        while check_out and check_failed(check_out) and rounds < FIX_ROUNDS and not self.late():
            rounds += 1
            self.say(f"Los tests fallan: arreglo {rounds} de {FIX_ROUNDS}")
            named = self.named_files(check_out)
            fix_files = list(dict.fromkeys([*named, *touched]))[:MAX_FILES]
            scope = {*touched, *named, *self.task_paths(task), *self.changed()}
            res = self.plan_and_run(self.fix_task(task, check_out), fix_files, rules, f"Arreglo {rounds}", scope,
                                    spec=task)
            touched = list(dict.fromkeys([*touched, *res["written"]]))
            check_out = self.verify(res)
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
                       f"en lo hecho:\n{problems}\n\nCorrígelos con cambios mínimos, sin romper lo que ya pasa.")
                named = [p for p in self.task_paths(" ".join(verdict["problems"])) if (self.root / p).is_file()]
                scope = {*touched, *named, *self.task_paths(task), *self.changed()}
                res = self.plan_and_run(fix, list(dict.fromkeys([*named, *touched]))[:MAX_FILES], rules,
                                        f"Corrección {n + 1}", scope, spec=task)
                touched = list(dict.fromkeys([*touched, *res["written"]]))
                check_out = self.verify(res)
                try:
                    verdict = self.review(task, rules)
                except ToolError:
                    break
        # lo que impide integrar: guardias que siguen fallando o una revisión en contra (el 09/10 se integraron 22
        # parches con la revisión en contra, y el juego no arrancaba)
        # sin ningún cambio no hay nada que rechazar: casi siempre es que los modelos no contestaron (el 09/10, un
        # 401 de un llama-server de antes del reinicio) y el autopiloto, al verlo «sin cambios», lo repite una vez
        if not self.changed():
            return self.report(verdict, check_out)
        if "GUARDIAS DEL JEFE" in (check_out or ""):
            self.rejected.append("guardias: " + "; ".join(ln[2:] for ln in check_out.splitlines()
                                                           if ln.startswith("- ")))
        if verdict.get("ok") is False and verdict.get("problems"):
            self.rejected.append("revisión: " + "; ".join(verdict["problems"]))
        return self.report(verdict, check_out)

    def report(self, verdict: dict, check_out: str) -> str:
        green = bool(check_out) and not check_failed(check_out)
        head = ("Hecho por el jefe local (sin Claude). "
                + (f"`{self.check}` pasa." if green else
                   f"`{self.check}` sigue fallando." if self.check and check_out else "Sin comprobación."))
        if self.rejected:
            head = f"{REJECTED} (no se integra): {' · '.join(self.rejected)[:600]}\n\n{head}"
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
