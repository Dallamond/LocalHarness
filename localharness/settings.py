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
    # servers: los llama-server que puede tener encendidos a la vez (uno por GPU, p. ej.): [{id, name, port, device,
    # role}]. Vacío = solo el «principal» en `port`. role: general (todo) | fuerte (escribir código, agente local) |
    # rapido (preguntas, resúmenes, buscar): la delegación reparte los encargos según el papel. device: -dev de
    # llama.cpp (CUDA0, CUDA1, CUDA0,CUDA1…; vacío = lo decide llama.cpp).
    "llama": {"server": "", "model_dirs": [], "port": 8080, "ctx": 16384, "ngl": 99, "per_model": {},
              "hardware": {}, "hf_token": "", "download_dir": "", "servers": [],
              # autostart: al abrir LocalHarness arranca el último modelo de cada servidor (last = {model, options}
              # del principal; last_by_server = {id: {model, options}} de los demás)
              "autostart": False, "last": {}, "last_by_server": {}},
    # Valores que propone el formulario de nuevo agente
    "agent_defaults": {"provider": "claude", "model": "sonnet", "role": "trabajador", "max_turns": 10,
                       "max_budget_usd": 1.0},
    # Catálogo de servidores MCP (formato `mcpServers` de Claude/Cursor): {nombre: {command, args, env} | {url}}.
    # Cada agente Claude elige los suyos (config.mcps); `local` (el modelo local) es de serie y no va aquí.
    "mcp_servers": {},
    # Agentes: False = cada tarea recibe un agente diseñado a medida (designer.py) y los roles de roles/*.md no se
    # crean solos como agentes; True = lo de antes (un agente fijo por rol, sincronizado al arrancar)
    "roles_autosync": False,
    # Oficina: dónde has colocado cada puesto ({"you" | "a<id>" | "rack": [x, z, giro en cuartos de vuelta]})
    "office_layout": {},
}
FREE_DICTS = ("mcp_servers", "office_layout")  # se guardan enteros (las claves son nombres, no campos fijos)


def clean_office_layout(v: Any) -> dict[str, list[float]]:
    if not isinstance(v, dict):
        raise ValueError("office_layout debe ser un objeto {puesto: [x, z, giro]}")
    out = {}
    for k, p in v.items():
        if not re.match(r"^(you|rack|[aw]\d{1,9})$", str(k)) or not isinstance(p, list) or len(p) != 3 \
                or not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in p):
            raise ValueError(f"Posición no válida para {k!r}")
        out[k] = [max(-20.0, min(20.0, float(p[0]))), max(-20.0, min(20.0, float(p[1]))), int(p[2]) % 4]
    return out
SERVER_ROLES = ("general", "fuerte", "rapido")
SERVER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")
DEVICE = re.compile(r"^([A-Za-z]+\d+)(,[A-Za-z]+\d+)*$")


def clean_servers(v: Any, default_port: int) -> list[dict]:
    """Valida `llama.servers`. Siempre queda el «principal» (el primero); ids y puertos únicos."""
    if not isinstance(v, list):
        raise ValueError("llama.servers debe ser una lista")
    out: list[dict] = []
    for srv in v:
        if not isinstance(srv, dict):
            raise ValueError("Cada servidor local debe ser un objeto")
        sid = str(srv.get("id") or "").strip().lower()
        if not SERVER_ID.match(sid):
            raise ValueError(f"Identificador de servidor no válido: {sid!r} (minúsculas, números, - y _)")
        try:
            port = int(srv.get("port") or 0)
        except (TypeError, ValueError):
            port = 0
        if not 1024 <= port <= 65535:
            raise ValueError(f"Puerto no válido para {sid}: {srv.get('port')!r}")
        device = str(srv.get("device") or "").replace(" ", "")
        if device and not DEVICE.match(device):
            raise ValueError(f"Dispositivo no válido para {sid}: {device!r} (p. ej. CUDA0 o CUDA0,CUDA1)")
        role = srv.get("role") if srv.get("role") in SERVER_ROLES else "general"
        out.append({"id": sid, "name": str(srv.get("name") or sid)[:40], "port": port, "device": device,
                    "role": role})
    ids = [s["id"] for s in out]
    ports = [s["port"] for s in out]
    if len(set(ids)) != len(ids):
        raise ValueError("Hay dos servidores locales con el mismo identificador")
    if len(set(ports)) != len(ports):
        raise ValueError("Hay dos servidores locales en el mismo puerto")
    if len(out) > 4:
        raise ValueError("Como mucho 4 servidores locales")
    if llama.PRINCIPAL not in ids:
        if default_port in ports:
            raise ValueError(f"El puerto {default_port} es del servidor principal")
        out.insert(0, {"id": llama.PRINCIPAL, "name": "Principal", "port": default_port, "device": "",
                       "role": "general"})
    else:  # el principal siempre el primero
        out.sort(key=lambda s: s["id"] != llama.PRINCIPAL)
    return out


def local_servers(store: Store) -> list[dict]:
    """Los servidores locales configurados (como mínimo el principal, en `llama.port`)."""
    lm = load(store)["llama"]
    return clean_servers(lm.get("servers") or [], int(lm["port"]))


def server_url(srv: dict) -> str:
    return f"http://127.0.0.1:{srv['port']}"


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
            v = clean_office_layout(v) if k == "office_layout" else clean_mcp_servers(v)
        elif isinstance(DEFAULTS[k], dict):
            if not isinstance(v, dict):
                raise ValueError(f"{k} debe ser un objeto")
            v = {kk: vv for kk, vv in {**current[k], **v}.items() if kk in DEFAULTS[k]}
            if k == "llama":
                v = _sync_principal(v, changes[k])
        store.set_setting(k, v)
    apply(store)
    return load(store)


def _sync_principal(lm: dict, changed: dict) -> dict:
    """`llama.port` y el puerto del servidor «principal» son lo mismo: se cambie lo que se cambie, quedan iguales."""
    if not lm.get("servers"):
        return lm
    if "servers" in changed:
        servers = clean_servers(lm["servers"], int(lm["port"]))
        return {**lm, "servers": servers, "port": servers[0]["port"]}
    servers = [{**s, "port": int(lm["port"])} if s.get("id") == llama.PRINCIPAL else s for s in lm["servers"]]
    return {**lm, "servers": clean_servers(servers, int(lm["port"]))}


def reset(store: Store) -> dict[str, Any]:
    """Valores por defecto en todo salvo el catálogo de servidores MCP y la oficina (son datos tuyos, no preferencias)."""
    saved = store.get_settings()
    store.clear_settings()
    for k in FREE_DICTS:
        if saved.get(k):
            store.set_setting(k, saved[k])
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
