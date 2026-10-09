"""Cerebro 2 del jefe local: lo que hacía Claude dirigiendo y el jefe 1 no (banco del 09/10: con los MISMOS obreros,
Claude 96,6 % y el jefe local 20,7 %). Se elige por agente (`config.cerebro = 2`); el jefe 1 (boss.Boss) sigue igual
como línea base. Los 13 parches que el jefe 1 descartó tenían los tests en ROJO: lo que fallaba era arreglar, no
revisar. Lo que cambia:

1. **Mapa de la API** (sin modelo): qué exporta cada módulo JS y con qué parámetros. Va al planificador y a cada
   bloque de código o de tests, para que nadie importe del módulo equivocado ni invente nombres.
2. **Tests DESPUÉS del código** que comprueban, con el código delante (el jefe 1 los escribía a la vez desde la
   tarea: el 4B importó las funciones de fechas desde dinero.js, el arreglo «añadió export {…}», salió un
   `Duplicate export` y ahí murió el parche 1 y, en cascada, casi todo lo demás). Un test que el plan pone fuera de
   su ruta (fechas.test.mjs en la raíz) vuelve a la que da la tarea.
3. **Arreglos mecánicos** (sin modelo) antes de gastar una ronda: exportaciones duplicadas, un import que pide un
   nombre al módulo que no lo tiene cuando otro sí, `.js` ↔ `.mjs`.
4. **Escalera de arreglo con diagnóstico**: el jefe 1 replanificaba a ciegas con el final de la salida. Ahora el
   depurador lee el PRIMER fallo y los archivos implicados (con números de línea) y devuelve archivo, culpable
   (código o test), causa y el cambio exacto; un obrero hace solo ese cambio. Lo ya probado va en cada ronda para no
   repetirlo. Ronda 3: el archivo se reescribe entero desde la tarea (así lo resolvía Claude cuando no salía).
5. **Revisión solo con los tests en verde**, y consultiva: una ronda de corrección; si la corrección rompe los
   tests, se deshace. Rechazan el parche los tests en rojo y las guardias, no la opinión del revisor.
6. **Sistema de pensamiento por papel** (`ROLES`): cada papel del jefe (elegir archivos, planificar, diagnosticar,
   revisar) dice a qué tipo de servidor va, con qué razonamiento y con qué tope. Se cambia por agente
   (`config.roles`), p. ej. el diagnóstico a la M40 con un modelo grande: lee mucho y escribe poco, así que puede
   ser lento. Si un modelo «se queda pensando», se repite UNA vez con el razonamiento apagado.
"""

import json
import os
import re
import time
from pathlib import Path

from localharness.boss import REWRITE_UNDER, SKIP_DIRS, Boss
from localharness.mcp_local import ToolError, check_failed, is_test_path, strip_fence

# papel → {tipo: a qué clase de servidor va (route de mcp_local), servidor: id concreto (opcional), effort:
# razonamiento de gpt-oss, pensar: apagado|normal|profundo (manda sobre el del servidor), max_tokens}
ROLES: dict[str, dict] = {
    "elegir_archivos": {"tipo": "local_ask", "effort": "low", "max_tokens": 3000},
    "planificar": {"tipo": "local_agent", "effort": "low"},
    "diagnosticar": {"tipo": "local_agent", "effort": "low", "max_tokens": 3000},
    "revisar": {"tipo": "local_agent", "effort": "low", "max_tokens": 4000},
}
LADDER = ("quirurgico", "quirurgico", "reescribir", "quirurgico")  # una entrada por ronda de arreglo
MAX_MECHANICAL = 3      # pasadas de arreglos mecánicos por parche (cada una arregla algo de verdad o no cuenta)
MAX_DIAG_FILES = 4
MAX_DIAG_FILE_CHARS = 7000
MAX_FAIL_CHARS = 2500
MAX_API = 5000
JS = (".js", ".mjs")

EXPORT_DECL = re.compile(r"^[ \t]*export[ \t]+(?:default[ \t]+)?(?:async[ \t]+)?(?:function[ \t]*\*?[ \t]*"
                         r"([A-Za-z_$][\w$]*)[ \t]*\(([^)]*)\)|(?:const|let|var|class)[ \t]+([A-Za-z_$][\w$]*))",
                         re.M)
EXPORT_LIST = re.compile(r"^[ \t]*export[ \t]*\{([^}]*)\}[ \t]*(from[ \t]*['\"][^'\"]+['\"])?[ \t]*;?[ \t]*\n?", re.M)
IMPORT_NAMED = re.compile(r"^([ \t]*)import[ \t]*\{([^}]*)\}[ \t]*from[ \t]*(['\"])(\.{1,2}/[^'\"]+)\3[ \t]*;?",
                          re.M)

DIAG_SCHEMA = {
    "type": "object",
    "properties": {"archivo": {"type": "string"}, "culpable": {"type": "string", "enum": ["codigo", "test"]},
                   "causa": {"type": "string"}, "cambio": {"type": "string"}},
    "required": ["archivo", "culpable", "causa", "cambio"],
}
SYSTEM_DIAG = (
    "Eres el depurador de un equipo de modelos locales. Te paso la TAREA (es la especificación), la salida de la "
    "comprobación que FALLA y los archivos implicados con números de línea. Encuentra la causa del PRIMER fallo y "
    "di el cambio exacto que lo arregla. Los valores y casos de la TAREA mandan: si un test comprueba lo que dice la "
    "tarea y falla, el culpable es el CÓDIGO; el test solo es culpable si importa mal, tiene un error de sintaxis o "
    "espera algo distinto de lo que dice la tarea. `archivo`: la ruta del archivo que hay que cambiar (uno de los "
    "que te paso). `causa`: una frase. `cambio`: instrucción exacta y corta para otro modelo que verá ese archivo: "
    "qué función o línea, qué hay ahora y qué tiene que haber (p. ej. «en diasDelMes los casos 3, 5, 8 y 10 "
    "devuelven 30 y el default 31»). Nunca cambies el valor esperado de un test que copia la tarea ni metas casos "
    "especiales o números fijos. No repitas nada de YA PROBADO: no funcionó. Responde SOLO con el JSON.")


# --- módulos JS (sin modelo)
def exports_of(text: str) -> dict[str, str]:
    """Nombres que exporta un módulo ES → sus parámetros ("" si no es una función)."""
    out: dict[str, str] = {}
    for m in EXPORT_DECL.finditer(text):
        if m.group(1):
            out[m.group(1)] = " ".join(m.group(2).split())
        elif m.group(3):
            out.setdefault(m.group(3), "")
    for m in EXPORT_LIST.finditer(text):
        for spec in m.group(1).split(","):
            name = spec.split(" as ")[-1].strip()
            if name and name != "default":
                out.setdefault(name, "")
    return out


def js_modules(root: Path) -> list[str]:
    out = []
    for p in sorted([*root.rglob("*.js"), *root.rglob("*.mjs")]):
        rel = p.relative_to(root)
        if not any(part in SKIP_DIRS for part in rel.parts) and not is_test_path(rel.as_posix()):
            out.append(rel.as_posix())
    return out


def api_map(root: Path) -> str:
    """Una línea por módulo JS (no tests): `src/dinero.js: aCentimos(valor), formatear(centimos)`."""
    lines = []
    for rel in js_modules(root):
        try:
            ex = exports_of((root / rel).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if ex:
            lines.append(f"- {rel}: " + ", ".join(f"{n}({a})" if a or _is_fn(n, root / rel) else n
                                                  for n, a in ex.items()))
    text = "\n".join(lines)
    return text if len(text) <= MAX_API else text[:MAX_API] + "\n[…]"


def _is_fn(name: str, path: Path) -> bool:
    try:
        return bool(re.search(rf"function[ \t]*\*?[ \t]*{re.escape(name)}[ \t]*\(", path.read_text(encoding="utf-8")))
    except OSError:
        return False


def rel_import(importer: str, target: str) -> str:
    spec = os.path.relpath(target, os.path.dirname(importer) or ".").replace("\\", "/")
    return spec if spec.startswith(".") else f"./{spec}"


def fix_duplicate_exports(text: str) -> tuple[str, list[str]]:
    """Quita de los `export { … }` los nombres que ya se exportan con `export function/const…` (o en otra lista
    anterior). Es el `Duplicate export of 'formatear'` que tumbó el parche 1 cinco rondas seguidas."""
    declared = {m.group(1) or m.group(3) for m in EXPORT_DECL.finditer(text)}
    seen: set[str] = set(declared)
    removed: list[str] = []

    def repl(m: re.Match) -> str:
        if m.group(2):  # re-exportación `export { x } from './y.js'`: no se toca
            return m.group(0)
        keep = []
        for spec in (s.strip() for s in m.group(1).split(",")):
            if not spec:
                continue
            name = spec.split(" as ")[-1].strip()
            if name in seen:
                removed.append(name)
            else:
                seen.add(name)
                keep.append(spec)
        if len(keep) == len([s for s in m.group(1).split(",") if s.strip()]):
            return m.group(0)
        return f"export {{ {', '.join(keep)} }};\n" if keep else ""
    new = EXPORT_LIST.sub(repl, text)
    return new, removed


def fix_imports(root: Path, rel: str, text: str, exported: dict[str, dict[str, str]]) -> tuple[str, list[str]]:
    """Imports con nombre que piden algo al módulo que no lo tiene: si OTRO módulo del repo lo exporta (uno solo),
    se importa de ahí; si la ruta no existe y la misma con .js/.mjs sí, se corrige la extensión."""
    notes: list[str] = []

    def resolve(spec: str) -> str | None:
        try:
            return (root / rel).parent.joinpath(spec).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return None

    def repl(m: re.Match) -> str:
        indent, names, quote, spec = m.groups()
        target = resolve(spec)
        ext_fixed = False
        if target is None:
            return m.group(0)
        if target not in exported:
            stem = target.rsplit(".", 1)[0]
            alt = next((t for t in (f"{stem}.js", f"{stem}.mjs") if t in exported), None)
            if not alt:
                return m.group(0)
            notes.append(f"{rel}: {spec} → {rel_import(rel, alt)} (la extensión no era la del archivo)")
            target, spec, ext_fixed = alt, rel_import(rel, alt), True
        have = exported[target]
        specs = [s.strip() for s in names.split(",") if s.strip()]
        keep, moved = [], {}
        for s in specs:
            name = s.split(" as ")[0].strip()
            if name in have:
                keep.append(s)
                continue
            owners = [t for t, ex in exported.items() if name in ex and t != rel]
            if len(owners) != 1:
                return m.group(0)  # no se sabe de dónde: que lo vea el depurador
            moved.setdefault(owners[0], []).append(s)
        if not moved:
            return f"{indent}import {{ {', '.join(keep)} }} from {quote}{spec}{quote};" if ext_fixed else m.group(0)
        lines = [f"{indent}import {{ {', '.join(keep)} }} from {quote}{spec}{quote};"] if keep else []
        for owner, ss in moved.items():
            lines.append(f"{indent}import {{ {', '.join(ss)} }} from {quote}{rel_import(rel, owner)}{quote};")
            notes.append(f"{rel}: {', '.join(s.split(' as ')[0].strip() for s in ss)} se importa de {owner}, que es "
                         "quien lo exporta")
        return "\n".join(lines)
    return IMPORT_NAMED.sub(repl, text), notes


# --- salida de los tests
def first_failure(output: str) -> str:
    """Lo útil para diagnosticar: las guardias (si las hay) y el PRIMER fallo, no 3.000 letras del final."""
    parts = []
    if "GUARDIAS DEL JEFE" in output:
        block = output.split("GUARDIAS DEL JEFE", 1)[1].split("\n\n", 1)[0]
        parts.append("GUARDIAS DEL JEFE" + block)
    for marker in ("✖ failing tests:", "FAIL:", "ERROR:", "\nnot ok "):
        if marker in output:
            parts.append(output[output.index(marker):][:MAX_FAIL_CHARS])
            break
    else:
        m = re.search(r"^\s*✖ .*$", output, re.M)
        parts.append(output[m.start():][:MAX_FAIL_CHARS] if m else output[-MAX_FAIL_CHARS:])
    return "\n\n".join(parts).strip()


def numbered(text: str) -> str:
    return "\n".join(f"{i:4} | {line}" for i, line in enumerate(text.splitlines(), 1))


class Cerebro(Boss):
    RULE_LIKE = {"ENCARGO.md", "AGENTS.md", "CLAUDE.md", "README.md", "CHANGELOG.md", "package.json"}

    def __init__(self, server, check: str = "", say=lambda text: None, deadline: float | None = None,
                 roles: dict | None = None):
        super().__init__(server, check=check, say=say, deadline=deadline)
        self.last_diag: str | None = None  # el último archivo que señaló el depurador
        self.roles = {k: {**v, **((roles or {}).get(k) or {})} for k, v in ROLES.items()}

    # --- sistema de pensamiento
    @staticmethod
    def role_of(tool: str) -> str:
        for role in ROLES:
            if tool.startswith(role):
                return role
        return "planificar"  # proponer parches y lo que venga: piensa como el planificador

    def think(self, tool: str, task: str, fn, light: bool = False):
        s = self.s
        role = self.role_of(tool)
        cfg = self.roles.get(role) or {}
        entry: dict = {"tool": f"jefe_local/{tool}", "at": time.time(), "task": task[:300], "role": role}
        t0 = time.monotonic()
        wanted = cfg.get("servidor") if any(x["id"] == cfg.get("servidor") for x in s.servers) else None
        order = s.route(cfg.get("tipo") or ("local_ask" if light else "local_agent"), wanted)
        s.order = order
        s.use(order[0])
        s.current = {"tool": entry["tool"], "task": entry["task"], "server": s.server_id}
        overrides = {k: cfg[k] for k in ("effort", "max_tokens", "pensar") if cfg.get(k)}
        try:
            s.overrides = overrides
            try:
                result, stats = fn()
            except ToolError as e:
                if not any(w in str(e) for w in ("bucle", "pensando", "no vale")):
                    raise
                if "pensando" in str(e):  # se comió los tokens razonando: otra vez sin razonar
                    s.overrides = {**overrides, "pensar": "apagado"}
                    entry["retry"] = "sin razonamiento"
                self.say(f"{tool}: {str(e).split(';')[0]} — lo intento otra vez"
                         + (" sin razonamiento" if "pensando" in str(e) else ""))
                result, stats = fn()
            entry.update(stats, ok=True, server=s.server_id)
            return result
        except ToolError as e:
            entry.update(ok=False, error=str(e), server=s.server_id)
            raise
        finally:
            s.overrides = {}
            entry["seconds"] = round(time.monotonic() - t0, 1)
            s._log(entry)

    # --- organizar
    def plan_check(self) -> str:
        return ""  # sin el arreglo automático a ciegas de execute_plan: los arreglos son de la escalera

    def code_for_test(self, test: str, blocks: list) -> tuple[list[str], list[str]]:
        """(ids de los bloques de código del plan, rutas) que comprueba un test: el del mismo nombre
        (tests/dinero.test.mjs → src/dinero.js); si no hay, los módulos que nombran sus instrucciones; si no, todos."""
        code = [b for b in blocks if b.get("kind") in ("edit", "write") and b.get("path")
                and not is_test_path(str(b["path"])) and Path(str(b["path"])).suffix in JS]
        stem = Path(test).name.split(".")[0]
        same = [b for b in code if Path(str(b["path"])).name.split(".")[0] == stem]
        text = str(next((b.get("instructions") for b in blocks if b.get("path") == test), "") or "")
        named = [b for b in code if str(b["path"]) in text or Path(str(b["path"])).name in text]
        chosen = same or named or code
        paths = [str(b["path"]) for b in chosen]
        for rel in js_modules(self.root):  # el módulo ya existe y este plan no lo toca
            if Path(rel).name.split(".")[0] == stem and rel not in paths:
                paths.append(rel)
        return [str(b.get("id")) for b in chosen], paths

    def shape_plan(self, task: str, blocks: list, scope: set[str] | None = None) -> list:
        named = self.task_paths(task)
        named_tests = [p for p in named if is_test_path(p)]
        for b in blocks:  # un test fuera de su sitio (fechas.test.mjs en la raíz) vuelve a la ruta de la tarea
            path = str(b.get("path") or "")
            if path and is_test_path(path) and path not in named_tests:
                same = [t for t in named_tests if Path(t).name == Path(path).name]
                if len(same) == 1:
                    self.notes.append(f"- {path} → {same[0]} (la ruta que da la tarea)")
                    b["path"] = same[0]
        out = super().shape_plan(task, blocks, scope)
        api = api_map(self.root)
        tests = [b for b in out if is_test_path(str(b.get("path") or ""))]
        rest = [b for b in out if b not in tests]
        for b in rest:
            if Path(str(b.get("path") or "")).suffix in JS and api:
                b["instructions"] = (f"{b.get('instructions') or ''}\n\nMÓDULOS QUE YA EXISTEN (importa de aquí, "
                                     f"con estos nombres exactos y del archivo que los exporta):\n{api}")
        for b in tests:
            if not b.pop("spec", False) or scope is not None:
                continue
            ids, paths = self.code_for_test(str(b["path"]), rest)
            b["after"] = [i for i in ids if i != b.get("id")]
            b["files"] = list(dict.fromkeys([*paths, *(b.get("files") or [])]))[:6]
            if str(b.get("id", "")).startswith("spec-test-"):
                b["instructions"] = (
                    f"Escribe el archivo de tests {b['path']} con los casos que pide para él la TAREA de abajo (solo "
                    "los de este archivo), con node:test y node:assert/strict y un test() por caso, todos al nivel "
                    "superior (nunca un test dentro de otro). El código que se prueba YA ESTÁ ESCRITO y lo tienes en "
                    "ARCHIVOS DE CONTEXTO: importa cada función del archivo que la exporta, con su nombre exacto. "
                    f"Los valores esperados salen de la TAREA, no del código.\n\nTAREA:\n{task}"
                    f"{self.skill('tests-de-especificacion')}")
            else:
                b["instructions"] = (f"{b.get('instructions') or ''}\n\nEl código que se prueba YA ESTÁ ESCRITO (en "
                                     "ARCHIVOS DE CONTEXTO): importa cada función del archivo que la exporta.")
        # los tests al final: `after` solo puede apuntar a bloques anteriores
        return rest + tests

    # --- arreglos sin modelo
    def mechanical(self) -> list[str]:
        changed = [p for p in self.changed() if Path(p).suffix in JS]
        if not changed:
            return []
        notes: list[str] = []
        for rel in changed:
            if is_test_path(rel):
                continue
            path = self.root / rel
            text = path.read_text(encoding="utf-8", errors="replace")
            new, removed = fix_duplicate_exports(text)
            if removed:
                path.write_text(new, encoding="utf-8", newline="\n")
                notes.append(f"{rel}: fuera el export duplicado de {', '.join(dict.fromkeys(removed))}")
        exported = {}
        for rel in js_modules(self.root):
            try:
                exported[rel] = exports_of((self.root / rel).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        for rel in changed:
            path = self.root / rel
            text = path.read_text(encoding="utf-8", errors="replace")
            new, fixed = fix_imports(self.root, rel, text, exported)
            if fixed and new != text:
                path.write_text(new, encoding="utf-8", newline="\n")
                notes += fixed
        return notes

    # --- escalera de arreglo
    def related(self, path: str) -> list[str]:
        """Los módulos que importa `path` (y, si es un módulo, su test): lo que hay que ver para arreglarlo."""
        out = []
        try:
            text = (self.root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return out
        for m in IMPORT_NAMED.finditer(text):
            try:
                dep = (self.root / path).parent.joinpath(m.group(4)).resolve().relative_to(self.root.resolve())
            except ValueError:
                continue
            if (self.root / dep).is_file():
                out.append(dep.as_posix())
        stem = Path(path).name.split(".")[0]
        if not is_test_path(path):
            out += [t for t in self.changed() if is_test_path(t) and Path(t).name.split(".")[0] == stem]
        return list(dict.fromkeys(x for x in out if x != path))

    def diagnose(self, task: str, output: str, tried: list[str], touched: list[str]) -> dict | None:
        fail = first_failure(output)
        named = self.named_files(fail) or self.named_files(output)
        files = list(dict.fromkeys([*named, *(d for f in named for d in self.related(f))]))
        if not files:
            files = [t for t in touched if (self.root / t).is_file()]
        files = files[:MAX_DIAG_FILES]
        ctx = "\n\n".join(f"--- {f} ---\n{numbered((self.root / f).read_text(encoding='utf-8', errors='replace'))}"
                          [:MAX_DIAG_FILE_CHARS] for f in files)
        user = (f"TAREA:\n{task}\n\nFALLA ASÍ (`{self.check or 'guardias'}`):\n```\n{fail}\n```\n\nARCHIVOS:\n{ctx}"
                + ("\n\nYA PROBADO (no funcionó):\n" + "\n".join(f"- {t}" for t in tried) if tried else ""))

        def ask():
            raw, stats = self.s.complete(SYSTEM_DIAG, user, schema=DIAG_SCHEMA)
            try:
                data = json.loads(strip_fence(raw))
            except ValueError:
                data = {}
            return data, stats
        try:
            d = self.think("diagnosticar", task, ask)
        except ToolError as e:
            self.notes.append(f"- Diagnóstico: no salió ({str(e).split(';')[0]})")
            return None
        path = str(d.get("archivo") or "").strip().replace("\\", "/").removeprefix("./")
        if not path or not (self.root / path).is_file() or not str(d.get("cambio") or "").strip():
            self.notes.append(f"- Diagnóstico sin archivo válido ({path or 'ninguno'})")
            return None
        self.last_diag = path
        return {**d, "archivo": path, "files": [f for f in files if f != path]}

    def block_for(self, path: str, instructions: str, files: list[str], bid: str) -> dict:
        size = (self.root / path).stat().st_size if (self.root / path).is_file() else 0
        if Path(path).suffix in JS and not is_test_path(path):
            instructions += self.skill("modulos-es")
        return {"id": bid, "kind": "write" if size < REWRITE_UNDER else "edit", "path": path, "after": [],
                "title": f"{bid}: {path}", "instructions": instructions,
                "files": list(dict.fromkeys(files or self.related(path)))[:5]}

    def run_blocks(self, blocks: list, label: str) -> bool:
        text, stats = self.s.execute_plan(blocks, "")
        self.s._log({"tool": "local_execute_plan", "at": time.time(), "task": f"{label}: {stats['ok']} de "
                     f"{stats['blocks']} bloques", **stats, "blocks_ok": stats["ok"], "ok": True})
        return stats["ok"] == stats["blocks"]

    def surgical(self, d: dict, n: int) -> str:
        instructions = (f"{d['cambio'].strip()}\n\n(Causa: {str(d.get('causa') or '').strip()}.) Haz SOLO este "
                        "cambio y deja todo lo demás igual: mismos nombres, mismas exportaciones, mismos tests.")
        ok = self.run_blocks([self.block_for(d["archivo"], instructions, d.get("files") or [], f"diag{n}")],
                             f"Arreglo {n}")
        self.notes.append(f"- Arreglo {n} (diagnóstico): {d['archivo']} — {str(d.get('causa') or '')[:160]}"
                          + ("" if ok else " (el obrero no pudo aplicarlo)"))
        return f"{d['archivo']}: {str(d.get('cambio') or '')[:200]}"

    def rewrite(self, task: str, output: str, d: dict | None, tried: list[str], touched: list[str], n: int) -> str:
        fail = first_failure(output)
        named = self.named_files(fail) or self.named_files(output)
        # el que señaló el último diagnóstico; si no, código antes que tests (la salida suele nombrar solo el test)
        pool = [f for f in dict.fromkeys([*named, *touched]) if (self.root / f).is_file()]
        path = (d or {}).get("archivo") or self.last_diag or next(
            (f for f in pool if not is_test_path(f) and f not in self.RULE_LIKE), None) or next(iter(pool), None)
        if not path:
            self.notes.append(f"- Arreglo {n}: no sé qué archivo reescribir")
            return "nada"
        spec = self.skill("tests-de-especificacion") if is_test_path(path) else ""
        instructions = (f"Reescribe {path} ENTERO y desde cero para que cumpla la TAREA: la versión actual tiene "
                        "fallos que no se han podido arreglar a trozos. Mismos nombres de funciones y de exportaciones "
                        f"que pide la tarea.\n\nTAREA:\n{task}\n\nASÍ FALLA AHORA:\n```\n{fail}\n```"
                        + ("\n\nYA PROBADO (no funcionó):\n" + "\n".join(f"- {t}" for t in tried) if tried else "")
                        + spec)
        block = self.block_for(path, instructions, self.related(path), f"reescribir{n}")
        block["kind"] = "write"
        ok = self.run_blocks([block], f"Arreglo {n}")
        self.notes.append(f"- Arreglo {n} (reescritura entera): {path}" + ("" if ok else " (no salió)"))
        return f"{path}: reescrito entero"

    # --- todo
    def run(self, task: str) -> str:
        rules = self.rules()
        api = api_map(self.root)
        if api:
            rules += f"\n\n### Módulos que ya existen (qué exporta cada uno)\n{api}"
        files = self.select_files(task, rules)
        res = self.plan_and_run(task, files, rules, "Plan")
        touched = list(dict.fromkeys([*files, *res["written"]]))
        out = self.verify()
        tried: list[str] = []
        rounds = mech = 0
        while out and check_failed(out) and rounds < len(LADDER) and not self.late():
            if mech < MAX_MECHANICAL:
                fixed = self.mechanical()
                if fixed:
                    mech += 1
                    self.say("Arreglo mecánico: " + "; ".join(fixed)[:300])
                    self.notes.append("- Arreglo mecánico (sin modelo): " + "; ".join(fixed))
                    out = self.verify()
                    continue
            rounds += 1
            self.say(f"Falla: arreglo {rounds} de {len(LADDER)} ({LADDER[rounds - 1]})")
            d = self.diagnose(task, out, tried, touched) if LADDER[rounds - 1] == "quirurgico" else None
            if d:
                tried.append(self.surgical(d, rounds))
                touched = list(dict.fromkeys([*touched, d["archivo"]]))
            else:
                tried.append(self.rewrite(task, out, None, tried, touched, rounds))
            out = self.verify()
        green = not (out and check_failed(out))
        verdict = {"ok": True, "problems": [], "summary": ""}
        if green and self.changed() and not self.late():
            verdict = self.advisory_review(task, rules, touched)
        if not self.changed():
            return self.report(verdict, out)
        if "GUARDIAS DEL JEFE" in (out or ""):
            self.rejected.append("guardias: " + "; ".join(ln[2:] for ln in out.splitlines() if ln.startswith("- ")))
        return self.report(verdict, out)

    def advisory_review(self, task: str, rules: str, touched: list[str]) -> dict:
        """Con los tests en verde: revisión, una corrección y, si la corrección rompe algo, se deshace. Lo que quede
        va al informe como pendiente, pero no impide integrar."""
        self.say("Revisando el diff contra el encargo…")
        try:
            verdict = self.review(task, self.rules())
        except ToolError as e:
            return {"ok": True, "problems": [], "summary": f"(no se pudo revisar: {e})"}
        if verdict.get("ok") or not verdict.get("problems") or self.late():
            return verdict
        self.say(f"La revisión pide cambios: {'; '.join(verdict['problems'])[:300]}")
        before = {p: (self.root / p).read_bytes() for p in self.changed()}
        problems = "\n".join(f"- {p}" for p in verdict["problems"])
        fix = (f"CORRECCIONES DE LA REVISIÓN. La tarea era:\n{task}\n\nEl revisor encontró estos problemas en lo "
               f"hecho:\n{problems}\n\nCorrige solo los que sean ciertos, con cambios mínimos. Los tests ya pasan: no "
               "los rompas ni cambies sus valores esperados.")
        named = [p for p in self.task_paths(" ".join(verdict["problems"])) if (self.root / p).is_file()]
        scope = {*touched, *named, *self.task_paths(task), *self.changed()}
        self.plan_and_run(fix, list(dict.fromkeys([*named, *touched]))[:8], rules, "Corrección", scope, spec=task)
        after = self.verify()
        if after and check_failed(after):
            for p in self.changed():
                if p in before:
                    (self.root / p).write_bytes(before[p])
                else:
                    (self.root / p).unlink(missing_ok=True)
            self.notes.append("- Corrección de la revisión: rompía los tests y se deshizo")
            return {**verdict, "ok": True}
        self.notes.append("- Corrección de la revisión: hecha y los tests siguen pasando")
        return {**verdict, "ok": True, "problems": []}
