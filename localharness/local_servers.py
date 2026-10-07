"""Los servidores locales (llama-server, normalmente uno por GPU): arrancarlos, su estado y la propuesta de uno por
GPU. Lo usan la API (pestaña Modelos locales) y el orquestador (arrancar solos los modelos cuando una tarea los
necesita: `ensure_for_task`)."""

import time
from pathlib import Path

from localharness import llama, settings
from localharness.store import Store


def model_name(path: str | None) -> str | None:
    return Path(path.replace("\\", "/")).name.removesuffix(".gguf") if path else None


def last_of(store: Store, srv: dict) -> dict:
    """Lo último que se arrancó en ese servidor: {model, options}."""
    cfg = settings.load(store)["llama"]
    if srv["id"] == llama.PRINCIPAL:
        return cfg.get("last") or {}
    return (cfg.get("last_by_server") or {}).get(srv["id"]) or {}


def autostart_llama(store: Store, pool: "llama.LlamaPool") -> str | None:
    """Modelos locales → «Arrancar el último modelo al abrir LocalHarness»: lanza en cada servidor local el último
    GGUF que tuvo, con sus ajustes. Devuelve qué pasó (para la GUI) o None si está apagado. Nunca impide arrancar."""
    cfg = settings.load(store)["llama"]
    if not cfg.get("autostart"):
        return None
    said = []
    for srv in settings.local_servers(store):
        main = srv["id"] == llama.PRINCIPAL
        last = last_of(store, srv)
        if not last.get("model"):
            continue
        who = "" if main else f"{srv['name']}: "
        model = Path(last["model"])
        if not model.is_file():
            said.append(f"{who}no encuentro {model}")
            continue
        if llama.health(srv["port"]) != "off":
            said.append(f"{who}ya había un llama-server en el puerto {srv['port']}")
            continue
        try:
            start_on(store, pool, srv, model, last.get("options") or None)
        except (LookupError, RuntimeError, OSError) as e:
            said.append(f"{who}no pude arrancarlo: {e}")
            continue
        said.append(f"{who}arrancando {model.name}")
    return " · ".join(said) or None


def start_on(store: Store, pool: "llama.LlamaPool", srv: dict, model: Path, options: dict | None = None,
             ctx: int | None = None, ngl: int | None = None) -> dict:
    """Arranca `model` en el servidor local `srv` (en su GPU si tiene `device`). Devuelve los ajustes usados."""
    own = settings.llama_launch(store, str(model), options)
    extra = own["extra"]
    if srv.get("device") and not own["options"].get("device"):
        extra = ["-dev", srv["device"], *extra]
    pool.get(srv["id"], srv["port"]).start(model, srv["port"], ctx or own["ctx"],
                                           ngl if ngl is not None else own["ngl"], extra)
    if srv["id"] == llama.PRINCIPAL:  # los agentes locales sin URL propia se conectan al principal
        settings.save(store, {"local_base_url": settings.server_url(srv)})
    return own


def servers_status(store: Store, pool: "llama.LlamaPool") -> list[dict]:
    """Cada servidor local de Ajustes con su estado (off | loading | ready | failed | external)."""
    out = []
    for srv in settings.local_servers(store):
        status = pool.get(srv["id"], srv["port"]).status(srv["port"])
        out.append({**srv, "url": settings.server_url(srv), "status": status,
                    "model_name": model_name(status.get("model")) if status["state"] != "off" else None})
    return out


def suggest_servers(devices: list[dict], current: list[dict]) -> list[dict] | None:
    """Con 2+ GPU y solo el servidor principal: uno por GPU. El principal («fuerte») en la de más memoria y otro
    («rápido») en la siguiente. None si no hay nada que proponer."""
    gpus_ = sorted([d for d in devices if d.get("total_mb")], key=lambda d: -d["total_mb"])
    if len(gpus_) < 2 or len(current) > 1:
        return None
    main = current[0] if current else {"id": llama.PRINCIPAL, "name": "Principal", "port": 8080}
    return [{**main, "name": "Fuerte", "device": gpus_[0]["id"], "role": "fuerte", "thinking": "normal"},
            {"id": "rapido", "name": "Rápido", "port": main["port"] + 1, "device": gpus_[1]["id"], "role": "rapido",
             "thinking": "apagado"}]  # preguntas y resúmenes: sin pensar, al momento



def ensure_for_task(store: Store, wanted: list[str] | None = None, wait_s: float = 180,
                    say=lambda text: None) -> list[str]:
    """Antes de una tarea que usa modelos locales: los servidores apagados (de `wanted`, o todos) arrancan con el
    último modelo que tuvieron y se espera a que estén listos (como mucho `wait_s`). Así una tarea en modo
    coordinador no acaba con Claude trabajando solo (y gastando tu plan) porque se te olvidó arrancarlos.
    Ajuste `llama.autostart_on_task` (por defecto encendido). Devuelve los nombres de los que arrancó."""
    pool = llama.POOL
    if pool is None or not settings.load(store)["llama"].get("autostart_on_task", True):
        return []
    started: list[dict] = []
    for srv in settings.local_servers(store):
        if wanted is not None and srv["id"] not in wanted:
            continue
        last = last_of(store, srv)
        model = Path(last["model"]) if last.get("model") else None
        if not model or not model.is_file() or llama.health(srv["port"]) != "off":
            continue
        try:
            start_on(store, pool, srv, model, last.get("options") or None)
        except (LookupError, RuntimeError, OSError) as e:
            say(f"No pude arrancar {model.name} en {srv['name']}: {e}")
            continue
        say(f"Arrancando {model_name(str(model))} en {srv['name']} (el último que usaste ahí)…")
        started.append(srv)
    deadline = time.monotonic() + wait_s
    pending = list(started)
    while pending and time.monotonic() < deadline:
        time.sleep(1)
        for srv in list(pending):
            state = pool.get(srv["id"], srv["port"]).status(srv["port"])["state"]
            if state in ("ready", "failed", "off"):
                pending.remove(srv)
                if state != "ready":
                    say(f"{srv['name']} no llegó a arrancar ({state}): mira su log en Modelos locales")
    for srv in pending:
        say(f"{srv['name']} sigue cargando: los encargos esperarán a que termine")
    return [s["name"] for s in started]
