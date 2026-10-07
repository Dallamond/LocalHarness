"""Ciclo de una tarea: worktree -> agente -> checkpoint -> diff listo para revisar. Sin push automático."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from localharness import llama, mcp_local, settings, workspace
from localharness.adapters import get_adapter
from localharness.adapters.base import THINKING_LEVELS, RunSpec
from localharness.adapters.claude import READ_TOOLS, SUBAGENT_TOOL, WEB_TOOLS, thinking_env
from localharness.adapters.local import config_kwargs
from localharness.context import build_prompt, load_memory, load_skills
from localharness.events import Event
from localharness.runner import run
from localharness.store import Store

EPHEMERAL = ("speed", "thinking_live")  # en vivo para la GUI, no se guardan (llegan cada ~1,5 s)

DELEGATE_TOOLS = {"local_ask": "mcp__local__local_ask", "local_write_file": "mcp__local__local_write_file",
                  "local_execute_plan": "mcp__local__local_execute_plan",
                  "local_research": "mcp__local__local_research"}
PLAN_TOOL = "local_execute_plan"
DELEGATE_GUIDE = """
DELEGACIÓN EN EL MODELO LOCAL — OBLIGATORIA cuando encaje (tu cuota es cara; el modelo local es gratis):
Tienes un modelo local con las herramientas `local_ask`, `local_write_file` y `local_research`. Reglas:
1. NO leas archivos tú para entenderlos, resumirlos o buscar fallos: llama a `local_ask` con sus rutas en `files`.
   Solo haces Read tú de las líneas concretas que vayas a editar o verificar.
2. Preguntas, explicaciones, comparar opciones, redactar texto o documentación: `local_ask` y usa su respuesta.
3. Código nuevo o un archivo reescrito entero: `local_write_file` con instrucciones precisas
   (qué debe contener, funciones y firmas, estilo, casos límite). Cambios de pocas líneas: Edit tú.
4. Empieza SIEMPRE por un encargo al modelo local antes de trabajar tú, salvo que la tarea sea de 1–2 líneas.
5. Buscar en internet (documentación, errores, versiones, APIs): `local_research`; te devuelve respuesta y fuentes.
Tú decides, planificas y verificas: es un modelo pequeño. Revisa lo que escriba (Read de las partes clave) y
corrige con Edit si hace falta. Si responde que no hay modelo local, hazlo tú y dilo al final."""

COORDINATOR_GUIDE = """
MODO COORDINADOR — TÚ NO HACES EL TRABAJO: lo hace el modelo local; tú planificas y presentas.
No tienes Edit, Write ni Bash: no puedes escribir archivos ni ejecutar nada. Todo lo que haya que generar
(código, tests, documentación, correcciones) lo genera el modelo local con sus herramientas. Sigue SIEMPRE
este ciclo, sin saltarte pasos:
1. ENTIENDE LA PETICIÓN ENTERA y sepárala en BLOQUES independientes: cada archivo a crear o reescribir es un
   bloque `write` (con su `path`); cada pregunta o análisis, un bloque `ask`. No resuelvas los bloques tú.
2. EXPLORA LO JUSTO: Glob para ver la estructura. Para entender código o encontrar fallos NO leas tú los
   archivos: `local_ask` con sus rutas en `files` (puedes pedirle de una vez «lista todos los fallos de estos
   archivos con archivo, línea y corrección»).
3. PLANIFICA: escribe el plan en tu respuesta (bloques numerados: archivo, qué cambia y por qué) ANTES de
   encargarlo. Las instrucciones de cada bloque son autocontenidas: el modelo local no ve esta conversación;
   di qué arreglar exactamente, firmas, casos límite y estilo, y pon en `files` lo que debe leer (incluido lo
   que escriban bloques anteriores si depende de ello, p. ej. el módulo en un bloque de tests). Un bloque
   `write` reescribe el archivo ENTERO: pídele que conserve lo que no cambia.
4. ENCARGA EL PLAN ENTERO en UNA llamada a `local_execute_plan` (todos los bloques, en orden) con `check` =
   la orden de los tests si los hay (p. ej. «python -m unittest»).
5. LEE EL INFORME. Si un bloque falló o la comprobación no pasa, vuelve a llamar a `local_execute_plan` solo
   con esos bloques y con instrucciones corregidas (como mucho 2 rondas). Puedes hacer Read de las partes
   clave para verificar, no para reescribirlas.
6. PRESENTA: el plan (bloques), qué hizo el modelo local en cada uno, el resultado de la comprobación y lo que
   quede pendiente o dudoso. Sé honesto: si algo no quedó bien, dilo.
Si el modelo local no responde (no hay modelo arrancado), para y díselo al usuario: no hay otro camino."""


def delegate_guide(write: bool) -> str:
    if write:
        return DELEGATE_GUIDE + ("\nVarios archivos a la vez (un plan con varios bloques): `local_execute_plan` con "
                                 "todos los bloques en una llamada y `check` = la orden de los tests.")
    # solo lectura (Director, jefe técnico): únicamente `local_ask`
    lines = [ln for ln in DELEGATE_GUIDE.split("\n") if "local_write_file` con" not in ln and "(qué debe contener" not in ln]
    return ("\n".join(lines).replace("las herramientas `local_ask` y `local_write_file`", "la herramienta `local_ask`")
            .replace("3. Código nuevo", "3. (Solo lectura: no escribes archivos.) Código nuevo"))


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
    # la URL del llama-server del agente manda; si no tiene, la de Ajustes
    extra = ({**config_kwargs({"base_url": settings.load(store)["local_base_url"], **cfg}), "api_key": llama.API_KEY}
             if agent["provider"] in ("local", "local_agent") else {})
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
    # modo coordinador: Claude planifica y presenta; todo lo que se escribe lo genera el modelo local
    coord = is_claude and bool(cfg.get("coordinator")) and not ro
    deleg = _mcp_setup(store, ws.path, {**cfg, "delegate_local": True} if coord else cfg, write=not ro,
                       coordinator=coord) if is_claude else None
    if deleg and deleg["missing"]:
        sink(Event("warning", text=f"Servidores MCP no encontrados en el Catálogo: {', '.join(deleg['missing'])}"))
    if coord and not resume:
        prompt += "\n" + COORDINATOR_GUIDE
    elif deleg and deleg["delegate"] and (not resume or not _had_delegation(store, task_id)):
        # también al continuar una conversación que empezó sin la casilla: la sesión no sabe que ahora puede delegar
        prompt += "\n" + delegate_guide(write=not ro)
    thinking = task.get("thinking") or cfg.get("thinking")
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
                   env=deleg_env,
                   ask_director=(_director_line(store, task, ws, binaries)
                                 if agent["provider"] == "local_agent" else None))
    if followup is not None:
        sink(Event("user", text=followup))
    sink(Event("status", text="running"))
    if injected["memory"] or injected["skills"]:
        names = [m["file"] for m in injected["memory"]] + [s["name"] for s in injected["skills"]]
        sink(Event("context", text=", ".join(names), data=injected))
    if missing:
        sink(Event("warning", text=f"Skills no encontradas: {', '.join(missing)}"))
    if coord and not llama_up(settings.load(store)["local_base_url"]):
        sink(Event("warning", text="Modo coordinador sin modelo local arrancado: Claude no podrá encargar nada "
                                   "(Modelos locales → Arrancar)"))
    watcher = asyncio.create_task(_watch_delegations(deleg, sink)) if deleg and deleg["delegate"] else None
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


def _had_delegation(store: Store, task_id: int) -> bool:
    """¿La sesión ya arrancó alguna vez con las herramientas del modelo local?"""
    for e in reversed(store.list_events(task_id)):
        if e["kind"] == "session":
            if any(str(t).startswith("mcp__local__") for t in json.loads(e["data"] or "{}").get("tools") or []):
                return True
    return False


NPM_SHIMS = {"npx", "npm", "pnpm", "yarn", "bunx"}


def win_shim(srv: dict, nt: bool | None = None) -> dict:
    """En Windows `npx` es un .cmd y la CLI de Claude no lo arranca directamente: hay que pasar por `cmd /c`."""
    nt = os.name == "nt" if nt is None else nt
    cmd = str(srv.get("command") or "")
    if nt and cmd.lower().removesuffix(".cmd") in NPM_SHIMS:
        return {**srv, "command": "cmd", "args": ["/c", cmd, *(srv.get("args") or [])]}
    return srv


def llama_up(base_url: str, timeout: float = 2.0) -> bool:
    """¿Contesta el llama-server? (GET /health). Solo para avisar: no impide lanzar la tarea."""
    import urllib.request
    url = base_url.rstrip("/").removesuffix("/v1") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status < 500
    except Exception:  # noqa: BLE001 — 503 (cargando), sin conexión…
        return False


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
        env = {"LH_LOCAL_URL": settings.load(store)["local_base_url"], "LH_LOCAL_KEY": llama.API_KEY or "",
               "LH_ROOT": str(root), "LH_LOG": str(log), "LH_WRITE": "1" if write else "0",
               "LH_COORDINATOR": "1" if coordinator else "0", "PYTHONIOENCODING": "utf-8"}
        servers["local"] = {"type": "stdio", "command": sys.executable,
                            # por ruta: la CLI lo lanza desde el worktree, donde el paquete no está en el path
                            "args": [str(Path(mcp_local.__file__).resolve())], "env": env}
        tools = ([DELEGATE_TOOLS["local_ask"]]
                 + ([DELEGATE_TOOLS["local_write_file"], DELEGATE_TOOLS[PLAN_TOOL]] if write else [])
                 + [DELEGATE_TOOLS["local_research"]] + tools)
    path = d / "mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}, ensure_ascii=False), encoding="utf-8")
    # los encargos al modelo local pueden tardar minutos: el tope por defecto de la CLI para una herramienta MCP es corto
    return {"dir": d, "config": str(path), "log": log, "tools": tools, "seen": 0, "delegate": delegate,
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
    entries = [e for e in read_log(deleg["log"]) if e.get("tool") != PLAN_TOOL]  # el resumen del plan no es un encargo
    if entries:
        tokens = sum((e.get("completion_tokens") or 0) + (e.get("prompt_tokens") or 0) for e in entries)
        ok = sum(1 for e in entries if e.get("ok"))
        sink(Event("delegate_summary", text=f"{ok} de {len(entries)} encargos al modelo local",
                   data={"calls": len(entries), "ok": ok, "local_tokens": tokens}))


def _emit_new(deleg: dict, sink: Callable[[Event], None]) -> None:
    from localharness.mcp_local import read_log
    entries = read_log(deleg["log"])
    for e in entries[deleg["seen"]:]:
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
