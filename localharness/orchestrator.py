"""Ciclo de una tarea: worktree -> agente -> checkpoint -> diff listo para revisar. Sin push automático."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from localharness import llama, local_servers, mcp_local, settings, workspace
from localharness.adapters import get_adapter
from localharness.adapters.base import THINKING_LEVELS, RunSpec
from localharness.adapters.claude import READ_TOOLS, SUBAGENT_TOOL, WEB_TOOLS, thinking_env
from localharness.adapters.local import config_kwargs
from localharness.context import build_prompt, load_memory, load_skills
from localharness.events import Event
from localharness.runner import run
from localharness.store import Store

EPHEMERAL = ("speed", "thinking_live", "worker_live")  # en vivo para la GUI, no se guardan (llegan cada ~1,5 s)

DELEGATE_TOOLS = {"local_ask": "mcp__local__local_ask", "local_write_file": "mcp__local__local_write_file",
                  "local_execute_plan": "mcp__local__local_execute_plan",
                  "local_agent": "mcp__local__local_agent", "run_checks": "mcp__local__run_checks",
                  "local_research": "mcp__local__local_research", "local_prepare": "mcp__local__local_prepare",
                  "local_edit_file": "mcp__local__local_edit_file", "local_map": "mcp__local__local_map",
                  "local_plan": "mcp__local__local_plan", "local_read_documents": "mcp__local__local_read_documents",
                  "local_look": "mcp__local__local_look", "local_search": "mcp__local__local_search",
                  "local_models": "mcp__local__local_models", "local_use": "mcp__local__local_use"}
PLAN_TOOL = "local_execute_plan"
PREPARE_TOOL = "local_prepare"
# no cuentan como encargos en el resumen (no generan nada)
NOT_ENCARGOS = (PLAN_TOOL, PREPARE_TOOL, "local_map", "local_models", "local_use", "local_search")
# trabajador local de las tareas en marcha: task_id -> datos de su delegación (la GUI cambia sus skills al vuelo)
ACTIVE_WORKERS: dict[int, dict] = {}
API_URL = "http://127.0.0.1:8095"  # la API de esta sesión (cli start/serve lo ponen con su puerto)

# Las guías van en el prompt de SISTEMA (--append-system-prompt), no en el de la tarea: Claude las trata como reglas
# de trabajo y se repiten en cada vuelta de la conversación (con --resume también).
COORDINATOR_GUIDE = """
# Cómo trabajas: MODO COORDINADOR — eres el jefe de un modelo local
El trabajo lo hace un modelo local que corre gratis en el PC del usuario; tu cuota es cara. Tú entiendes, partes,
encargas, revisas y presentas. No tienes Edit, Write ni Bash: no puedes escribir archivos ni ejecutar nada; todo lo
que haya que generar (código, tests, documentación, correcciones) lo genera el modelo local. Sigue este ciclo:
0. EQUIPA al trabajador local ANTES de encargar: `local_prepare` con las skills (de su lista) y herramientas que
   necesita para esta tarea, y el motivo. Pocas y relevantes: es un modelo pequeño y cada skill ocupa contexto.
1. ENTIENDE la petición entera y sepárala en bloques. Explora lo justo: `local_map` te da en una llamada cada
   archivo con sus funciones, selectores, ids y títulos (gratis): empieza por ahí en vez de Glob y Read. Para
   entender código o buscar fallos NO leas tú los archivos: `local_ask` con sus rutas en `files` (puedes pedirle de
   una vez «lista los fallos de estos archivos con archivo, línea y corrección»). Read solo de líneas concretas.
2. PLANIFICA en tu respuesta (bloques numerados: archivo, qué cambia y por qué) ANTES de encargar. El modelo local no
   ve esta conversación: cada encargo lleva instrucciones autocontenidas (qué exactamente, firmas, casos límite,
   estilo, qué archivos leer).
3. ENCARGA:
   - `local_execute_plan` con TODOS los bloques en una llamada y `check` = la orden de tests. Para un archivo que
     YA EXISTE usa `kind: edit` (el modelo devuelve solo los trozos que cambian: mucho más rápido y no pierde
     líneas); `write` solo para archivos nuevos o que cambian enteros. Pon `after` en cada bloque (de qué bloques
     anteriores depende; [] si de ninguno): los independientes se hacen a la vez y el plan tarda mucho menos;
   - si el parche es de plantilla (como otros que ya se hicieron), pide antes el plan a `local_plan` (gratis):
     revisarlo y corregirlo te cuesta mucho menos que escribirlo;
   - un retoque suelto en un archivo existente: `local_edit_file`;
   - `local_agent` casi nunca: solo si hay que explorar algo que no sabes planificar. Se atasca releyendo; NUNCA
     para arreglar un fallo ni para añadir entradas a una lista.
4. REVISA siempre: el informe trae el diff de cada `edit`, así que muchas veces no hace falta Read. Pasa los tests
   con `run_checks` (no gasta cuota). Si algo falla, vuelve a encargar SOLO lo que falló, como `edit` del archivo
   culpable con el error y la corrección exacta (como mucho 2 rondas más). Si hay páginas web, `local_look` las
   mira en escritorio y móvil con un modelo de visión (si no hay uno cargado, `local_use` con «vision»).
5. PRESENTA: el plan, qué hizo el modelo local en cada parte, el resultado de los tests y lo pendiente o dudoso.
   Sé honesto: si algo no quedó bien, dilo.
Investigar en internet: `local_research`. Si el modelo local deja de responder, para y díselo al usuario."""

DELEGATE_GUIDE = """
# Cómo trabajas: delega en el modelo local
Tienes un modelo local que corre gratis en el PC del usuario; tu cuota es cara. Delegar es OBLIGATORIO cuando encaje:
0. Antes del primer encargo, equípalo con `local_prepare` (skills y herramientas que necesita para esta tarea).
1. NO leas archivos tú para entenderlos, resumirlos o buscar fallos: `local_ask` con sus rutas en `files`.
   Haz Read tú solo de las líneas concretas que vayas a editar o verificar.
2. Preguntas, explicaciones, comparar opciones, redactar texto o documentación: `local_ask`.
3. Programación de más de unas pocas líneas: encárgala. `local_edit_file` para cambiar una parte de un archivo que
   ya existe; `local_write_file` para un archivo nuevo bien especificado; `local_execute_plan` para varios archivos
   a la vez (todos los bloques en una llamada, `kind: edit` en los que ya existen y `check` = los tests);
   `local_agent` solo para una tarea que necesite explorar e iterar con los tests.
   Tú revisas el resultado (Read) y corriges con Edit lo pequeño.
4. Comprobar tests sin gastar: `run_checks`. Internet (documentación, errores, versiones): `local_research`.
5. Empieza SIEMPRE por un encargo al modelo local, salvo que la tarea sea de 1–2 líneas.
Tú decides, planificas y verificas: es un modelo pequeño. Si responde que no hay modelo local, hazlo tú y dilo al final."""

READ_GUIDE = """
# Cómo trabajas: delega la lectura en el modelo local
Tienes un modelo local que corre gratis en el PC del usuario; tu cuota es cara. Este agente es de SOLO LECTURA: ni
tú ni el modelo local podéis crear ni modificar archivos, ni ejecutar órdenes (el modelo local solo contesta texto).
Si la petición pide crear o cambiar archivos, NO lo intentes por otros caminos (pedírselo al modelo local, scripts,
PowerShell, git): di en una línea que este agente es de solo lectura y que use uno que pueda escribir; como mucho,
deja el contenido propuesto en tu respuesta.
1. NO leas archivos tú para entenderlos o resumirlos: `local_ask` con sus rutas en `files`; haz Read tú solo de las
   líneas concretas que necesites verificar. El modelo local NO ve el repo por su cuenta ni recuerda encargos
   anteriores: sin `files`, lo que diga del repo es inventado.
2. Explicaciones, comparar opciones, borradores de texto: `local_ask`. Internet: `local_research`.
3. Tests: `run_checks` (no gasta cuota).
Tú decides y verificas: es un modelo pequeño. Si responde que no hay modelo local, hazlo tú y dilo al final."""


MULTI_GUIDE = """
## Varios modelos locales a la vez
Tienes {n} modelos locales, cada uno en su GPU, y trabajan EN PARALELO: {who}. Cada encargo va solo al que encaja
por su papel (el «fuerte» escribe código y hace `local_agent`; el «rápido» contesta preguntas, resume e investiga);
con el argumento `server` puedes elegir otro. OJO: dos llamadas tuyas solo van a la vez si son de solo lectura
(`local_ask`, `local_research`, `run_checks`): pídelas en el MISMO mensaje. Las que escriben (`local_write_file`,
`local_agent`) se hacen una detrás de otra, así que para que los dos modelos ESCRIBAN a la vez usa UNA llamada a
`local_execute_plan` con `after` en cada bloque (y `server` en el bloque si quieres elegir quién lo hace).
"""


def delegate_guide(write: bool, coordinator: bool = False, servers: list[dict] | None = None) -> str:
    guide = READ_GUIDE if not write else COORDINATOR_GUIDE if coordinator else DELEGATE_GUIDE
    if servers and len(servers) > 1:
        who = "; ".join(f"«{s['id']}» ({s['role']}{', ' + s['device'] if s.get('device') else ''})" for s in servers)
        guide += MULTI_GUIDE.format(n=len(servers), who=who)
    return guide


async def execute_task(store: Store, task_id: int, *, binaries: dict[str, str] | None = None,
                       on_event: Callable[[int, Event], None] | None = None,
                       worktree_root: str | None = None, timeout_s: float | None = None,
                       ws: workspace.Workspace | None = None, json_schema: dict | None = None,
                       read_only: bool | None = None, followup: str | None = None) -> dict:
    """Ejecuta una tarea. Con `ws` reutiliza un worktree (subtareas de un plan, en serie sobre la misma rama):
    la base de la tarea es el HEAD actual y su resultado queda en un commit propio (`head_commit`).

    Con `followup` es tu respuesta en la conversación de una tarea ya terminada: sigue en su mismo worktree y
    rama, el diff sigue contando desde la base original y el coste se acumula. Claude reanuda su sesión
    (`--resume`); un proveedor sin sesión (modelo local) recibe la conversación entera en el prompt."""
    task = store.get_task(task_id)
    if not task:
        raise ValueError(f"Tarea {task_id} no existe")
    project = store.get_project(task["project_id"])
    agent = store.get_agent(task["agent_id"]) if task["agent_id"] else None
    if not project or not agent:
        raise ValueError("La tarea necesita proyecto y agente")
    busy = [t for t in store.list_tasks(project["id"], status="running") if t["id"] != task_id]
    if busy and ws is None:  # conflictos de merge entre tareas: por ahora, una tarea por repo a la vez
        raise ValueError(f"El proyecto ya tiene una tarea en curso: #{busy[0]['id']}")
    cfg = json.loads(agent["config"] or "{}")
    # agente local con su servidor apagado: se arranca solo (antes de crear el adaptador, que necesita su clave)
    pre_warn: list[str] = []
    if agent["provider"] in ("local", "local_agent") and not cfg.get("base_url"):
        await asyncio.to_thread(local_servers.ensure_for_task, store, [cfg.get("server") or llama.PRINCIPAL], 180,
                                pre_warn.append)
    # la URL del llama-server del agente manda (o su servidor local, `config.server`); si no, la de Ajustes
    extra = {}
    if agent["provider"] in ("local", "local_agent"):
        url = local_url(store, cfg)
        extra = {**config_kwargs({**cfg, "base_url": url}), "api_key": llama.key_for_url(url)}
    if agent["provider"] == "local_agent":  # el bucle de agente local tiene sus propios ajustes
        extra.update({k: cfg[k] for k in ("tool_mode", "max_tool_chars", "max_context_chars", "web", "commands",
                                          "command_timeout_s") if k in cfg})
    adapter = get_adapter(agent["provider"], binary=(binaries or {}).get(agent["provider"]) or cfg.get("binary"),
                          **extra)

    history = _conversation(store, task) if followup is not None else []
    prev_cost = (task["cost_usd"] or 0) if followup is not None else 0
    if followup is not None and task["worktree"] and Path(task["worktree"]).is_dir():
        ws = workspace.Workspace(Path(project["repo_path"]), Path(task["worktree"]), task["branch"],
                                 task["base_commit"])
        base = task["base_commit"]
    else:
        if ws is None:  # también una respuesta a una tarea cuyo worktree ya no existe: se crea otro
            ws = workspace.create(project["repo_path"], task_id, worktree_root)
        base = ws.head()
    store.update_task(task_id, status="running", branch=ws.branch, worktree=str(ws.path), base_commit=base)

    def sink(ev: Event) -> None:  # el estado se guarda ANTES de avisar: quien escucha lee la tarea ya al día
        if ev.kind not in EPHEMERAL:
            ev.id = store.add_event(task_id, ev.kind, ev.text, ev.data)
        if ev.kind == "session" and ev.data.get("session_id"):
            store.update_task(task_id, session_id=ev.data["session_id"])
        if ev.kind == "usage" and ev.data.get("cost_usd") is not None:
            store.update_task(task_id, cost_usd=round(prev_cost + ev.data["cost_usd"], 6))
        if on_event:
            on_event(task_id, ev)

    # M5: skills del agente + de la tarea, y memoria del proyecto, inyectadas como texto (igual en todo proveedor)
    wanted = list(dict.fromkeys([*(cfg.get("skills") or []), *json.loads(task.get("skills") or "[]")]))
    catalog = load_skills() if wanted else {}
    resume = followup is not None and adapter.is_cli and task.get("session_id")
    if resume:  # la sesión ya tiene la memoria, las skills y lo hablado
        prompt, injected = followup, {"memory": [], "skills": []}
    else:
        request = task["prompt"] if followup is None else transcript(history, followup)
        prompt, injected = build_prompt(request, load_memory(project.get("memory_dir")),
                                        [catalog[n] for n in wanted if n in catalog])
    missing = [n for n in wanted if n not in catalog]
    if cfg.get("instructions") and not resume:  # objetivo 5: instrucciones del rol (roles/*.md)
        prompt += f"\n\n## Tu rol en el equipo\n{cfg['instructions']}"

    ro = bool(cfg.get("read_only")) if read_only is None else read_only
    is_claude = agent["provider"] == "claude"
    # modo coordinador: Claude planifica, encarga y revisa; todo lo que se escribe lo genera el modelo local. Sin
    # llama-server no tendría con qué trabajar: entonces trabaja él solo esta vez (con aviso) en vez de gastar en vano
    coord = is_claude and bool(cfg.get("coordinator")) and not ro
    # modelos locales apagados que esta tarea va a usar: se arrancan solos con el último modelo de cada servidor
    if is_claude and (coord or cfg.get("delegate_local")):
        await asyncio.to_thread(local_servers.ensure_for_task, store, cfg.get("local_servers"), 180,
                                lambda t: sink(Event("warning", text=t)))
    for text in pre_warn:
        sink(Event("warning", text=text))
    if coord and not await asyncio.to_thread(any_llama_up, store, cfg.get("local_servers")):
        coord = False
        sink(Event("warning", text="Modo coordinador sin modelo local arrancado: Claude trabaja solo esta vez "
                                   "(Modelos locales → Arrancar para que encargue el trabajo)"))
    deleg = _mcp_setup(store, ws.path, {**cfg, "delegate_local": True} if coord else cfg, write=not ro,
                       coordinator=coord) if is_claude else None
    if deleg and deleg["missing"]:
        sink(Event("warning", text=f"Servidores MCP no encontrados en el Catálogo: {', '.join(deleg['missing'])}"))
    only = cfg.get("local_servers")  # la Comparativa limita a qué modelos locales puede encargar
    system = (delegate_guide(write=not ro, coordinator=coord,
                             servers=[s for s in settings.local_servers(store) if not only or s["id"] in only])
              if deleg and deleg["delegate"] else None)
    thinking = task.get("thinking") or cfg.get("thinking")
    if not thinking and agent["provider"] in ("local", "local_agent"):  # si no, el de su servidor local
        srv = next((s for s in settings.local_servers(store) if s["id"] == (cfg.get("server") or llama.PRINCIPAL)), None)
        thinking = srv and srv.get("thinking")
    thinking = thinking if thinking in THINKING_LEVELS else None
    if thinking and agent["provider"] == "claude":
        deleg_env = {**(deleg["env"] if deleg else {}), **thinking_env(thinking)}
    else:
        deleg_env = deleg["env"] if deleg else {}
    spec = RunSpec(prompt=prompt, cwd=str(ws.path), model=agent["model"], thinking=thinking,
                   max_turns=cfg.get("max_turns"), max_budget_usd=cfg.get("max_budget_usd"),
                   read_only=ro, allowed_tools=list(READ_TOOLS) if coord else cfg.get("tools"),
                   json_schema=json_schema,
                   extra_tools=([SUBAGENT_TOOL] if cfg.get("subagents") and is_claude else []) +
                               (list(WEB_TOOLS) if cfg.get("web") and is_claude else []),
                   session_id=task["session_id"] if resume else None,
                   mcp_config=deleg["config"] if deleg else None, mcp_tools=deleg["tools"] if deleg else [],
                   env=deleg_env, system_append=system,
                   ask_director=(_director_line(store, task, ws, binaries)
                                 if agent["provider"] == "local_agent" else None))
    if coord:
        sink(Event("progress", text="Modo coordinador: Claude planifica y revisa; el trabajo lo hace el modelo local"))
    if followup is not None:
        sink(Event("user", text=followup))
    sink(Event("status", text="running"))
    if injected["memory"] or injected["skills"]:
        names = [m["file"] for m in injected["memory"]] + [s["name"] for s in injected["skills"]]
        sink(Event("context", text=", ".join(names), data=injected))
    if missing:
        sink(Event("warning", text=f"Skills no encontradas: {', '.join(missing)}"))
    watcher = asyncio.create_task(_watch_delegations(deleg, sink)) if deleg and deleg["delegate"] else None
    if watcher:
        ACTIVE_WORKERS[task_id] = deleg
    try:
        res = await run(adapter, spec, sink, timeout_s=cfg.get("timeout_s") or timeout_s or settings.task_timeout_s(store))
    except asyncio.CancelledError:
        ws.checkpoint(f"localharness (cancelada): {task['title']}")  # lo hecho queda en la rama, por si sirve
        store.update_task(task_id, status="cancelled", finished_at=_now())
        sink(Event("status", text="cancelled"))
        raise
    finally:
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            _flush_delegations(deleg, sink)
        if deleg:
            ACTIVE_WORKERS.pop(task_id, None)
            shutil.rmtree(deleg["dir"], ignore_errors=True)
    ws.checkpoint(f"localharness: {task['title']}")
    head = ws.head()
    changes = ws.changes(base, head)
    # review = esperando tu aprobación; sin cambios en archivos (consultas, planes, revisiones) = done
    status = ("review" if changes else "done") if res["status"] == "done" else res["status"]
    store.update_task(task_id, status=status, final=res["final"], finished_at=_now(), head_commit=head)
    sink(Event("status", text=status))
    return {**res, "status": status, "diff": ws.diff_range(base, head), "changes": changes,
            "stat": git_stat(ws, base, head)}


def _director_line(store: Store, task: dict, ws: workspace.Workspace, binaries: dict[str, str] | None):
    """Para un agente local dentro de un plan: `preguntar_director` reanuda la sesión de Claude del Director
    (ya conoce la petición y el plan) con la pregunta. Solo lectura, pocos turnos y tope de gasto."""
    if not task.get("plan_id"):
        return None
    d = next((t for t in store.plan_tasks(task["plan_id"]) if t["kind"] == "director"), None)
    director = store.get_agent(d["agent_id"]) if d and d["agent_id"] else None
    if not d or not d.get("session_id") or not director or director["provider"] != "claude":
        return None
    dcfg = json.loads(director["config"] or "{}")

    async def ask(question: str) -> tuple[str, float]:
        adapter = get_adapter("claude", binary=(binaries or {}).get("claude") or dcfg.get("binary"))
        prompt = (f"Un trabajador del equipo (agente local) está con la subtarea «{task['title']}» de tu plan y te "
                  f"pregunta:\n\n{question}\n\nResponde corto y concreto, con una decisión clara. No modifiques "
                  "archivos ni rehagas el plan.")
        spec = RunSpec(prompt=prompt, cwd=str(ws.path), model=director["model"], read_only=True, max_turns=3,
                       max_budget_usd=0.2, session_id=d["session_id"])
        got: dict = {"cost": 0.0}

        def collect(ev: Event) -> None:
            if ev.kind == "usage" and ev.data.get("cost_usd") is not None:
                got["cost"] = ev.data["cost_usd"]
        res = await run(adapter, spec, collect, timeout_s=300)
        if res["status"] != "done" or not (res.get("final") or "").strip():
            return "El Director no ha podido responder. Decide tú y explícalo en `terminar`.", got["cost"]
        return res["final"].strip(), got["cost"]
    return ask


NPM_SHIMS = {"npx", "npm", "pnpm", "yarn", "bunx"}


def win_shim(srv: dict, nt: bool | None = None) -> dict:
    """En Windows `npx` es un .cmd y la CLI de Claude no lo arranca directamente: hay que pasar por `cmd /c`."""
    nt = os.name == "nt" if nt is None else nt
    cmd = str(srv.get("command") or "")
    if nt and cmd.lower().removesuffix(".cmd") in NPM_SHIMS:
        return {**srv, "command": "cmd", "args": ["/c", cmd, *(srv.get("args") or [])]}
    return srv


def local_url(store: Store, cfg: dict) -> str:
    """A qué llama-server va un agente local: su `base_url`, si no el de su servidor local (`server`), si no el
    principal de Ajustes."""
    if cfg.get("base_url"):
        return cfg["base_url"]
    if cfg.get("server"):
        srv = next((s for s in settings.local_servers(store) if s["id"] == cfg["server"]), None)
        if srv:
            return settings.server_url(srv)
    return settings.load(store)["local_base_url"]


def local_endpoints(store: Store, only: list[str] | None = None) -> list[dict]:
    """Los servidores locales para el MCP de delegación: id, nombre, papel, GPU, URL y clave. El primero, el que usan
    los encargos si no hay papel que encaje (el principal). `only`: solo esos (config `local_servers` del agente)."""
    out = []
    joined = settings.load(store)["llama"].get("topology") == "unido"
    for srv in settings.local_servers(store):
        if only and srv["id"] not in only:
            continue
        url = settings.server_url(srv)
        if srv["id"] == llama.PRINCIPAL:
            url = settings.load(store)["local_base_url"] or url
        elif joined and not llama_up(url):
            # GPU unidas: normalmente solo queda el principal (con las dos). Pero si al lado sigue un modelo pequeño
            # (el 08/10, Qwen3.5-4B en la 1060 junto a gpt-oss), también trabaja: antes pasó 20 parches parado
            continue
        out.append({"id": srv["id"], "name": srv["name"], "role": srv["role"],
                    "device": srv["device"], "thinking": srv.get("thinking") or "normal", "url": url,
                    "key": llama.key_for_url(url) or ""})
    if joined and len(out) == 1:
        out[0]["role"] = "general"  # solo uno: lo hace todo
    return out


def any_llama_up(store: Store, only: list[str] | None = None) -> bool:
    return any(llama_up(e["url"]) for e in local_endpoints(store, only))


def llama_up(base_url: str, timeout: float = 2.0) -> bool:
    """¿Contesta el llama-server? (GET /health). Cualquier respuesta HTTP vale, también 503 = cargando el modelo:
    estará listo cuando Claude haga el primer encargo. Sin conexión = apagado."""
    import urllib.error
    import urllib.request
    url = base_url.rstrip("/").removesuffix("/v1") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, ValueError):
        return False


def worker_skill_catalog() -> dict[str, dict]:
    """Skills que puede llevar el trabajador local: las instaladas y las de la biblioteca (sin instalar hace falta)."""
    from localharness import library
    from localharness.context import load_skills
    out = {n: {"description": sk.description, "body": sk.body} for n, sk in load_skills().items()}
    try:
        for e in library.skill_library():
            if e["name"] not in out:
                meta_body = library._front(e["content"])[1]
                out[e["name"]] = {"description": e["description"], "body": meta_body}
    except OSError:
        pass
    return out


def worker_state(deleg: dict) -> dict:
    try:
        return json.loads(Path(deleg["worker"]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return {"skills": [], "tools": None}


def set_worker(task_id: int, skills: list[str], tools: list[str] | None) -> dict:
    """Desde la GUI, con la tarea en marcha: cambia las skills/herramientas del trabajador local para los encargos
    siguientes. El vigilante lo convierte en un evento `worker` (como cuando lo cambia Claude)."""
    from localharness.mcp_local import WORKER_TOOLS
    deleg = ACTIVE_WORKERS.get(task_id)
    if not deleg:
        raise LookupError("La tarea no está trabajando con el modelo local ahora mismo")
    known = json.loads(Path(deleg["skills"]).read_text(encoding="utf-8"))
    unknown = [n for n in skills if n not in known]
    if unknown:
        raise ValueError(f"No existen estas skills: {', '.join(unknown)}")
    if tools is not None and any(t not in WORKER_TOOLS for t in tools):
        raise ValueError(f"Herramientas válidas: {', '.join(WORKER_TOOLS)}")
    state = {**worker_state(deleg), "skills": list(dict.fromkeys(skills)), "tools": tools, "by": "tú",
             "reason": "", "at": time.time()}
    Path(deleg["worker"]).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return state


def _mcp_setup(store: Store, root: Path, cfg: dict, write: bool, coordinator: bool = False) -> dict | None:
    """Archivo `--mcp-config` de un agente Claude: los servidores del Catálogo que tiene asignados (`config.mcps`)
    y, con «Puede delegar en el modelo local», el servidor `local` (localharness.mcp_local). Va en una carpeta
    temporal (puede llevar la clave del llama-server) que se borra al terminar la tarea. None si no lleva ninguno."""
    catalog = settings.load(store).get("mcp_servers") or {}
    wanted = [n for n in cfg.get("mcps") or [] if n != "local"]
    servers = {n: win_shim({k: v for k, v in catalog[n].items() if k != "description"}) for n in wanted if n in catalog}
    delegate = bool(cfg.get("delegate_local"))
    if not servers and not delegate:
        return None
    d = Path(tempfile.mkdtemp(prefix="lh-mcp-"))
    log = d / "encargos.jsonl"
    tools = [f"mcp__{n}" for n in servers]  # regla de servidor: aprueba todas sus herramientas
    if delegate:
        endpoints = local_endpoints(store, cfg.get("local_servers"))
        env = {"LH_LOCAL_URL": endpoints[0]["url"], "LH_LOCAL_KEY": endpoints[0]["key"],
               # con dos GPU, dos modelos: el MCP reparte cada encargo según el papel de cada servidor
               "LH_LOCAL_SERVERS": json.dumps(endpoints, ensure_ascii=False),
               "LH_ROOT": str(root), "LH_LOG": str(log), "LH_WRITE": "1" if write else "0",
               "LH_COORDINATOR": "1" if coordinator else "0", "PYTHONIOENCODING": "utf-8",
               # para `local_models`/`local_use` (cambiar de modelo) y el RAG
               "LH_API": API_URL, "LH_EMBED_URL": settings.load(store)["llama"].get("embed_url") or "",
               "LH_AUTO_SWAP": "1" if settings.load(store)["llama"].get("auto_swap") else "0"}
        servers["local"] = {"type": "stdio", "command": sys.executable,
                            # por ruta: la CLI lo lanza desde el worktree, donde el paquete no está en el path
                            "args": [str(Path(mcp_local.__file__).resolve())], "env": env}
        if cfg.get("commands") is not None:
            env["LH_COMMANDS"] = json.dumps(cfg["commands"], ensure_ascii=False)
        # el trabajador local: catálogo de skills que puede llevar y su estado (skills/herramientas elegidas)
        catalog_skills = worker_skill_catalog()
        (d / "skills.json").write_text(json.dumps(catalog_skills, ensure_ascii=False), encoding="utf-8")
        start = [n for n in cfg.get("local_skills") or [] if n in catalog_skills]
        (d / "worker.json").write_text(json.dumps({"skills": start, "tools": None, "by": "agente" if start else "",
                                                   "reason": ""}, ensure_ascii=False), encoding="utf-8")
        env.update(LH_WORKER=str(d / "worker.json"), LH_SKILLS=str(d / "skills.json"), LH_LIVE=str(d / "live.json"))
        tools = ([DELEGATE_TOOLS[PREPARE_TOOL], DELEGATE_TOOLS["local_map"], DELEGATE_TOOLS["local_ask"]]
                 + ([DELEGATE_TOOLS["local_edit_file"], DELEGATE_TOOLS["local_write_file"], DELEGATE_TOOLS[PLAN_TOOL],
                     DELEGATE_TOOLS["local_plan"], DELEGATE_TOOLS["local_agent"]] if write else [])
                 + [DELEGATE_TOOLS[n] for n in ("local_read_documents", "local_look", "local_search", "local_models",
                                                "local_use")]
                 + ([DELEGATE_TOOLS["run_checks"]] if cfg.get("commands") != [] else [])
                 + [DELEGATE_TOOLS["local_research"]] + tools)
    path = d / "mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}, ensure_ascii=False), encoding="utf-8")
    # los encargos al modelo local pueden tardar minutos: el tope por defecto de la CLI para una herramienta MCP es corto
    return {"dir": d, "config": str(path), "log": log, "tools": tools, "seen": 0, "delegate": delegate,
            "worker": str(d / "worker.json"), "skills": str(d / "skills.json"), "worker_seen": None,
            "live": str(d / "live.json"), "live_at": 0.0,
            "missing": [n for n in wanted if n not in catalog],
            # sin --safe-mode (bloquea el MCP): el CLAUDE.md del usuario/vault se apaga con esta variable (verificado)
            "env": {"MCP_TOOL_TIMEOUT": "900000", "MCP_TIMEOUT": "30000", "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}}


def _delegation(store: Store, root: Path, write: bool) -> dict:
    """Solo el servidor del modelo local (lo que usaban las pruebas antes del Catálogo)."""
    return _mcp_setup(store, root, {"delegate_local": True}, write)


async def _watch_delegations(deleg: dict, sink: Callable[[Event], None], every: float = 1.0) -> None:
    """Mientras trabaja Claude: cada encargo terminado del modelo local aparece como evento `delegate`."""
    while True:
        await asyncio.sleep(every)
        _emit_new(deleg, sink)


def _flush_delegations(deleg: dict, sink: Callable[[Event], None]) -> None:
    from localharness.mcp_local import read_log
    _emit_new(deleg, sink)  # los que terminaron después del último vistazo
    # el resumen de un plan y los pasos sueltos del agente local no son encargos
    entries = [e for e in read_log(deleg["log"]) if e.get("tool") not in NOT_ENCARGOS and not e.get("progress")]
    if entries:
        tokens = sum((e.get("completion_tokens") or 0) + (e.get("prompt_tokens") or 0) for e in entries)
        ok = sum(1 for e in entries if e.get("ok"))
        sink(Event("delegate_summary", text=f"{ok} de {len(entries)} encargos al modelo local",
                   data={"calls": len(entries), "ok": ok, "local_tokens": tokens,
                         "by_tool": {n: sum(1 for e in entries if e.get("tool") == n)
                                     for n in sorted({str(e.get("tool")) for e in entries})}}))
    elif deleg["delegate"]:
        sink(Event("warning", text="Claude no le encargó nada al modelo local en esta tarea"))


def _emit_worker(deleg: dict, sink: Callable[[Event], None]) -> None:
    """Skills/herramientas del trabajador local cambiadas (por Claude con `local_prepare` o por ti en la oficina)."""
    if not deleg.get("worker"):
        return
    try:
        raw = Path(deleg["worker"]).read_text(encoding="utf-8")
    except OSError:
        return
    if raw == deleg.get("worker_seen"):
        return
    first = deleg.get("worker_seen") is None
    deleg["worker_seen"] = raw
    try:
        state = json.loads(raw)
    except ValueError:
        return
    if first and not state.get("skills") and state.get("tools") is None:
        return  # arranque sin nada elegido: no hace falta avisar
    skills = ", ".join(state.get("skills") or []) or "ninguna"
    who = {"Claude": "Claude equipó", "tú": "Cambiaste", "agente": "El agente trae"}.get(state.get("by"), "Equipado")
    sink(Event("worker", text=f"{who} al trabajador local · skills: {skills}"[:300], data=state))


def _emit_live(deleg: dict, sink: Callable[[Event], None]) -> None:
    """El trabajador local pensando y escribiendo AHORA (en vivo para la oficina; no se guarda)."""
    try:
        data = json.loads(Path(deleg["live"]).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return
    if not isinstance(data, dict):
        return
    seen = deleg.setdefault("live_by", {})
    # uno por modelo local: con dos GPU, los dos pueden estar escribiendo a la vez
    for sid, entry in (data.get("servers") or {str(data.get("server") or ""): data}).items():
        if not isinstance(entry, dict) or entry.get("at", 0) <= seen.get(sid, 0):
            continue
        seen[sid] = entry["at"]
        sink(Event("worker_live", text=str(entry.get("task") or "")[:200], data=entry))


def _emit_new(deleg: dict, sink: Callable[[Event], None]) -> None:
    from localharness.mcp_local import read_log
    _emit_worker(deleg, sink)
    _emit_live(deleg, sink)
    entries = read_log(deleg["log"])
    for e in entries[deleg["seen"]:]:
        if e.get("progress"):  # paso a paso del agente local mientras trabaja un encargo de `local_agent`
            if e.get("thinking"):  # su pensamiento: para el inspector del trabajador local
                sink(Event("worker_thinking", text=e["thinking"][-4000:]))
            else:
                sink(Event("progress", text=f"Modelo local: {e.get('text', '')}"[:300]))
            continue
        what = e.get("path") or e.get("task") or ""
        sink(Event("delegate", text=f"{e.get('tool')}: {what}"[:300], data=e))
    deleg["seen"] = len(entries)


def _conversation(store: Store, task: dict) -> list[tuple[str, str]]:
    """Turnos (quién, texto) hasta ahora: tu petición, tus respuestas y la respuesta final de cada vuelta."""
    turns = [("user", task["prompt"])]
    for e in store.list_events(task["id"]):
        if e["kind"] == "user":
            turns.append(("user", e["text"]))
        elif e["kind"] == "result" and e["text"]:
            turns.append(("agent", e["text"]))
    if task.get("final") and (turns[-1][0] != "agent"):
        turns.append(("agent", task["final"]))
    return turns


def transcript(history: list[tuple[str, str]], followup: str) -> str:
    who = {"user": "Usuario", "agent": "Tú (asistente)"}
    lines = [f"### {who[w]}\n{t}" for w, t in history]
    return ("Continúa esta conversación. Lo hablado hasta ahora:\n\n" + "\n\n".join(lines) +
            f"\n\n### Usuario (mensaje nuevo, respóndelo)\n{followup}")


def git_stat(ws: workspace.Workspace, base: str, head: str) -> str:
    return workspace.git(ws.path, "diff", "--stat", base, head)


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
