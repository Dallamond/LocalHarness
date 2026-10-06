"""Ajustes editables desde la GUI (pestaña Ajustes). Se guardan en la tabla `settings` (clave → JSON).

Solo se guardan las claves cambiadas; lo que falta toma el valor de DEFAULTS. Los efectos son globales del
proceso (un único servidor local): `apply()` los vuelca en context y quien ejecuta lee el resto al usarlos.
"""

import copy
from typing import Any

from localharness import context, llama
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
    # Ejecución
    "task_timeout_min": 30,
    "local_base_url": "http://127.0.0.1:8080",
    # Contexto inyectado (M5)
    "context": {"max_memory_chars": context.MAX_MEMORY_CHARS, "max_skill_chars": context.MAX_SKILL_CHARS,
                "skill_dirs": []},
    # Modelos locales (llama.cpp): vacío = variables de entorno o configuración de Arena LLM
    # per_model: {ruta del GGUF: {ctx, ngl, extra}} — lo que falte usa los valores generales de arriba
    "llama": {"server": "", "model_dirs": [], "port": 8080, "ctx": 16384, "ngl": 99, "per_model": {}},
    # Valores que propone el formulario de nuevo agente
    "agent_defaults": {"provider": "claude", "model": "sonnet", "role": "trabajador", "max_turns": 10,
                       "max_budget_usd": 1.0},
}


def load(store: Store) -> dict[str, Any]:
    """DEFAULTS con lo guardado encima (los diccionarios se mezclan clave a clave)."""
    out = copy.deepcopy(DEFAULTS)
    for k, v in store.get_settings().items():
        if k not in out:
            continue
        out[k] = {**out[k], **v} if isinstance(out[k], dict) and isinstance(v, dict) else v
    return out


def save(store: Store, changes: dict[str, Any]) -> dict[str, Any]:
    unknown = [k for k in changes if k not in DEFAULTS]
    if unknown:
        raise ValueError(f"Ajustes desconocidos: {', '.join(unknown)}")
    current = load(store)
    for k, v in changes.items():
        if isinstance(DEFAULTS[k], dict):
            if not isinstance(v, dict):
                raise ValueError(f"{k} debe ser un objeto")
            v = {kk: vv for kk, vv in {**current[k], **v}.items() if kk in DEFAULTS[k]}
        store.set_setting(k, v)
    apply(store)
    return load(store)


def reset(store: Store) -> dict[str, Any]:
    store.clear_settings()
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


def policy(store: Store) -> Policy:
    return Policy.from_dict(load(store)["policy"])


def llama_launch(store: Store, model: str) -> dict:
    """ctx, ngl y argumentos extra con los que arrancar un GGUF (su configuración propia, si la tiene)."""
    import shlex
    lm = load(store)["llama"]
    own = (lm.get("per_model") or {}).get(model) or {}
    extra = own.get("extra") or ""
    return {"ctx": int(own.get("ctx") or lm["ctx"]),
            "ngl": int(own["ngl"]) if own.get("ngl") not in (None, "") else int(lm["ngl"]),
            "extra": shlex.split(extra, posix=False) if isinstance(extra, str) else list(extra)}


def task_timeout_s(store: Store) -> float:
    return float(load(store)["task_timeout_min"]) * 60
