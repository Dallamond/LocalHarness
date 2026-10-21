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

import copy
import json
import os
import re
import subprocess
import time
from pathlib import Path

from localharness.boss import SKIP_DIRS, Boss, protected_paths
from localharness.mcp_local import MAX_BLOCKS, ToolError, check_failed, is_test_path, strip_fence

# papel → {tipo: a qué clase de servidor va (route de mcp_local), servidor: id concreto (opcional), effort:
# razonamiento de gpt-oss, pensar: apagado|normal|profundo (manda sobre el del servidor), max_tokens}
ROLES: dict[str, dict] = {
    "elegir_archivos": {"tipo": "local_ask", "effort": "low", "max_tokens": 3000},
    "planificar": {"tipo": "local_agent", "effort": "low"},
    "diagnosticar": {"tipo": "local_agent", "effort": "low", "max_tokens": 3000},
    "revisar": {"tipo": "local_agent", "effort": "low", "max_tokens": 4000},
}
LADDER = ("quirurgico", "quirurgico", "reescribir", "quirurgico")  # una entrada por ronda de arreglo
MAX_IDLE = 2  # rondas seguidas que dejan los archivos idénticos: a la segunda se para la escalera
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
# nombres que un archivo define él mismo (función, clase o variable), con export o sin él
DECL = re.compile(r"^[ \t]*(?:export[ \t]+)?(?:async[ \t]+)?(?:function[ \t]*\*?[ \t]*([A-Za-z_$][\w$]*)|"
                  r"class[ \t]+([A-Za-z_$][\w$]*)|(?:const|let|var)[ \t]+([A-Za-z_$][\w$]*))", re.M)
FUNC_DECL = re.compile(r"^[ \t]*(export[ \t]+)?(?:async[ \t]+)?function[ \t]*\*?[ \t]*([A-Za-z_$][\w$]*)[ \t]*\(",
                       re.M)
SPEC_PATH = r"(?:[\w-]+/)*[\w-]+(?:\.[\w-]+)*\.(?:mjs|cjs|js|ts|py|html|css)"
LEFTOVER = re.compile(r"^[ \t]*```|from[ \t]*['\"]node:(?:test|assert)", re.M)  # salida del modelo pegada en código
MISSING_MODULE = re.compile(r"Cannot find module '([^']+)'")
JEST_CALL = re.compile(r"^[ \t]*(describe|test|it|expect|beforeEach|afterEach)\s*\(", re.M)


def imported_names(text: str) -> set[str]:
    """Los nombres que un módulo importa (con nombre o por defecto) o declara al nivel superior."""
    names: set[str] = set()
    for m in re.finditer(r"import\s*(\w+)?\s*,?\s*(?:\{([^}]*)\})?\s*from", text):
        if m.group(1):
            names.add(m.group(1))
        for spec in (m.group(2) or "").split(","):
            if spec.strip():
                names.add(spec.split(" as ")[-1].strip())
    names |= set(re.findall(r"^(?:const|let|var|function)\s+(\w+)", text, re.M))
    return names
MAX_SPEC_DEPS = 3000    # caracteres de «lo que usa de otros módulos» por bloque
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
    "espera algo distinto de lo que dice la tarea. Antes de decidir, CALCULA con la fórmula de la tarea el valor que "
    "debería salir en ese caso: si el test espera otro número, prueba algo que la tarea no pide (un error, un archivo, "
    "un mensaje) o usa datos que no existen (una fila 4 en un mapa de 3), el culpable es el TEST; si el código da otro "
    "número, el CÓDIGO. `archivo`: la ruta del archivo que hay que cambiar (uno de los "
    "que te paso). `causa`: una frase. `cambio`: instrucción exacta y corta para otro modelo que verá ese archivo, "
    "con el número de línea, lo que hay y lo que tiene que haber (p. ej. «línea 27: cambia "
    "`assert.deepEqual(fila, ['.', '.'])` por `assert.equal(fila, '..')`» o «en diasDelMes los casos 3, 5, 8 y 10 "
    "devuelven 30 y el default 31»). Si el culpable es un test, quita o corrige SOLO ese caso. Nunca cambies el valor esperado de un test que copia la tarea ni metas casos "
    "especiales o números fijos. No repitas nada de YA PROBADO: no funcionó. Responde SOLO con el JSON.")


TEST_FIRST = (
    "\n\nOJO: cambiar el CÓDIGO ya se probó y no sirvió (o rompía otros tests que pasaban). Lo más probable es que el "
    "TEST espere un valor mal calculado o algo que la TAREA no pide. Mira PRIMERO el test que falla: si el valor que "
    "da el código encaja con la regla de la TAREA (y con los otros tests que pasan), el culpable es el TEST; corrige "
    "ese valor esperado o quita ese caso.")


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
                return missing_module(m, rel, target, text, exported, notes)
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


IMPORT_ANY = re.compile(r"^[ \t]*import[ \t]+(?:([A-Za-z_$][\w$]*)[ \t]*,?[ \t]*)?(?:\{([^}]*)\}|\*[ \t]+as[ \t]+"
                        r"([A-Za-z_$][\w$]*))?[ \t]*(?:from[ \t]*)?['\"][^'\"]+['\"][ \t]*;?", re.M)
CALL = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)[ \t]*\(")


def fix_missing_imports(root: Path, rel: str, text: str, exported: dict[str, dict[str, str]]) -> tuple[str, list[str]]:
    """Funciones que el archivo llama sin declararlas ni importarlas y que exporta UN solo módulo del repo: se importan
    de él. El 10/10 el 4B escribió tests/fechas.test.mjs sin `import … from '../src/fechas.js'` y el depurador culpó
    al código en las 8 rondas (`ReferenceError: sumarMeses is not defined`)."""
    have = {m.group(i) for i in (1, 2, 3) for m in DECL.finditer(text) if m.group(i)}
    for m in IMPORT_ANY.finditer(text):
        have |= {x for x in (m.group(1), m.group(3)) if x}
        have |= {s.split(" as ")[-1].strip() for s in (m.group(2) or "").split(",") if s.strip()}
    # parámetros y variables locales no se distinguen bien con regex: solo cuenta lo que exporta otro módulo
    called = list(dict.fromkeys(m.group(1) for m in CALL.finditer(text)))
    wanted: dict[str, list[str]] = {}
    for name in called:
        if name in have:
            continue
        owners = [t for t, ex in exported.items() if name in ex and t != rel]
        if len(owners) == 1:
            wanted.setdefault(owners[0], []).append(name)
    if not wanted:
        return text, []
    lines = [f"import {{ {', '.join(names)} }} from '{rel_import(rel, owner)}';" for owner, names in wanted.items()]
    imports = list(IMPORT_ANY.finditer(text))
    at = imports[-1].end() if imports else 0
    sep = "\n" if at else ""
    new = text[:at] + sep + "\n".join(lines) + ("\n" if not at else "") + text[at:]
    return new, [f"{rel}: faltaba importar {', '.join(n)} de {o}" for o, n in wanted.items()]


def missing_module(m: re.Match, rel: str, target: str, text: str, exported: dict[str, dict[str, str]],
                   notes: list[str]) -> str:
    """Un import de un archivo que no existe (el `mapa.js` que copiaban de un ejemplo): cada nombre se quita si el
    archivo lo define él mismo o no lo usa, o se importa del único módulo que lo exporta. Si alguno no tiene arreglo
    claro, no se toca (lo ve el depurador)."""
    indent, names, quote, _ = m.groups()
    rest = text.replace(m.group(0), "", 1)
    local = {g for x in DECL.finditer(rest) for g in x.groups() if g}
    dropped, moved = [], {}
    for s in (x.strip() for x in names.split(",") if x.strip()):
        name, alias = s.split(" as ")[0].strip(), s.split(" as ")[-1].strip()
        if alias in local or not re.search(rf"(?<![\w$.]){re.escape(alias)}(?![\w$])", rest):
            dropped.append(alias)
            continue
        owners = [t for t, ex in exported.items() if name in ex and t != rel]
        if len(owners) != 1:
            return m.group(0)
        moved.setdefault(owners[0], []).append(s)
    lines = [f"{indent}import {{ {', '.join(ss)} }} from {quote}{rel_import(rel, owner)}{quote};"
             for owner, ss in moved.items()]
    notes.append(f"{rel}: fuera el import de {target}, que no existe"
                 + (f" ({', '.join(dropped)}: no se usan o ya están en el archivo)" if dropped else "")
                 + (f"; {', '.join(o for o in moved)} exporta el resto" if moved else ""))
    return "\n".join(lines)


def fix_duplicate_functions(text: str) -> tuple[str, list[str]]:
    """Una función declarada dos veces (`Identifier 'formatear' has already been declared`): se queda la exportada
    o, si ninguna lo está, la última, y se quitan las demás enteras (contando llaves)."""
    found: dict[str, list[re.Match]] = {}
    for m in FUNC_DECL.finditer(text):
        found.setdefault(m.group(2), []).append(m)
    cuts, removed = [], []
    for name, ms in found.items():
        if len(ms) < 2:
            continue
        keep = next((x for x in ms if x.group(1)), ms[-1])
        for x in ms:
            if x is keep:
                continue
            end = _block_end(text, text.index("{", x.end()))
            if end is None:
                return text, []
            cuts.append((x.start(), end))
            removed.append(name)
    for a, b in sorted(cuts, reverse=True):
        text = text[:a] + text[b:].lstrip("\n")
    return text, removed


def fix_import_clash(root: Path, rel: str, text: str, exported: dict[str, dict[str, str]]) -> tuple[str, list[str]]:
    """Un nombre importado Y declarado como función en el mismo archivo (`Identifier 'crearReloj' has already been
    declared`): si el módulo importado lo exporta, se quita la función local (manda la del módulo); si no, se quita
    el nombre del import. Variables y clases repetidas no se tocan: las ve el depurador."""
    funcs = {m.group(2): m for m in FUNC_DECL.finditer(text) if not m.group(1)}
    if not funcs:
        return text, []
    edits: list[tuple[int, int, str]] = []  # (desde, hasta, texto nuevo) sobre `text`
    notes: list[str] = []
    for m in IMPORT_NAMED.finditer(text):
        indent, names, quote, spec = m.groups()
        try:
            target = (root / rel).parent.joinpath(spec).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        have = exported.get(target)
        if have is None:
            continue  # el módulo no existe: lo trata `missing_module`
        keep, changed = [], False
        for s in (x.strip() for x in names.split(",") if x.strip()):
            decl = funcs.get(s.split(" as ")[-1].strip())
            if decl is None:
                keep.append(s)
            elif s.split(" as ")[0].strip() in have:
                end = _block_end(text, text.index("{", decl.end()))
                if end is None:
                    keep.append(s)
                    continue
                edits.append((decl.start(), end, ""))
                keep.append(s)
                notes.append(f"{rel}: {decl.group(2)} estaba importada de {spec} y declarada aquí: queda la del módulo")
            else:
                changed = True
                notes.append(f"{rel}: fuera {decl.group(2)} del import de {spec} (no la exporta y ya está declarada aquí)")
        if changed:
            edits.append((m.start(), m.end(),
                          f"{indent}import {{ {', '.join(keep)} }} from {quote}{spec}{quote};" if keep else ""))
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + (text[b:].lstrip("\n") if not new else text[b:])
    return text, notes


def _close(text: str, start: int) -> int | None:
    """Fin (exclusivo) del paréntesis/llave/corchete que abre en `start`, saltando cadenas."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            i += 1
            while i < n and text[i] != c:
                i += 2 if text[i] == "\\" else 1
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _split_args(text: str) -> list[str]:
    parts, depth, cur, i, n = [], 0, "", 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'`":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            cur += text[i:j + 1]
            i = j + 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += c
        i += 1
    if cur.strip():
        parts.append(cur.strip())
    return parts


EXPECT = re.compile(r"(?<![\w$.])expect\(")
EXPECT_MATCHER = re.compile(r"\s*\.\s*(?:(not)\s*\.\s*)?(\w+)\s*\(")
NODE_TEST_IMPORT = re.compile(r"import[ \t]*\{([^}]*)\}[ \t]*from[ \t]*['\"]node:test['\"][ \t]*;?")


def _assertion(a: str, matcher: str, args: list[str], neg: bool) -> str | None:
    """Un `expect(a).matcher(args)` de Jest como llamada a `assert` de node:test; None si no se sabe traducir."""
    def p(x: str) -> str:
        return x if re.fullmatch(r"[\w$.]+", x) else f"({x})"
    b = args[0] if args else ""
    cmp = {"toBeGreaterThan": (">", "<="), "toBeGreaterThanOrEqual": (">=", "<"),
           "toBeLessThan": ("<", ">="), "toBeLessThanOrEqual": ("<=", ">")}
    if matcher == "toBe":
        return f"assert.{'notStrictEqual' if neg else 'strictEqual'}({a}, {b})"
    if matcher in ("toEqual", "toStrictEqual"):
        return f"assert.{'notDeepStrictEqual' if neg else 'deepStrictEqual'}({a}, {b})"
    if matcher in ("toBeTruthy", "toBeFalsy"):
        return f"assert.ok({'!' if (matcher == 'toBeFalsy') != neg else ''}{p(a)})"
    if matcher in ("toBeNull", "toBeUndefined"):
        return f"assert.{'notStrictEqual' if neg else 'strictEqual'}({a}, {matcher[6:].lower()})"
    if matcher == "toBeDefined":
        return f"assert.{'strictEqual' if neg else 'notStrictEqual'}({a}, undefined)"
    if matcher == "toContain" and b:
        return f"assert.ok({'!' if neg else ''}{p(a)}.includes({b}))"
    if matcher == "toHaveLength" and b:
        return f"assert.{'notStrictEqual' if neg else 'strictEqual'}({p(a)}.length, {b})"
    if matcher in cmp and b:
        return f"assert.ok({p(a)} {cmp[matcher][1 if neg else 0]} {p(b)})"
    if matcher == "toBeCloseTo" and b:
        digits = args[1] if len(args) > 1 else "2"
        return f"assert.ok({'!' if neg else ''}(Math.abs({p(a)} - {p(b)}) < 10 ** -{p(digits)} / 2))"
    if matcher == "toBeInstanceOf" and b:
        return f"assert.ok({'!' if neg else ''}({p(a)} instanceof {p(b)}))"
    if matcher == "toMatch" and b:
        test = f"{b}.test({a})" if b.startswith("/") else f"{p(a)}.includes({b})"
        return f"assert.ok({'!' if neg else ''}{test})"
    if matcher == "toThrow":
        if neg:
            return f"assert.doesNotThrow({a})"
        if not b:
            return f"assert.throws({a})"
        if b[0] in "\"'`":
            return f"assert.throws({a}, (e) => e.message.includes({b}))"
        return f"assert.throws({a}, {b})"
    return None


def fix_jest(text: str) -> tuple[str, list[str]]:
    """Tests estilo Jest (`describe`/`test`/`expect` sin importar): se importan de node:test y los `expect(…).toBe(…)`
    se traducen a `assert`. El 20/10 gpt-oss los escribió así en `w-tareas`, `w-propinas` y `j-tres-en-raya` (la
    guardia tenía razón, pero el modelo no los arreglaba en 4 rondas); es mecánico. Si algún `expect` no se sabe
    traducir se deja tal cual (sí se importan los nombres de node:test)."""
    used = {m.group(1) for m in JEST_CALL.finditer(text)} - imported_names(text)
    if not used:
        return text, []
    notes: list[str] = []
    new = text
    if "expect" in used:
        out, pos, ok = [], 0, True
        while True:
            m = EXPECT.search(new, pos)
            if not m:
                out.append(new[pos:])
                break
            end_a = _close(new, m.end() - 1)
            mm = EXPECT_MATCHER.match(new, end_a) if end_a else None
            end_b = _close(new, mm.end() - 1) if mm else None
            repl = None
            if end_b:
                repl = _assertion(new[m.end():end_a - 1].strip(), mm.group(2), _split_args(new[mm.end():end_b - 1]),
                                  bool(mm.group(1)))
            if repl is None:
                ok = False
                break
            out.append(new[pos:m.start()] + repl)
            pos = end_b
        if ok:
            new = "".join(out)
            notes.append("expect de Jest traducido a assert")
        used.discard("expect")
    head = []
    wanted = sorted(used & {"describe", "test", "it", "beforeEach", "afterEach"})
    if wanted:
        have = NODE_TEST_IMPORT.search(new)
        if have:
            names = sorted({s.strip() for s in have.group(1).split(",") if s.strip()} | set(wanted))
            new = new[:have.start()] + f"import {{ {', '.join(names)} }} from 'node:test';" + new[have.end():]
        else:
            head.append(f"import {{ {', '.join(wanted)} }} from 'node:test';")
        notes.append(f"importado de node:test: {', '.join(wanted)}")
    if re.search(r"(?<![\w$.])assert\.", new) and "assert" not in imported_names(new):
        head.append("import assert from 'node:assert/strict';")
    if head:
        new = "\n".join(head) + "\n" + new
    return new, notes


STRAY_NAME = re.compile(r"^(?:ejemplo|example|sample|demo|prueba)\d*[._-]", re.I)


def fix_stray_tests(root: Path, changed: list[str], task: str) -> list[str]:
    """Tests que el plan dejó donde no van: un `x.test.mjs` suelto en la raíz (el 20/10 en `v-divisas` salieron 4,
    con `./resumen.js` que no existe) pasa a `tests/` (o se borra si ya hay uno con ese nombre), y los inventados que la
    tarea no pide (`tests/ejemplo2.test.mjs`, `tests/README.md` en `j-tres-en-raya`) se quitan."""
    notes: list[str] = []
    if not (root / "tests").is_dir():
        return notes
    try:
        tracked = set(subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, timeout=60)
                      .stdout.decode("utf-8", "replace").split("\n"))
    except (OSError, subprocess.TimeoutExpired):
        return notes
    for rel in changed:
        path, name = root / rel, Path(rel).name
        if not path.is_file() or rel in tracked or name in task:
            continue  # lo que ya estaba en el repo o la tarea nombra no se toca
        if "/" not in rel and ".test." in name and Path(rel).suffix in JS:
            target = root / "tests" / name
            if target.exists():
                path.unlink()
                notes.append(f"{rel}: fuera, ya existe tests/{name}")
            else:
                path.replace(target)
                notes.append(f"{rel}: movido a tests/{name}")
        elif rel.startswith("tests/") and rel.count("/") == 1 and (
                STRAY_NAME.match(name) or Path(rel).suffix.lower() in (".md", ".txt")):
            path.unlink()
            notes.append(f"{rel}: fuera, la tarea no lo pide")
    return notes


def _block_end(text: str, start: int) -> int | None:
    """Fin (exclusivo) del bloque `{…}` que abre en `start`, saltando cadenas y comentarios."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if text.startswith("//", i):
            i = text.find("\n", i)
            i = n if i < 0 else i
            continue
        if text.startswith("/*", i):
            i = text.find("*/", i)
            i = n if i < 0 else i + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


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


def failing_tests(output: str) -> list[str]:
    """Los nombres de los tests que fallan (líneas `✖ …` de node:test, sin el resumen ni repetidos)."""
    names = [m.group(1).strip() for m in re.finditer(r"^\s*✖ (.+?)(?: \([\d.]+m?s\))?\s*$", output, re.M)]
    return list(dict.fromkeys(n for n in names if n and not n.startswith("failing tests")))


TEST_CALL = re.compile(r"\b(test|it)(\s*)\(")
SUITE_CALL = re.compile(r"\b(describe|suite)\s*\(")
PREV_MARK = "## INTENTO ANTERIOR"  # el autopiloto pega así lo que falló la vez anterior
DEBT = "Integrado con deuda"  # primera línea del informe de un parche rescatado (el autopiloto lo apunta así)
MAX_OWN_TESTS = 10      # tests propios que se añaden como mucho a un plan sin tests
MAX_DEBT_SHARE = 0.5    # como mucho la mitad de los tests nuevos del parche pasan a TODO; si no, no se rescata


def tap_failures(out: str, root: Path) -> list[tuple[str, str, int]] | None:
    """(nombre, ruta relativa, línea) de cada test que falla en la salida TAP de `node --test`; un archivo que ni
    carga sale con su propia ruta como nombre y línea 1. None si algo no se entiende (no se rescata a ciegas)."""
    fails, name = [], None
    for line in out.splitlines():
        m = re.match(r"\s*not ok \d+ - (.*)$", line)
        if m:
            name = m.group(1).strip()
            continue
        m = re.match(r"\s*location: '(.+):(\d+):\d+'$", line)
        if m and name is not None:
            path = Path(m.group(1).replace("\\\\", "\\"))
            try:
                rel = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                return None
            fails.append((name, rel, int(m.group(2))))
            name = None
        elif re.match(r"\s*ok \d+ - ", line):
            name = None
    return fails


def in_order(blocks: list) -> list:
    """Los bloques en un orden en que cada `after` apunta a bloques anteriores (estable: a igualdad, como venían).
    Las dependencias de bloques que no están, o que cerrarían un ciclo, se quitan."""
    ids = {str(b.get("id")) for b in blocks}
    for b in blocks:
        b["after"] = [str(a) for a in (b.get("after") or []) if str(a) in ids and str(a) != str(b.get("id"))]
    out, done, pending = [], set(), list(blocks)
    while pending:
        ready = next((b for b in pending if all(a in done for a in b["after"])), None)
        if ready is None:  # ciclo: el primero que quede, sin lo que aún no está hecho
            ready = pending[0]
            ready["after"] = [a for a in ready["after"] if a in done]
        pending.remove(ready)
        out.append(ready)
        done.add(str(ready.get("id")))
    return out


def numbered(text: str) -> str:
    return "\n".join(f"{i:4} | {line}" for i, line in enumerate(text.splitlines(), 1))


# --- la especificación troceada por archivo (sin modelo)
def spec_items(text: str) -> list[dict]:
    """Los párrafos de un contrato con su sección y los archivos de los que hablan: «- src/mapa.js exporta …» es de
    src/mapa.js; «- Edita src/partida.js y src/paso.js (…)» de los dos; un párrafo sin viñeta es la introducción de
    su sección (p. ej. «Un cuerpo es {x, y, …}»)."""
    items, sec = [], ""
    for part in re.split(r"\n[ \t]*\n", text):
        p = part.strip()
        if p.startswith("#"):
            first, _, p = p.partition("\n")
            sec = first.lstrip("#").strip() if re.match(r"#{2,3}\s*\d", first) else ""
            p = p.strip()
        if not p or not sec:
            continue
        if p.startswith("-"):
            head = re.split(r"[(:]", p, maxsplit=1)[0]
            found = re.findall(SPEC_PATH, head)
            owners = found if p[1:].lstrip().startswith("Edita") else found[:1]
            items.append({"sec": sec, "owners": owners, "text": p, "edit": p[1:].lstrip().startswith("Edita")})
        else:
            items.append({"sec": sec, "owners": [], "text": p, "edit": False})
    return items


def spec_excerpt(path: str, current: list[dict], whole: list[dict]) -> tuple[list[str], list[str]]:
    """(lo que el contrato dice de `path`, lo que dice de los módulos que eso nombra). De `path`: su párrafo base
    («exporta …», de todo el contrato) y lo que le pide la parte actual (los «Edita»), con la introducción de esas
    secciones. De los demás: solo sus párrafos base, para importarlos con los nombres exactos."""
    base = [i for i in whole if path in i["owners"] and not i["edit"]]
    now = [i for i in current if path in i["owners"]]
    own = list({id(i): i for i in [*base[:1], *now]}.values())
    if not own:
        return [], []
    secs = {i["sec"] for i in now or own}
    intro = [i["text"] for i in current + whole if not i["owners"] and i["sec"] in secs]
    named = {p for text in [*intro, *(i["text"] for i in own)] for p in re.findall(SPEC_PATH, text) if p != path}
    deps, size = [], 0
    for i in whole:
        if not i["edit"] and set(i["owners"]) & named and i["text"] not in deps and size < MAX_SPEC_DEPS:
            deps.append(i["text"])
            size += len(i["text"])
    return list(dict.fromkeys([*intro, *(i["text"] for i in own)])), deps


class Cerebro(Boss):
    RULE_LIKE = {"ENCARGO.md", "AGENTS.md", "CLAUDE.md", "README.md", "CHANGELOG.md", "package.json"}
    # el 10/10 el Qwen3.5-9B no respetó el formato BUSCAR/REEMPLAZAR y un arreglo quirúrgico «no encajó»; a ~45 tok/s
    # reescribir un archivo de 15.000 caracteres sale por ~1-2 min y no falla
    rewrite_under = 15_000
    CODE_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".py", ".html", ".css", ".json")

    def __init__(self, server, check: str = "", say=lambda text: None, deadline: float | None = None,
                 roles: dict | None = None, recetas: str | None = None):
        super().__init__(server, check=check, say=say, deadline=deadline)
        # experimento del 11/10: los planes que Claude mandó a los obreros en el banco (banco/recetas/*.json); con
        # ellos, el plan principal es el de Claude tal cual y el resto (arreglos, rescate, revisión) sigue local
        # (un archivo o una carpeta de ellos: cada receta se elige por el texto del hito)
        src = Path(recetas) if recetas else None
        files = sorted(src.glob("*.json")) if src and src.is_dir() else [src] if src else []
        self.recetas = [r for f in files for r in json.loads(f.read_text(encoding="utf-8"))]
        self.receta: list | None = None
        self._raw = False  # el plan que sale de _plan es la receta: shape_plan no lo toca
        self._rest: list = []  # bloques de la receta que no caben en una llamada
        self.last_diag: str | None = None  # el último archivo que señaló el depurador
        self._main = False  # planificando el plan principal (no una ronda de arreglo)
        self._plan_fails = 0
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

    def plan_and_run(self, task: str, files: list[str], rules: str, label: str, scope: set[str] | None = None,
                     spec: str | None = None) -> dict:
        self._main, self._plan_fails = label == "Plan" and scope is None, 0
        try:
            res = super().plan_and_run(task, files, rules, label, scope, spec)
        finally:
            self._main = False
        rest, self._rest = self._rest, []
        if rest:  # una receta de más de MAX_BLOCKS: lo que no cupo, en una segunda llamada
            ids = {b.get("id") for b in rest}
            for b in rest:
                b["after"] = [a for a in b.get("after") or [] if a in ids]
            self.run_blocks(rest, f"{label} (resto)")
            res["written"] += [b["path"] for b in rest if b.get("kind") in ("edit", "write") and b.get("path")]
        return res

    def _plan(self, task: str, files: list[str], rules: str) -> tuple[list, dict]:
        """El plan del modelo; si en el plan principal falla dos veces (el 10/10 el Qwen3.5-9B entró en bucle dos
        veces y el parche 3 acabó «sin cambios»), un plan de reserva sacado de la tarea: un bloque por archivo."""
        if self._main and self.receta:
            blocks, self.receta = self.receta, None
            blocks, self._rest = blocks[:MAX_BLOCKS], blocks[MAX_BLOCKS:]  # el 11/10 el hito 7 traía 22
            self.notes.append(f"- Plan: la receta de Claude ({len(blocks)} bloques, banco/recetas)")
            self.say(f"Plan: receta de Claude, {len(blocks)} bloques")
            self._raw = True
            return blocks, {"plan": [{k: b.get(k) for k in ("id", "kind", "path", "title", "after")} for b in blocks],
                            "receta": True}
        try:
            blocks, stats = super()._plan(task, files, rules)
            # un plan principal sin ningún bloque que escriba no hace el parche (el 10/10 los hitos 6 y 7 de
            # Supersalto libre fueron 7 bloques «describe los cambios» y acabaron «sin cambios»)
            if self._main and not any(b.get("kind") in ("write", "edit") for b in blocks):
                raise ToolError("el plan no escribe ningún archivo (solo preguntas)")
            return blocks, stats
        except ToolError as e:
            self._plan_fails += 1
            backup = self.skeleton(task) if self._main and self._plan_fails >= 2 else []
            if not backup:
                raise
            self.notes.append(f"- El plan del modelo no salió ({str(e).split(';')[0]}): plan de reserva desde la "
                              "tarea, un bloque por archivo")
            self.say("Plan de reserva: un bloque por archivo que nombra la tarea")
            return backup, {"plan": [{k: b.get(k) for k in ("id", "kind", "path", "after")} for b in backup],
                            "fallback": True}

    def skeleton(self, task: str) -> list[dict]:
        """Un bloque por archivo de código que nombra la tarea (los tests los añade shape_plan) y la línea del
        CHANGELOG si existe. Sin archivos nombrados, nada."""
        paths = [p for p in self.task_paths(task) if not is_test_path(p) and Path(p).suffix in self.CODE_SUFFIXES
                 and Path(p).name not in self.RULE_LIKE]
        blocks = [{"id": f"s{i}", "kind": "edit" if (self.root / p).is_file() else "write", "path": p, "after": [],
                   "title": p, "instructions": (
                       f"Haz en {p} todo lo que la TAREA pide para ESTE archivo: funciones con sus nombres, parámetros "
                       "y comportamiento exactos (lo de los demás archivos lo hacen otros).\n\nTAREA:\n" + task)}
                  for i, p in enumerate(paths, 1)]
        if blocks and (self.root / "CHANGELOG.md").is_file():
            blocks.append({"id": "changelog", "kind": "edit", "path": "CHANGELOG.md", "after": [], "title": "CHANGELOG",
                           "instructions": ("Añade al final una línea para este parche, con el número siguiente y el "
                                            "mismo formato que las anteriores, que resuma en una frase esta tarea: "
                                            + task[:400])})
        return blocks

    def add_template(self, b: dict) -> None:
        """Sin plantilla para los tests: con tests/proyecto.test.mjs de plantilla, el obrero copiaba sus casos y los
        renombraba («el proyecto tiene rect y changelog» → exige un RECT.md que nadie pidió)."""
        if not is_test_path(str(b.get("path") or "")):
            super().add_template(b)

    def own_tests(self, blocks: list) -> list[dict]:
        """Un plan principal que escribe módulos JS sin ningún test (modalidad libre: «con tus propios tests», sin
        rutas) se integraba con `npm test` en verde porque no había nada que probar (10/10, hitos 3, 4, 7 y 8 de
        Supersalto libre). Se añade un tests/<módulo>.test.mjs por módulo nuevo, escrito después del código."""
        if not (self.root / "package.json").is_file():
            return []
        # lo que ya prueba algún test del plan (por la ruta del test o porque sus instrucciones nombran el módulo)
        planned = " ".join(f"{b.get('path')} {b.get('instructions') or ''}" for b in blocks
                           if is_test_path(str(b.get("path") or "")))
        suffix = ".test.mjs" if any((self.root / "tests").glob("*.test.mjs")) else ".test.js"
        extra = []
        for b in blocks:
            path = str(b.get("path") or "")
            if b.get("kind") not in ("edit", "write") or Path(path).suffix not in JS or is_test_path(path):
                continue
            if (self.root / path).is_file():  # los módulos que se amplían (paso.js, partida.js) integran mucho: un
                continue                      # test propio ahí suele salir mal y tumbar el parche; solo los nuevos
            stem = Path(path).name.split(".")[0]
            if re.search(rf"(?<![\w-]){re.escape(stem)}(?![\w-])", planned):
                continue
            test = f"tests/{stem}{suffix}"
            if (self.root / test).exists() or any(t["path"] == test for t in extra):
                continue
            extra.append({"id": f"own-test-{stem}", "kind": "write", "path": test, "after": [b.get("id")],
                          "title": test, "instructions": "", "spec": True, "module": path})
            if len(extra) == MAX_OWN_TESTS:
                break
        if extra:
            self.notes.append("- Módulos nuevos sin test en el plan: se añaden " + ", ".join(t["path"] for t in extra)
                              + " (desde la tarea, después del código)")
        return extra

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
        if getattr(self, "_raw", False):  # la receta de Claude va tal cual, como la mandó él a execute_plan
            self._raw = False
            return blocks
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
        if scope is None and getattr(self, "_main", False):
            out += self.contract_blocks(task, out)
            out += self.own_tests(out)
        for b in out:  # reescribir entero lo que no sea enorme (execute_plan editaría por trozos desde 6.000)
            target = self.root / str(b.get("path") or "")
            if b.get("kind") == "write" and b.get("path") and target.is_file() \
                    and target.stat().st_size < self.rewrite_under:
                b["rewrite"] = True
        api = api_map(self.root)
        tests = [b for b in out if is_test_path(str(b.get("path") or ""))]
        rest = [b for b in out if b not in tests]
        # a cada bloque de código, su especificación: el trozo literal del contrato si la tarea lo cita (como hacía
        # Claude, 10/10: 97,1 %) y, si no, la tarea entera (el 10/10 los 59 bloques del plan del 9B llegaron con una
        # frase, «nombres de meses en castellano», y el obrero inventó formatos que solo los tests conocían)
        head = self.task_head(task)
        for b in rest:
            path = str(b.get("path") or "")
            if b.get("kind") in ("edit", "write") and Path(path).suffix in self.CODE_SUFFIXES \
                    and Path(path).name not in self.RULE_LIKE and "TAREA:" not in str(b.get("instructions") or ""):
                spec = self.spec_for([path], task)
                if spec and (self.root / path).is_file():
                    spec += ("\n\nEl archivo YA EXISTE y hace cosas de partes anteriores del contrato: consérvalas "
                             "todas (mismas funciones, exportaciones y comportamiento) y añade lo de aquí.")
                b["instructions"] = (
                    f"{b.get('instructions') or ''}\n\n{spec}\n\nENCARGO (para situarte; lo de los demás archivos lo "
                    f"hacen otros):\n{head}" if spec else
                    f"{b.get('instructions') or ''}\n\nTAREA (la especificación: cumple lo que pide para {path} con "
                    f"los nombres, formatos, valores y ejemplos exactos; lo de los demás archivos lo hacen otros):\n{task}")
        for b in rest:
            if Path(str(b.get("path") or "")).suffix in JS and api:
                b["instructions"] = (f"{b.get('instructions') or ''}\n\nMÓDULOS QUE YA EXISTEN (importa de aquí, "
                                     f"con estos nombres exactos y del archivo que los exporta):\n{api}")
        for b in tests:
            spec_block = b.pop("spec", False)
            if scope is not None:
                continue
            ids, paths = self.code_for_test(str(b["path"]), rest)
            if spec_block or not b.get("after"):
                b["after"] = [i for i in ids if i != b.get("id")]
            b["files"] = list(dict.fromkeys([*paths, *(b.get("files") or [])]))[:6]
            module = b.pop("module", None)
            excerpt = self.spec_for([module] if module else [p for p in paths if not is_test_path(p)][:3], task)
            # Claude daba los valores esperados ya calculados; el obrero, sin cuentas, se los inventaba
            source = (f"{excerpt}\n\nLa especificación da fórmulas y reglas: esas SÍ dan los valores. Elige entradas "
                      "pequeñas, calcula tú cada valor esperado con la fórmula y escribe la cuenta en un comentario "
                      "junto al assert (p. ej. `// camaraX(300, 1000): 300 - 128 = 172`). Datos pequeños escritos "
                      f"en el test.\n\nENCARGO:\n{head}" if excerpt else f"TAREA:\n{task}")
            what = "la ESPECIFICACIÓN" if excerpt else "la TAREA"
            if str(b.get("id", "")).startswith("own-test-"):
                b["instructions"] = (
                    f"Escribe el archivo de tests {b['path']} para {module}, con node:test y node:assert/strict: de 3 "
                    f"a 8 test() al nivel superior con lo que {what} de abajo pide para ese módulo (sus funciones, "
                    f"firmas y números exactos). Nada que {what} no diga: ni errores, ni archivos, ni mensajes que no "
                    "nombre. El código YA ESTÁ ESCRITO y lo tienes en ARCHIVOS DE CONTEXTO: importa cada función del "
                    f"archivo que la exporta. Los valores esperados salen de {what}, no del código.\n\n{source}"
                    f"{self.skill('tests-de-especificacion')}")
            elif str(b.get("id", "")).startswith("spec-test-"):
                b["instructions"] = (
                    f"Escribe el archivo de tests {b['path']} con los casos que pide para él la TAREA de abajo (solo "
                    "los de este archivo), con node:test y node:assert/strict y un test() por caso, todos al nivel "
                    "superior (nunca un test dentro de otro). El código que se prueba YA ESTÁ ESCRITO y lo tienes en "
                    "ARCHIVOS DE CONTEXTO: importa cada función del archivo que la exporta, con su nombre exacto. "
                    f"Los valores esperados salen de la TAREA, no del código.\n\nTAREA:\n{task}"
                    f"{self.skill('tests-de-especificacion')}")
            else:
                # también a los tests del plan: el 10/10 (Supersalto libre) el obrero escribió los tests sin el
                # contrato (~370 tokens) e inventó casos («existe RECT.md», «columnaDe lanza fuera de límites»); los
                # arreglos rompieron mapa.js para cumplirlos
                b["instructions"] = (f"{b.get('instructions') or ''}\n\nEl código que se prueba YA ESTÁ ESCRITO (en "
                                     f"ARCHIVOS DE CONTEXTO): importa cada función del archivo que la exporta. Prueba "
                                     f"SOLO lo que dice {what} de abajo, con sus nombres, firmas y valores: nada que no "
                                     "pida (ni errores, ni archivos, ni mensajes que no nombre)."
                                     + ("" if "TAREA:" in str(b.get("instructions") or "") else f"\n\n{source}"))
        # el código, luego los tests, y lo que dependa de algo, detrás (el 10/10 el CHANGELOG esperaba a los tests y,
        # con los tests al final, el plan entero falló: «el bloque 7 depende de 5, 6, que no es un bloque anterior»)
        return in_order(rest + tests)

    def gates(self) -> list[str]:
        """Las del jefe 1 y, además, salida del modelo pegada en el código de la app (el 10/10, con Claude dirigiendo,
        src/efectos.js y src/estrella.js llevaban bloques ``` y tests con `import node:test` dentro; los pilló la
        revisión final de Claude, el jefe local los habría integrado)."""
        problems = super().gates()
        for rel in self.changed():
            if Path(rel).suffix not in JS:
                continue
            try:
                text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if is_test_path(rel):
                # 11/10: tests con describe/expect de Jest sin importarlos; el depurador quiso definirlos en src/mapa.js
                used = sorted({m.group(1) for m in JEST_CALL.finditer(text)} - imported_names(text))
                if used:
                    problems.append(f"{rel}: usa {', '.join(used)} sin importarlos (estilo Jest): con node:test es "
                                    "`import { test, describe, it } from 'node:test'` y `import assert from "
                                    "'node:assert/strict'` (assert.equal…, no expect)")
                continue
            if LEFTOVER.search(text):
                problems.append(f"{rel}: lleva salida del modelo pegada (``` o tests con node:test dentro del código "
                                "de la app): debe quedar solo el módulo")
        return problems

    # --- arreglos sin modelo
    def mechanical(self) -> list[str]:
        notes: list[str] = fix_stray_tests(self.root, self.changed(), getattr(self, "task_text", ""))
        changed = [p for p in self.changed() if Path(p).suffix in JS]
        if not changed:
            return notes
        for rel in changed:
            if is_test_path(rel):
                path = self.root / rel
                text = path.read_text(encoding="utf-8", errors="replace")
                new, jest = fix_jest(text)
                if new != text:
                    path.write_text(new, encoding="utf-8", newline="\n")
                    notes += [f"{rel}: {n}" for n in jest]
                continue
            path = self.root / rel
            text = path.read_text(encoding="utf-8", errors="replace")
            new, twice = fix_duplicate_functions(text)
            new, removed = fix_duplicate_exports(new)
            if twice or removed:
                path.write_text(new, encoding="utf-8", newline="\n")
            if twice:
                notes.append(f"{rel}: {', '.join(dict.fromkeys(twice))} estaba declarada dos veces: queda una")
            if removed:
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
            new, missing = fix_missing_imports(self.root, rel, new, exported)
            fixed += missing
            new, clash = fix_import_clash(self.root, rel, new, exported)
            fixed += clash
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

    def diagnose(self, task: str, output: str, tried: list[str], touched: list[str],
                 test_first: bool = False) -> dict | None:
        """`test_first`: arreglar el código ya rompió tests que pasaban o se le culpó dos veces sin éxito; el modelo
        tiene que mirar primero el test (el 11/10 gpt-oss culpó al código 4 rondas de un valor mal contado en el test)."""
        fail = first_failure(output)
        named = self.named_files(fail) or self.named_files(output)
        files = list(dict.fromkeys([*named, *(d for f in named for d in self.related(f))]))
        if not files:
            files = [t for t in touched if (self.root / t).is_file()]
        files = files[:MAX_DIAG_FILES]
        ctx = "\n\n".join(f"--- {f} ---\n{numbered((self.root / f).read_text(encoding='utf-8', errors='replace'))}"
                          [:MAX_DIAG_FILE_CHARS] for f in files)
        others = failing_tests(output)
        user = (f"TAREA:\n{task}\n\nFALLA ASÍ (`{self.check or 'guardias'}`):\n```\n{fail}\n```"
                + (f"\n\nTODOS LOS TESTS QUE FALLAN ({len(others)}):\n" + "\n".join(f"- {t}" for t in others[:25])
                   if len(others) > 1 else "")
                + f"\n\nARCHIVOS:\n{ctx}"
                + ("\n\nYA PROBADO (no funcionó):\n" + "\n".join(f"- {t}" for t in tried) if tried else "")
                + (TEST_FIRST if test_first else ""))

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
        return {"id": bid, "kind": "write" if size < self.rewrite_under else "edit", "rewrite": size < self.rewrite_under,
                "path": path, "after": [],
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
        code = [f for f in pool if not is_test_path(f) and f not in self.RULE_LIKE]
        first = (d or {}).get("archivo") or self.last_diag
        # un archivo ya reescrito en este parche no se reescribe otra vez: el siguiente que falle (el 10/10 el bug de
        # dinero.js no se tocó en 8 rondas porque todas fueron a fechas.js)
        # solo otro archivo que esté fallando (el código que prueban los tests que fallan): el 10/10 15:00, con la
        # reescritura de dinero.js cortada en bucle, la ronda siguiente reescribió fechas.js, que ya pasaba
        failing = list(dict.fromkeys(f for t in self.named_files(output) for f in [t, *self.related(t)]
                                     if not is_test_path(f) and f not in self.RULE_LIKE))
        path = next((f for f in [first, *failing] if f and f not in self.rewritten), None) or first or next(
            iter(code), None) or next(iter(pool), None)
        if not path:
            self.notes.append(f"- Arreglo {n}: no sé qué archivo reescribir")
            return "nada"
        fresh = self.is_new(path)  # nuevo en este parche: desde cero de verdad, sin la versión mala delante
        spec = self.skill("tests-de-especificacion") if is_test_path(path) else ""
        instructions = (f"Reescribe {path} ENTERO y desde cero para que cumpla la TAREA: la versión actual tiene "
                        "fallos que no se han podido arreglar a trozos"
                        + (" (no te la enseño a propósito: no la copies, escríbelo desde la especificación)"
                           if fresh else "")
                        + ". Mismos nombres de funciones y de exportaciones que pide la tarea.\n\n"
                        f"TAREA:\n{task}\n\nASÍ FALLA AHORA:\n```\n{fail}\n```"
                        + ("\n\nYA PROBADO (no funcionó):\n" + "\n".join(f"- {t}" for t in tried) if tried else "")
                        + spec)
        block = self.block_for(path, instructions, self.related(path), f"reescribir{n}")
        block["kind"] = "write"
        block["fresh"] = fresh
        ok = self.run_blocks([block], f"Arreglo {n}")
        if ok:  # si el obrero no pudo (bucle), ese archivo sigue pendiente
            self.rewritten.add(path)
        self.notes.append(f"- Arreglo {n} (reescritura entera{', desde cero' if fresh else ''}): {path}"
                          + ("" if ok else " (no salió)"))
        return f"{path}: reescrito entero"

    def is_new(self, path: str) -> bool:
        """Que el archivo no esté en el último commit (lo ha creado este parche)."""
        try:
            p = subprocess.run(["git", "cat-file", "-e", f"HEAD:{path}"], cwd=self.root, capture_output=True,
                               timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return p.returncode != 0

    def snapshot(self) -> dict[str, bytes]:
        return {p: (self.root / p).read_bytes() for p in self.changed()}

    def restore(self, snap: dict[str, bytes]) -> None:
        """Deja el worktree como en `snap`: lo cambiado después vuelve a su versión de entonces (o a HEAD, o se borra
        si no existía)."""
        for p in self.changed():
            if p not in snap:
                old = self.head_bytes(p)
                if old is None:
                    (self.root / p).unlink(missing_ok=True)
                else:
                    (self.root / p).write_bytes(old)
        for p, data in snap.items():
            (self.root / p).write_bytes(data)

    # --- rescate parcial (contra el efecto dominó)
    def head_text(self, rel: str) -> str | None:
        old = self.head_bytes(rel)
        return old.decode("utf-8", "replace") if old is not None else None

    def salvage(self) -> tuple[list[str], str] | None:
        """Con los tests aún en rojo tras la escalera: en vez de tirar el parche entero, se integra lo que funciona y
        los tests NUEVOS que fallan pasan a `test.todo` (siguen corriendo y se ven como TODO, pero no tumban la
        suite); un archivo de tests nuevo que ni carga se aparca como `.pendiente.mjs`. El 10/10, con `aCentimos`
        mal, se descartaba el parche 1 entero (fechas.js bien incluido) y los 9 siguientes caían por no encontrar
        sus módulos. No se rescata si falla un test que ya estaba (regresión), si la deuda pasa de la mitad de los
        tests nuevos o si, aun así, algo sigue en rojo (guardias incluidas): entonces se descarta como siempre."""
        if not (self.root / "package.json").is_file():
            return None
        try:
            p = subprocess.run(["node", "--test", "--test-reporter=tap"], cwd=self.root, capture_output=True,
                               timeout=300)
        except (OSError, subprocess.TimeoutExpired):
            return None
        fails = tap_failures(p.stdout.decode("utf-8", "replace"), self.root)
        if not fails:
            return None
        texts: dict[str, list[str]] = {}
        todo, parked = [], []
        for name, rel, line in fails:
            if not is_test_path(rel) or not (self.root / rel).is_file():
                return None
            old = self.head_text(rel)
            lines = texts.setdefault(rel, (self.root / rel).read_text(encoding="utf-8").split("\n"))
            if line == 1 and Path(name.replace("\\", "/")).name == Path(rel).name:  # el archivo entero no carga
                if old is not None:
                    return None
                parked.append(rel)
                continue
            src = lines[line - 1] if 0 < line <= len(lines) else ""
            if SUITE_CALL.search(src):  # la suite (describe) falla porque falla un hijo, que sale aparte
                continue
            if old is not None and src.strip() and src.strip() in old:
                return None  # ese test ya estaba antes del parche: es una regresión
            new = TEST_CALL.sub(r"\1.todo\2(", src, count=1)
            if new == src:
                return None  # no es una llamada test(…)/it(…) que se pueda marcar
            lines[line - 1] = new
            todo.append(f"{rel}: {name}")
        own = 0  # tests nuevos del parche (los de archivos nuevos y las líneas que no estaban)
        for rel in {t for t in self.changed() if is_test_path(t)}:
            old = self.head_text(rel) or ""
            own += sum(1 for ln in (self.root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
                       if TEST_CALL.search(ln) and ln.strip() not in old)
        debt = len(todo) + sum(len(TEST_CALL.findall((self.root / r).read_text(encoding="utf-8"))) for r in parked)
        if not own or debt > MAX_DEBT_SHARE * own:
            self.notes.append(f"- Rescate parcial: no ({debt} de {own} tests nuevos fallan, más de la mitad)")
            return None
        before = {rel: (self.root / rel).read_bytes() for rel in [*texts, *parked]}
        for rel, lines in texts.items():
            if rel not in parked:
                (self.root / rel).write_text("\n".join(lines), encoding="utf-8", newline="\n")
        for rel in parked:
            (self.root / rel).rename(self.root / re.sub(r"\.test\.(m?js|cjs)$", r".pendiente.\1", rel))
        out = self.verify()
        if check_failed(out):
            for rel in parked:
                (self.root / re.sub(r"\.test\.(m?js|cjs)$", r".pendiente.\1", rel)).unlink(missing_ok=True)
            for rel, data in before.items():
                (self.root / rel).write_bytes(data)
            self.notes.append("- Rescate parcial: no (con los tests nuevos en TODO sigue fallando algo)")
            return None
        notes = [*(f"{t} → TODO" for t in todo), *(f"{r} no carga → aparcado como .pendiente" for r in parked)]
        return notes, out

    SPEC_MARK = "\n\nLO QUE DICE "

    def with_sections(self, task: str) -> str:
        """Si la tarea cita secciones numeradas de un documento («las secciones 1 a 4 del contrato»), se le pegan
        esas secciones. En Supersalto libre la tarea solo decía eso y la especificación estaba en CONTRATO.md: el
        planificador la leía y la resumía, y los obreros escribían sin ella (archivos y firmas inventados)."""
        if self.SPEC_MARK in task:
            return task
        refs = re.findall(r"secci[oó]n(?:es)?\s+(\d+)(?:\s*(?:a|-|y|hasta)\s*(\d+))?", task, re.I)
        if not refs:
            return task
        wanted = {n for a, b in refs for n in range(int(a), int(b or a) + 1)}
        named = [p for p in self.task_paths(task) if p.endswith(".md") and (self.root / p).is_file()]
        docs = named or [p for p in ("CONTRATO.md", "ENCARGO.md") if (self.root / p).is_file()]
        for doc in docs:
            text = (self.root / doc).read_text(encoding="utf-8", errors="replace")
            parts = re.split(r"(?m)^(?=#{2,3}\s*\d+[.)]?\s)", text)
            got = [p.strip() for p in parts if (m := re.match(r"#{2,3}\s*(\d+)", p)) and int(m.group(1)) in wanted]
            if got:
                return f"{task}{self.SPEC_MARK}{doc} DE ESAS SECCIONES (es la especificación: nombres de archivo, " \
                       f"funciones, firmas y números obligatorios):\n\n" + "\n\n".join(got)
        return task

    def spec_parts(self, task: str) -> tuple[list[dict], list[dict]]:
        """(párrafos de las secciones que trae la tarea, párrafos de todo el contrato). Vacíos si la tarea no cita
        secciones de un documento (modalidad guiada: la especificación ya viene en la tarea)."""
        if self.SPEC_MARK not in task:
            return [], []
        current = spec_items(task.split(self.SPEC_MARK, 1)[1].split("\n", 1)[-1])
        doc = re.match(r"\s*(\S+)", task.split(self.SPEC_MARK, 1)[1])
        whole = current
        if doc and (self.root / doc.group(1)).is_file():
            whole = spec_items((self.root / doc.group(1)).read_text(encoding="utf-8", errors="replace")) or current
        return current, whole

    def spec_for(self, paths: list[str], task: str) -> str:
        """El trozo literal del contrato para escribir (o probar) `paths`, o "" si el contrato no los nombra. Claude
        dirigiendo (10/10, Supersalto libre: 97,1 %) le daba a cada obrero solo lo suyo, ya masticado (270–1.200
        tokens); el jefe local le pasaba «implement moverX per spec» o el contrato entero, y el obrero tenía que
        encontrarlo y deducirlo."""
        current, whole = self.spec_parts(task)
        if not whole:
            return ""
        own, deps = [], []
        for p in paths:
            o, d = spec_excerpt(p, current, whole)
            own += o
            deps += d
        own = list(dict.fromkeys(own))
        deps = [d for d in dict.fromkeys(deps) if d not in own]
        if not own:
            return ""
        names = ", ".join(paths)
        return (f"ESPECIFICACIÓN DE {names} (copiada literal del contrato: cumple cada nombre, firma, fórmula y "
                f"número):\n" + "\n\n".join(own)
                + (("\n\nLO QUE USA DE OTROS MÓDULOS (ya existen o los escribe otro: impórtalo de ahí, con estos "
                    "nombres exactos):\n" + "\n\n".join(deps)) if deps else ""))

    def task_head(self, task: str) -> str:
        return task.split(self.SPEC_MARK, 1)[0].strip()

    def contract_blocks(self, task: str, blocks: list) -> list[dict]:
        """Los archivos de las secciones de este parche que el plan olvidó: el 10/10 el plan del hito 3 no traía
        src/paso.js y el del 5 inventaba módulos (golpearBloque.js). Un bloque por archivo, con su trozo del contrato."""
        current, _ = self.spec_parts(task)
        planned = {str(b.get("path") or "") for b in blocks}
        extra = []
        for p in dict.fromkeys(o for i in current for o in i["owners"]):
            if p in planned or Path(p).suffix not in self.CODE_SUFFIXES or is_test_path(p):
                continue
            target = self.root / p
            big = target.is_file() and target.stat().st_size >= self.rewrite_under
            extra.append({"id": f"contrato-{len(extra) + 1}", "kind": "edit" if big else "write", "path": p,
                          "after": [], "title": p, "instructions": f"Haz en {p} lo que pide el contrato."})
        if extra:
            self.notes.append("- El plan no traía " + ", ".join(b["path"] for b in extra) + ": se añadieron "
                              "(son de las secciones de este parche)")
        return extra

    def missing_modules(self, out: str, done: set[str]) -> list[str]:
        """Módulos del proyecto que algo importa y no existen (rutas relativas), sin los ya intentados."""
        found = []
        for m in MISSING_MODULE.finditer(out or ""):
            try:
                rel = Path(m.group(1)).resolve().relative_to(self.root.resolve()).as_posix()
            except ValueError:
                continue
            if Path(rel).suffix in JS and not (self.root / rel).exists() and rel not in done:
                found.append(rel)
        return list(dict.fromkeys(found))

    def write_missing(self, task: str, out: str, done: set[str]) -> list[str]:
        """Escribe, desde su trozo del contrato, los módulos que se importan y no existen (el 10/10, hito 5:
        partida.js importaba ./nivel.js, que era del hito 1 rechazado, y la escalera gastó 4 rondas en otros
        archivos). Sin trozo del contrato no se inventa nada: sigue la escalera."""
        written = []
        for rel in self.missing_modules(out, done):
            done.add(rel)
            spec = self.spec_for([rel], task)
            if not spec:
                continue
            users = [p for p in self.changed() + js_modules(self.root) if (self.root / p).is_file()
                     and Path(rel).name in (self.root / p).read_text(encoding="utf-8", errors="replace")]
            block = {"id": f"falta-{len(written) + 1}", "kind": "write", "path": rel, "after": [], "title": rel,
                     "instructions": (f"Crea {rel}: lo importan {', '.join(dict.fromkeys(users)) or 'otros módulos'} "
                                      f"y no existe.\n\n{spec}{self.skill('modulos-es')}"),
                     "files": list(dict.fromkeys(users))[:4]}
            if self.run_blocks([block], f"Módulo que falta: {rel}"):
                written.append(rel)
        return written

    # --- todo
    def receta_for(self, task: str) -> list | None:
        """La receta de Claude para este parche: la del texto del hito que aparece en la tarea."""
        flat = " ".join(task.split())
        for r in self.recetas:
            if " ".join(r["texto"].split())[:80] in flat:
                return copy.deepcopy(r["blocks"])
        return None

    def run(self, task: str) -> str:
        self.receta = self.receta_for(task)
        # lo que falló el intento anterior no es especificación: fuera de la tarea (iría a cada encargo) y al
        # depurador como YA PROBADO
        task, mark, prev = task.partition(PREV_MARK)
        task = task.rstrip()
        self.protected = protected_paths(task)
        self.task_text = task
        task = self.with_sections(task)
        self.rewritten = set()
        rules = self.rules()
        api = api_map(self.root)
        if api:
            rules += f"\n\n### Módulos que ya existen (qué exporta cada uno)\n{api}"
        files = [] if self.receta else self.select_files(task, rules)
        res = self.plan_and_run(task, files, rules, "Plan")
        touched = list(dict.fromkeys([*files, *res["written"]]))
        out = self.verify()
        tried: list[str] = ([f"INTENTO ANTERIOR DE ESTE PARCHE: {' '.join(prev.split())[:900]}"] if mark else [])
        rounds = mech = code_blames = idle = 0
        stuck = suspect = False
        tried_missing: set[str] = set()
        while out and check_failed(out) and rounds < len(LADDER) and not self.late():
            if mech < MAX_MECHANICAL:
                fixed = self.mechanical()
                if fixed:
                    mech += 1
                    self.say("Arreglo mecánico: " + "; ".join(fixed)[:300])
                    self.notes.append("- Arreglo mecánico (sin modelo): " + "; ".join(fixed))
                    out = self.verify()
                    continue
            made = self.write_missing(task, out, tried_missing)
            if made:
                self.say("Escritos desde el contrato los módulos que faltaban: " + ", ".join(made))
                self.notes.append("- Módulos que se importaban y no existían, escritos desde el contrato (sin gastar "
                                  "ronda): " + ", ".join(made))
                touched = list(dict.fromkeys([*touched, *made]))
                out = self.verify()
                continue
            rounds += 1
            # con sospecha sobre el test, otro diagnóstico (que mire el test) en vez de reescribir código a ciegas
            step = "quirurgico" if suspect else "reescribir" if stuck else LADDER[rounds - 1]
            self.say(f"Falla: arreglo {rounds} de {len(LADDER)} ({step})")
            before = self.snapshot()
            fails_before = set(failing_tests(out))
            d = self.diagnose(task, out, tried, touched, suspect or code_blames >= 2) if step == "quirurgico" else None
            suspect = False
            if d:
                tried.append(self.surgical(d, rounds))
                touched = list(dict.fromkeys([*touched, d["archivo"]]))
            else:
                tried.append(self.rewrite(task, out, None, tried, touched, rounds))
            # una ronda que deja los archivos igual no cuenta como probada a medias: lo dice y la siguiente reescribe
            after = self.snapshot()
            stuck = after == before
            idle = idle + 1 if stuck else 0
            if stuck:
                tried[-1] += " (NO CAMBIÓ NADA: el archivo quedó idéntico)"
                self.notes.append(f"- Arreglo {rounds}: no cambió nada"
                                  + ("; paro la escalera (dos rondas seguidas sin cambiar nada)" if idle >= MAX_IDLE
                                     else "; el siguiente reescribe"))
            out = self.verify()
            if idle >= MAX_IDLE:  # 18/10: hasta 4 rondas iguales, ~10 min de GPU, y el mismo fallo al final
                break
            # 11/10 (Supersalto, receta de Claude): el código daba la meta en x 848 (bien: columna 53 × 16) y el test
            # esperaba 832; el depurador culpó al código 4 rondas y reescribirlo rompió lo que pasaba. Una ronda que
            # cambia código y hace fallar tests que pasaban se deshace: ese código cumplía, y el sospechoso es el test
            code = [p for p in {*before, *after} if before.get(p) != after.get(p) and not is_test_path(p)]
            broke = sorted(set(failing_tests(out)) - fails_before) if fails_before and code else []
            if broke and check_failed(out):
                self.restore(before)
                suspect = True
                tried[-1] += (" (DESHECHO: rompía tests que pasaban — " + "; ".join(broke[:4]) + ". Ese código "
                              "cumplía: el culpable probablemente es el TEST que falla)")
                self.notes.append(f"- Arreglo {rounds}: deshecho, rompía {len(broke)} test(s) que pasaban "
                                  f"({'; '.join(broke[:3])[:200]}); se sospecha del test")
                out = self.verify()
            elif d and d.get("culpable") != "test" and not is_test_path(d["archivo"]):
                code_blames += 1
        green = not (out and check_failed(out))
        debt: list[str] = []
        if not green and self.changed() and not self.late():
            saved = self.salvage()
            if saved:
                debt, out = saved
                green = True
                self.say(f"Rescate parcial: se integra lo que funciona; {len(debt)} pendientes en TODO")
                self.notes.append(f"- Rescate parcial ({len(debt)} pendientes, siguen en los tests como TODO): "
                                  + "; ".join(debt)[:800])
        verdict = {"ok": True, "problems": [], "summary": ""}
        if green and self.changed() and not self.late():
            verdict = self.advisory_review(task, rules, touched)
        if not self.changed():
            return self.report(verdict, out)
        if "GUARDIAS DEL JEFE" in (out or ""):
            self.rejected.append("guardias: " + "; ".join(ln[2:] for ln in out.splitlines() if ln.startswith("- ")))
        report = self.report(verdict, out)
        if debt and not self.rejected:
            report = f"{DEBT}: {len(debt)} tests nuevos fallan y quedan como TODO.\n\n{report}"
        return report

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
            # lo que la corrección tocó y ya estaba en el último commit vuelve a esa versión: el 10/10 (Supersalto
            # libre, hito 4) se borraban src/render.js y tests/proyecto.test.mjs, que no eran del parche
            for p in self.changed():
                old = before.get(p, self.head_bytes(p))
                if old is None:
                    (self.root / p).unlink(missing_ok=True)
                else:
                    (self.root / p).write_bytes(old)
            self.notes.append("- Corrección de la revisión: rompía los tests y se deshizo")
            return {**verdict, "ok": True}
        self.notes.append("- Corrección de la revisión: hecha y los tests siguen pasando")
        return {**verdict, "ok": True, "problems": []}
