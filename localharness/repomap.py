"""Mapa del repositorio: cada archivo con su esquema, sin modelo y sin gastar cuota.

El 08/10 Claude hizo 237 Read en 27 parches, casi todos para saber qué había en cada archivo antes de planificar.
El mapa se lo da en una llamada: funciones y clases de Python (`ast`), selectores de CSS, títulos e ids de HTML y
funciones/exports de JS, con el tamaño de cada archivo. Se guarda en caché por huella (tamaño + fecha) del archivo.
"""

import ast
import re
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".mypy_cache", ".pytest_cache",
             ".ruff_cache", "coverage"}
TEXT_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".html", ".htm", ".css", ".md", ".json", ".toml",
            ".yml", ".yaml", ".txt", ".sh", ".bat", ".ps1"}
MAX_ITEMS = 25  # elementos por archivo
MAX_CHARS = 30_000  # el mapa entero
SERIES_MIN = 4  # desde cuántos archivos con el mismo nombre salvo el número se resumen en una línea
_cache: dict[str, tuple[tuple, str]] = {}

_CSS_SEL = re.compile(r"(?m)^\s*([^@{}\n/][^{}\n]*?)\s*\{")
_CSS_AT = re.compile(r"(?m)^\s*(@(?:media|supports|keyframes|font-face|import)[^{;\n]*)")
_CSS_VAR = re.compile(r"(--[\w-]+)\s*:")
_HTML_HEAD = re.compile(r"<(h[1-3])[^>]*>(.*?)</\1>", re.S | re.I)
_HTML_ID = re.compile(r"""\bid=["']([^"']+)["']""", re.I)
_HTML_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_HTML_LINK = re.compile(r"""<(?:script|link)[^>]+(?:src|href)=["']([^"']+\.(?:js|mjs|css))["']""", re.I)
_JS_DEF = re.compile(r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+(\w+)|class\s+(\w+)|"
                     r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>)")
_JS_TEST = re.compile(r"""(?m)^\s*(?:test|it|describe)\(\s*(['"`])(.+?)\1""")
_MD_HEAD = re.compile(r"(?m)^(#{1,3})\s+(.+)$")
_TAGS = re.compile(r"<[^>]+>")


def repo_map(root: Path, paths: list[str] | None = None) -> str:
    root = Path(root).resolve()
    files = []
    for rel in paths or ["."]:
        base = (root / rel).resolve()
        if not base.is_relative_to(root) or not base.exists():
            continue
        if base.is_file():
            files.append(base)
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(root).parts) and p.suffix.lower() in TEXT_EXT:
                files.append(p)
    out, used = [], 0
    files = list(dict.fromkeys(files))
    # archivos en serie (blog/parche-001.html … 027): el primero entero y el resto en una línea
    series: dict[tuple, list[Path]] = {}
    for p in files:
        series.setdefault((p.parent, re.sub(r"\d+", "#", p.name)), []).append(p)
    shown: set[Path] = set()
    for p in files:
        if p in shown:
            continue
        group = series[(p.parent, re.sub(r"\d+", "#", p.name))]
        if len(group) >= SERIES_MIN and "#" in re.sub(r"\d+", "#", p.name):
            shown.update(group)
            names = [g.name for g in group]
            entry = (describe(p, root) + f"\n  (y {len(group) - 1} más con la misma forma: {names[1]} … {names[-1]})")
        else:
            entry = describe(p, root)
        if used + len(entry) > MAX_CHARS:
            out.append(f"[… {len(files) - len(out)} archivos más: pide `paths` concretos]")
            break
        out.append(entry)
        used += len(entry)
    return "\n".join(out) or "(no hay archivos de texto)"


def describe(p: Path, root: Path) -> str:
    st = p.stat()
    key = str(p)
    stamp = (st.st_size, st.st_mtime_ns)
    hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    rel = p.relative_to(root).as_posix()
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"{rel}: (no se pudo leer)"
    lines = text.count("\n") + 1
    items = outline(p.suffix.lower(), text)
    head = f"{rel} ({lines} líneas, {st.st_size // 1024 if st.st_size >= 1024 else st.st_size}"
    head += " KB)" if st.st_size >= 1024 else " B)"
    if len(items) > MAX_ITEMS:
        items = items[:MAX_ITEMS] + [f"… {len(items) - MAX_ITEMS} más"]
    entry = head + ("\n  " + "\n  ".join(items) if items else "")
    _cache[key] = (stamp, entry)
    return entry


def outline(ext: str, text: str) -> list[str]:
    if ext == ".py":
        return _python(text)
    if ext in (".css",):
        return _css(text)
    if ext in (".html", ".htm", ".vue"):
        return _html(text) + (_js(text) if ext == ".vue" else [])
    if ext in (".js", ".mjs", ".cjs", ".ts", ".tsx"):
        return _js(text)
    if ext == ".md":
        return [f"{'#' * len(h)} {t.strip()[:80]}" for h, t in _MD_HEAD.findall(text)]
    return []


def _python(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [f"(error de sintaxis en la línea {e.lineno})"]
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"def {node.name}({_args(node)})  L{node.lineno}")
        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            out.append(f"class {node.name}  L{node.lineno}" + (f": {', '.join(methods[:15])}" if methods else ""))
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id.isupper() for t in node.targets):
            out.append(", ".join(t.id for t in node.targets) + f"  L{node.lineno}")
    return out


def _args(fn) -> str:
    names = [a.arg for a in fn.args.args]
    return ", ".join(names[:6]) + (", …" if len(names) > 6 else "")


def _css(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = [m.strip()[:90] for m in _CSS_AT.findall(text)]
    sels = [" ".join(s.split())[:70] for s in _CSS_SEL.findall(text)]
    out += sels
    names = sorted(set(_CSS_VAR.findall(text)))
    if names:
        out.append("variables: " + ", ".join(names[:20]) + (" …" if len(names) > 20 else ""))
    return out


def _html(text: str) -> list[str]:
    out = []
    title = _HTML_TITLE.search(text)
    if title:
        out.append(f"<title> {' '.join(title.group(1).split())[:80]}")
    out += [f"<{tag.lower()}> {' '.join(_TAGS.sub('', body).split())[:70]}" for tag, body in _HTML_HEAD.findall(text)]
    ids = list(dict.fromkeys(_HTML_ID.findall(text)))
    if ids:
        out.append("ids: " + ", ".join(ids[:30]) + (" …" if len(ids) > 30 else ""))
    links = list(dict.fromkeys(_HTML_LINK.findall(text)))
    if links:
        out.append("carga: " + ", ".join(links[:12]))
    return out


def _js(text: str) -> list[str]:
    out = [f"{next(n for n in m if n)}" for m in _JS_DEF.findall(text)]
    out = [f"fn {n}" for n in dict.fromkeys(out)]
    out += [f"test «{t[:70]}»" for _, t in _JS_TEST.findall(text)]
    return out
