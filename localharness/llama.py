"""Lanzar llama-server con un GGUF que ya tengas descargado (M4).

De dónde salen las rutas (la primera que exista):
- `LOCALHARNESS_LLAMA_SERVER` / `LOCALHARNESS_MODEL_DIRS` (carpetas separadas por `;` en Windows, `:` en Linux)
- la configuración del agente de Arena LLM (`%APPDATA%/ArenaLLM/agent.json`: `model_dirs`, `llama_server`
  o la carpeta de `llama_bench`)
- `llama-server` en el PATH
"""

import json
import os
import shutil
from pathlib import Path


def arena_config() -> dict:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "ArenaLLM" / "agent.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def server_binary() -> str | None:
    env = os.environ.get("LOCALHARNESS_LLAMA_SERVER")
    if env and Path(env).is_file():
        return env
    cfg = arena_config()
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    for key in ("llama_server", "llama_bench"):
        if cfg.get(key):
            p = Path(cfg[key])
            cand = p if key == "llama_server" else p.with_name(exe)
            if cand.is_file():
                return str(cand)
    return shutil.which("llama-server")


def model_dirs() -> list[Path]:
    env = os.environ.get("LOCALHARNESS_MODEL_DIRS")
    dirs = env.split(os.pathsep) if env else arena_config().get("model_dirs") or []
    return [Path(d) for d in dirs if d and Path(d).is_dir()]


def list_models() -> list[Path]:
    """GGUF de modelo (se excluyen los proyectores multimodales mmproj y las partes 2..N)."""
    out = []
    for d in model_dirs():
        for p in sorted(d.rglob("*.gguf")):
            name = p.name.lower()
            if name.startswith("mmproj") or ("-of-" in name and "-00001-of-" not in name):
                continue
            out.append(p)
    return out


def find_model(query: str) -> Path:
    p = Path(query)
    if p.is_file():
        return p
    q = query.lower()
    hits = [m for m in list_models() if q in m.name.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise LookupError(f"Ningún GGUF contiene {query!r}. Mira: python -m localharness llama models")
    exact = [m for m in hits if m.stem.lower() == q]
    if len(exact) == 1:
        return exact[0]
    raise LookupError(f"{query!r} es ambiguo: " + ", ".join(m.name for m in hits))


def serve_command(model: Path, port: int = 8080, ctx: int = 16384, ngl: int = 99,
                  extra: list[str] | None = None) -> list[str]:
    exe = server_binary()
    if not exe:
        raise LookupError("No encuentro llama-server: define LOCALHARNESS_LLAMA_SERVER con su ruta")
    # 127.0.0.1: el servidor no queda expuesto en la red
    return [exe, "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx),
            "-ngl", str(ngl), "--jinja", *(extra or [])]
