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


# --- cambio de modelo en caliente (P2) y GPU unidas o separadas (P3)
_SWAP_LOCKS: dict[str, "threading.Lock"] = {}


def server_busy(server_id: str) -> bool:
    """¿Algún encargo en curso de una tarea está usando ese modelo local AHORA? (lo dice el directo de cada
    delegación: si no ha terminado y se movió hace menos de un minuto)."""
    import json

    from localharness import orchestrator
    for deleg in list(orchestrator.ACTIVE_WORKERS.values()):
        try:
            live = json.loads(Path(deleg["live"]).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        for sid, data in (live.get("servers") or {}).items():
            if sid == server_id and not data.get("done") and time.time() - float(data.get("at") or 0) < 60:
                return True
    return False


def swap(store: Store, pool: "llama.LlamaPool", srv: dict, model: Path, options: dict | None = None,
         wait_s: float = 300, idle_wait_s: float = 600, busy=server_busy, say=lambda text: None) -> dict:
    """Cambia el modelo de un servidor local sin romper lo que esté haciendo: espera a que no tenga encargos, lo
    para, arranca `model` y espera a que conteste. Si el nuevo no arranca, vuelve a poner el anterior. Un candado
    por servidor (dos cambios a la vez sobre el mismo servidor se esperan). Devuelve el estado final."""
    import threading
    lock = _SWAP_LOCKS.setdefault(srv["id"], threading.Lock())
    with lock:
        mgr = pool.get(srv["id"], srv["port"])
        current = mgr.status(srv["port"])
        if current.get("model") and Path(current["model"]) == Path(model) and current["state"] == "ready":
            return current  # ya está
        deadline = time.monotonic() + idle_wait_s
        while busy(srv["id"]) and time.monotonic() < deadline:
            time.sleep(2)
        prev = last_of(store, srv)
        say(f"{srv['name']}: cambiando a {model_name(str(model))}…")
        state = _start_and_wait(store, pool, srv, model, options, wait_s)
        if state["state"] != "ready":
            say(f"{srv['name']}: {model_name(str(model))} no arrancó ({state['state']}); vuelvo al anterior")
            if prev.get("model") and Path(prev["model"]).is_file():
                _start_and_wait(store, pool, srv, Path(prev["model"]), prev.get("options") or None, wait_s)
            raise RuntimeError(f"{model_name(str(model))} no arrancó en {srv['name']}: {state.get('error') or state['state']}")
        remember(store, srv, model, options or {})
        return state


def _start_and_wait(store, pool, srv, model, options, wait_s) -> dict:
    start_on(store, pool, srv, model, options)
    mgr = pool.get(srv["id"], srv["port"])
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        state = mgr.status(srv["port"])
        if state["state"] in ("ready", "failed", "off"):
            return state
        time.sleep(1)
    return mgr.status(srv["port"])


def remember(store: Store, srv: dict, model: Path, options: dict) -> None:
    """Lo último arrancado en cada servidor (para el autoarranque y para volver atrás)."""
    cfg = settings.load(store)["llama"]
    last = {"model": str(model), "options": options}
    if srv["id"] == llama.PRINCIPAL:
        settings.save(store, {"llama": {"last": last}})
    else:
        settings.save(store, {"llama": {"last_by_server": {**(cfg.get("last_by_server") or {}), srv["id"]: last}}})


def split_for(devices: list[dict], margin_mb: int = 700) -> str:
    """-ts según la VRAM LIBRE de cada GPU (menos un margen): «9,2» = 9 partes en la primera y 2 en la segunda."""
    free = [max(0, d.get("free_mb", d.get("total_mb", 0)) - margin_mb) for d in devices]
    total = sum(free) or 1
    parts = [max(1, round(10 * f / total)) for f in free]
    return ",".join(str(p) for p in parts)


def wait_idle(ids: list[str], busy=server_busy, idle_wait_s: float = 600, say=lambda text: None) -> None:
    """Hasta que ninguno de esos servidores tenga encargos en curso (o pase `idle_wait_s`)."""
    deadline = time.monotonic() + idle_wait_s
    told = False
    while any(busy(i) for i in ids) and time.monotonic() < deadline:
        if not told:
            say("Hay encargos en curso: espero a que terminen antes de cambiar")
            told = True
        time.sleep(2)


def set_topology(store: Store, pool: "llama.LlamaPool", mode: str, model: Path | None = None,
                 devices: list[dict] | None = None, say=lambda text: None, busy=server_busy,
                 idle_wait_s: float = 600) -> dict:
    """`unido`: apaga los demás servidores y arranca `model` en el principal repartido entre todas las GPU
    (-dev CUDA0,CUDA1 -sm layer -ts según VRAM libre). `separado`: vuelve a un servidor por GPU con lo último que
    tuvo cada uno. OJO: unido solo compensa para modelos que no caben en una GPU (la 1060 va a la mitad de
    ancho de banda que la 3060); el banco de pruebas (bench) lo mide."""
    if mode not in ("unido", "separado"):
        raise ValueError("topology: unido | separado")
    servers = settings.local_servers(store)
    main = next(s for s in servers if s["id"] == llama.PRINCIPAL)
    if mode == "unido":
        devices = llama.list_devices() if devices is None else devices
        if len(devices) < 2:
            raise RuntimeError("Hace falta más de una GPU para unirlas")
        model = model or Path(last_of(store, main).get("model") or "")
        if not model.is_file():
            raise LookupError("Elige qué modelo cargar con las GPU unidas")
        # el 08/10 «Unir» paró los servidores a mitad de un plan del autopiloto y se perdió el parche
        wait_idle([s["id"] for s in servers], busy, idle_wait_s, say)
        for srv in servers:
            if srv["id"] != llama.PRINCIPAL:
                pool.get(srv["id"], srv["port"]).stop()
        opts = {"device": ",".join(d["id"] for d in devices), "split_mode": "layer",
                "tensor_split": split_for(devices), "main_gpu": 0}
        say(f"Uniendo {opts['device']} (-ts {opts['tensor_split']}) para {model_name(str(model))}")
        settings.save(store, {"llama": {"topology": "unido"}})
        state = swap(store, pool, {**main, "device": ""}, model, opts, busy=lambda _: False)
        return {"topology": "unido", "options": opts, "status": state}
    wait_idle([s["id"] for s in servers], busy, idle_wait_s, say)
    settings.save(store, {"llama": {"topology": "separado"}})
    started = []
    for srv in servers:
        last = last_of(store, srv)
        if not last.get("model") or not Path(last["model"]).is_file():
            continue
        opts = {k: v for k, v in (last.get("options") or {}).items()
                if k not in ("device", "split_mode", "tensor_split", "main_gpu")}
        start_on(store, pool, srv, Path(last["model"]), opts)
        remember(store, srv, Path(last["model"]), opts)
        started.append(srv["name"])
    return {"topology": "separado", "started": started}
