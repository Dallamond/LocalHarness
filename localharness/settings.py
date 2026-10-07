"""Ajustes editables desde la GUI (pestaña Ajustes). Se guardan en la tabla `settings` (clave → JSON).

Solo se guardan las claves cambiadas; lo que falta toma el valor de DEFAULTS. Los efectos son globales del
proceso (un único servidor local): `apply()` los vuelca en context y quien ejecuta lee el resto al usarlos.
"""

import copy
import re
from typing import Any

from localharness import context, hf, llama
from localharness.policy import DEFAULT_CONFIG, DEFAULT_DEPENDENCY, DEFAULT_SENSITIVE, Policy
from localharness.store import Store

DEFAULTS: dict[str, Any] = {
    # Aprobaciones: cuándo algo deja de ser N0/N1 y te llega a ti
    "policy": {
        "max_files": 8,
        "max_lines": 300,
        "max_auto_subtasks": 3,
        "sensitive": list(DEFAULT_SENSITIVE),
        "dependency": list(DEFAULT_DEPENDENCY),
        "config": list(DEFAULT_CONFIG),
    },
    # Planes: con always_review el plan SIEMPRE te espera para aprobarlo, editarlo o rehacer pasos
    "plans": {"always_review": True},
    # Ejecución
    "task_timeout_min": 30,
    "local_base_url": "http://127.0.0.1:8080",
    # Contexto inyectado (M5)
    "context": {"max_memory_chars": context.MAX_MEMORY_CHARS, "max_skill_chars": context.MAX_SKILL_CHARS,
                "skill_dirs": []},
    # Modelos locales (llama.cpp): vacío = variables de entorno o configuración de Arena LLM
    # per_model: {ruta del GGUF: {ctx, ngl, extra, y cualquier clave de llama.OPTION_FLAGS/BOOL_FLAGS}} — lo que
    # falte usa los valores generales de arriba. hardware: VRAM/RAM a mano si la detección falla (vacío = detectar).
    # download_dir: dónde dejar lo que se descarga de Hugging Face (vacío = la primera carpeta de modelos).
    "llama": {"server": "", "model_dirs": [], "port": 8080, "ctx": 16384, "ngl": 99, "per_model": {},
              "hardware": {}, "hf_token": "", "download_dir": ""},
    # Valores que propone el formulario de nuevo agente
    "agent_defaults": {"provider": "claude", "model": "sonnet", "role": "trabajador", "max_turns": 10,
                       "max_budget_usd": 1.0},
    # Catálogo de servidores MCP (formato `mcpServers` de Claude/Cursor): {nombre: {command, args, env} | {url}}.
    # Cada agente Claude elige los suyos (config.mcps); `local` (el modelo local) es de serie y no va aquí.
    "mcp_servers": {},
}
FREE_DICTS = ("mcp_servers",)  # se guardan enteros (las claves son nombres, no campos fijos)
MCP_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def clean_mcp_servers(v: Any) -> dict[str, dict]:
    """Valida el catálogo de servidores MCP: stdio (`command`, `args`, `env`) o remoto (`url`, `type` http|sse)."""
    if not isinstance(v, dict):
        raise ValueError("mcp_servers debe ser un objeto {nombre: servidor}")
    out = {}
    for name, c in v.items():
        if not MCP_NAME.match(str(name)) or name == "local":
            raise ValueError(f"Nombre de servidor MCP no válido: {name!r} (letras, números, - y _; «local» es reservado)")
        if not isinstance(c, dict):
            raise ValueError(f"El servidor {name} debe ser un objeto")
        if c.get("url"):
            kind = c.get("type") if c.get("type") in ("http", "sse") else "http"
            srv = {"type": kind, "url": str(c["url"])}
            if isinstance(c.get("headers"), dict):
                srv["headers"] = {str(a): str(b) for a, b in c["headers"].items()}
        elif c.get("command"):
            srv = {"command": str(c["command"]), "args": [str(a) for a in c.get("args") or []]}
            if isinstance(c.get("env"), dict) and c["env"]:
                srv["env"] = {str(a): str(b) for a, b in c["env"].items()}
        else:
            raise ValueError(f"El servidor {name} necesita `command` (stdio) o `url` (http)")
        if c.get("description"):
            srv["description"] = str(c["description"])[:300]
        out[str(name)] = srv
    return out


def load(store: Store) -> dict[str, Any]:
    """DEFAULTS con lo guardado encima (los diccionarios se mezclan clave a clave)."""
    out = copy.deepcopy(DEFAULTS)
    for k, v in store.get_settings().items():
        if k not in out:
            continue
        mix = isinstance(out[k], dict) and isinstance(v, dict) and k not in FREE_DICTS
        out[k] = {**out[k], **v} if mix else v
    return out


def save(store: Store, changes: dict[str, Any]) -> dict[str, Any]:
    unknown = [k for k in changes if k not in DEFAULTS]
    if unknown:
        raise ValueError(f"Ajustes desconocidos: {', '.join(unknown)}")
    current = load(store)
    for k, v in changes.items():
        if k in FREE_DICTS:
            v = clean_mcp_servers(v)
        elif isinstance(DEFAULTS[k], dict):
            if not isinstance(v, dict):
                raise ValueError(f"{k} debe ser un objeto")
            v = {kk: vv for kk, vv in {**current[k], **v}.items() if kk in DEFAULTS[k]}
        store.set_setting(k, v)
    apply(store)
    return load(store)


def reset(store: Store) -> dict[str, Any]:
    """Valores por defecto en todo salvo el catálogo de servidores MCP (son datos tuyos, no preferencias)."""
    keep = store.get_settings().get("mcp_servers")
    store.clear_settings()
    if keep:
        store.set_setting("mcp_servers", keep)
    apply(store)
    return load(store)


def apply(store: Store) -> None:
    ctx = load(store)["context"]
    context.MAX_MEMORY_CHARS = int(ctx["max_memory_chars"])
    context.MAX_SKILL_CHARS = int(ctx["max_skill_chars"])
    context.EXTRA_SKILL_DIRS = [d for d in ctx["skill_dirs"] if d]
    lm = load(store)["llama"]
    llama.SERVER_OVERRIDE = lm["server"] or None
    llama.DIRS_OVERRIDE = [d for d in lm["model_dirs"] if d]
    hf.TOKEN = (lm.get("hf_token") or "").strip() or None


def policy(store: Store) -> Policy:
    return Policy.from_dict(load(store)["policy"])


def llama_launch(store: Store, model: str, override: dict | None = None) -> dict:
    """ctx, ngl y argumentos extra con los que arrancar un GGUF: su configuración propia (si la tiene) con
    `override` encima (los ajustes elegidos en el diálogo de arranque, solo para esta vez)."""
    import shlex
    lm = load(store)["llama"]
    own = {**((lm.get("per_model") or {}).get(model) or {}), **(override or {})}
    extra = own.get("extra") or ""
    extra = shlex.split(extra, posix=False) if isinstance(extra, str) else list(extra)
    return {"ctx": int(own.get("ctx") or lm["ctx"]),
            "ngl": int(own["ngl"]) if own.get("ngl") not in (None, "") else int(lm["ngl"]),
            "extra": [*llama.option_args(own), *extra], "options": own}


def task_timeout_s(store: Store) -> float:
    return float(load(store)["task_timeout_min"]) * 60
