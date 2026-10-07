"""Biblioteca del Catálogo: skills y servidores MCP preparados, plantillas de agente e importar skills de GitHub.

- `biblioteca/skills/<nombre>/SKILL.md`: skills listas para instalar (frontmatter con `category`). Instalar = copiar
  a `data/skills` (como una importada), así se pueden borrar y no se cargan solas en todos los agentes.
- `biblioteca/mcp.json`: servidores MCP probados con su configuración; `{clave}` se rellena con `params` al añadirlo.
- `biblioteca/agentes.json`: plantillas por rol del asistente de agentes (Catálogo → Nuevo agente).
- `github_skills(url)`: busca los SKILL.md de un repo (o carpeta, o archivo) de GitHub para previsualizarlos e
  importarlos. Solo se importa el SKILL.md (los scripts que traiga al lado no se usan: el agente recibe el texto).
"""

import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from localharness.context import _FRONT, load_skills

LIBRARY = Path(__file__).resolve().parent.parent / "biblioteca"
MAX_GITHUB_SKILLS = 80
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _front(text: str) -> tuple[dict[str, str], str]:
    m = _FRONT.match(text.lstrip("﻿"))
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, text[m.end():]


# --- skills preparadas
def skill_library() -> list[dict]:
    installed = load_skills()
    out = []
    for f in sorted((LIBRARY / "skills").glob("*/SKILL.md")):
        text = f.read_text(encoding="utf-8")
        meta, body = _front(text)
        name = meta.get("name") or f.parent.name
        out.append({"name": name, "description": meta.get("description", ""), "category": meta.get("category") or "Otras",
                    "tags": meta.get("tags", ""), "content": text, "chars": len(body.strip()),
                    "installed": name in installed})
    return out


def library_skill(name: str) -> str:
    for s in skill_library():
        if s["name"] == name:
            return s["content"]
    raise LookupError(f"La biblioteca no tiene la skill {name!r}")


# --- servidores MCP preparados
def _load(name: str, key: str) -> list[dict]:
    try:
        return json.loads((LIBRARY / name).read_text(encoding="utf-8"))[key]
    except (OSError, ValueError, KeyError):
        return []


def mcp_library(configured: dict[str, dict] | None = None) -> list[dict]:
    """Servidores preparados + si el programa que necesitan está en el PC y si ya están añadidos."""
    configured = configured or {}
    out = []
    for e in _load("mcp.json", "servers"):
        same = [n for n, c in configured.items() if n == e["id"] or _same_server(c, e["config"])]
        out.append({**e, "available": not e.get("needs") or bool(shutil.which(e["needs"])), "added_as": same})
    return out


def _same_server(a: dict, b: dict) -> bool:
    if b.get("url"):
        return a.get("url", "").split("?")[0] == b["url"].split("?")[0]
    key = lambda c: [x for x in [c.get("command"), *(c.get("args") or [])] if "{" not in str(x)][:3]  # noqa: E731
    return bool(a.get("command")) and key(a) == key(b)


def fill_mcp(entry_id: str, values: dict[str, str]) -> dict:
    """Configuración lista para `mcp_servers` con los `params` rellenados (error si falta alguno)."""
    e = next((x for x in _load("mcp.json", "servers") if x["id"] == entry_id), None)
    if not e:
        raise LookupError(f"La biblioteca no tiene el servidor {entry_id!r}")
    missing = [p["label"] for p in e.get("params", []) if not str(values.get(p["key"]) or "").strip()]
    if missing:
        raise ValueError("Falta: " + ", ".join(missing))

    def sub(v):
        if isinstance(v, str):
            return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))).strip(), v)
        if isinstance(v, list):
            return [sub(x) for x in v]
        if isinstance(v, dict):
            return {k: sub(x) for k, x in v.items()}
        return v
    return {**sub(e["config"]), "description": e["description"]}


def templates() -> list[dict]:
    return _load("agentes.json", "templates")


# --- skills de GitHub
_GH = re.compile(r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/(tree|blob)/([^/]+)(?:/(.*))?)?/?$")
_RAW = re.compile(r"^(?:https?://)?raw\.githubusercontent\.com/([\w.-]+)/([\w.-]+)/([^/]+)/(.+)$")
_SHORT = re.compile(r"^([\w.-]+)/([\w.-]+)$")


def parse_github(url: str) -> dict:
    """owner/repo, https://github.com/o/r[/tree|blob/ref/ruta] o raw.githubusercontent.com/o/r/ref/ruta."""
    u = url.strip()
    if m := _RAW.match(u):
        return {"owner": m[1], "repo": m[2], "ref": m[3], "path": m[4], "file": True}
    if m := _GH.match(u):
        return {"owner": m[1], "repo": m[2], "ref": m[4], "path": (m[5] or "").strip("/"), "file": m[3] == "blob"}
    if m := _SHORT.match(u):
        return {"owner": m[1], "repo": m[2], "ref": None, "path": "", "file": False}
    raise ValueError("No es una dirección de GitHub: usa usuario/repo o https://github.com/usuario/repo[/tree/rama/carpeta]")


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "LocalHarness", "Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(2_000_000)


def _raw(o: str, r: str, ref: str, path: str) -> str:
    return _get(f"https://raw.githubusercontent.com/{o}/{r}/{urllib.parse.quote(ref)}/{urllib.parse.quote(path)}") \
        .decode("utf-8", "replace")


def github_skills(url: str) -> dict:
    """Los SKILL.md que hay en esa dirección, con su contenido para previsualizar (no instala nada)."""
    g = parse_github(url)
    o, r = g["owner"], g["repo"]
    if g["file"] and g["path"].lower().endswith(".md"):
        paths, ref = [g["path"]], g["ref"]
    else:
        ref = g["ref"] or json.loads(_get(f"https://api.github.com/repos/{o}/{r}")).get("default_branch") or "main"
        tree = json.loads(_get(f"https://api.github.com/repos/{o}/{r}/git/trees/{urllib.parse.quote(ref)}?recursive=1"))
        prefix = g["path"] + "/" if g["path"] else ""
        paths = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"
                 and t["path"].rsplit("/", 1)[-1] == "SKILL.md" and t["path"].startswith(prefix)]
        if not paths:
            raise LookupError(f"No hay ningún SKILL.md en {o}/{r}{'/' + g['path'] if g['path'] else ''}")
    paths = sorted(paths)[:MAX_GITHUB_SKILLS]
    with ThreadPoolExecutor(8) as pool:
        texts = list(pool.map(lambda p: _raw(o, r, ref, p), paths))
    installed = load_skills()
    found = []
    for p, text in zip(paths, texts):
        meta, body = _front(text)
        if not meta.get("name"):
            continue  # sin frontmatter con name no se puede importar
        found.append({"name": meta["name"], "description": meta.get("description", ""),
                      "category": meta.get("category") or r,
                      "path": p, "content": text, "chars": len(body.strip()), "installed": meta["name"] in installed,
                      "url": f"https://github.com/{o}/{r}/blob/{ref}/{p}"})
    return {"source": f"{o}/{r}", "ref": ref, "skills": found}


def with_source(text: str, source: str, category: str | None = None) -> str:
    """Añade `source:` (y `category:` si no tiene) al frontmatter de un SKILL.md importado."""
    m = _FRONT.match(text.lstrip("﻿"))
    if not m:
        return text
    head = m.group(1)
    extra = [f"source: {source}"] if "\nsource:" not in "\n" + head else []
    if category and "\ncategory:" not in "\n" + head:
        extra.append(f"category: {category}")
    if not extra:
        return text
    t = text.lstrip("﻿")
    return t[:m.end(1)] + "\n" + "\n".join(extra) + t[m.end(1):]
