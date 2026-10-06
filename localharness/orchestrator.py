"""Ciclo de una tarea: worktree -> agente -> checkpoint -> diff listo para revisar. Sin push automático."""

import asyncio
import json
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from localharness import llama, mcp_local, settings, workspace
from localharness.adapters import get_adapter
from localharness.adapters.base import RunSpec
from localharness.adapters.claude import SUBAGENT_TOOL
from localharness.adapters.local import config_kwargs
from localharness.context import build_prompt, load_memory, load_skills
from localharness.events import Event
from localharness.runner import run
from localharness.store import Store

EPHEMERAL = ("speed",)  # en vivo para la GUI, no se guardan (llegan cada ~1,5 s)

DELEGATE_TOOLS = {"local_ask": "mcp__local__local_ask", "local_write_file": "mcp__local__local_write_file"}
DELEGATE_GUIDE = """
DELEGACIÓN EN EL MODELO LOCAL (ahorra tu cuota; úsala siempre que encaje):
Tienes un modelo local GRATUITO con las herramientas `local_ask` y `local_write_file`.
- Resumir, explicar o entender archivos: `local_ask` con las rutas en `files` (NO los leas tú antes).
- Comparar opciones, pensar alternativas, buscar fallos en un archivo, redactar texto: `local_ask`.
- Escribir código nuevo o reescribir un archivo entero: `local_write_file` con instrucciones precisas
  (qué debe contener, funciones y firmas, estilo, casos límite). Para cambios de pocas líneas usa Edit tú.
Tú decides, planificas y verificas: es un modelo pequeño. Revisa lo que escriba (Read de las partes clave) y
corrige con Edit si hace falta. Si responde que no hay modelo local, hazlo tú."""


def delegate_guide(write: bool) -> str:
    if write:
        return DELEGATE_GUIDE
    # solo lectura (Director, jefe técnico): únicamente `local_ask`
    lines = [ln for ln in DELEGATE_GUIDE.split("\n") if "local_write_file` con" not in ln and "(qué debe contener" not in ln]
    return "\n".join(lines).replace("las herramientas `local_ask` y `local_write_file`", "la herramienta `local_ask`")


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
             if agent["provider"] == "local" else {})
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

    ro = bool(cfg.get("read_only")) if read_only is None else read_only
    deleg = (_delegation(store, ws.path, write=not ro)
             if cfg.get("delegate_local") and agent["provider"] == "claude" else None)
    if deleg and not resume:
        prompt += "\n" + delegate_guide(write=not ro)
    spec = RunSpec(prompt=prompt, cwd=str(ws.path), model=agent["model"],
                   max_turns=cfg.get("max_turns"), max_budget_usd=cfg.get("max_budget_usd"),
                   read_only=ro, allowed_tools=cfg.get("tools"), json_schema=json_schema,
                   extra_tools=[SUBAGENT_TOOL] if cfg.get("subagents") and agent["provider"] == "claude" else [],
                   session_id=task["session_id"] if resume else None,
                   mcp_config=deleg["config"] if deleg else None, mcp_tools=deleg["tools"] if deleg else [],
                   env=deleg["env"] if deleg else {})
    if followup is not None:
        sink(Event("user", text=followup))
    sink(Event("status", text="running"))
    if injected["memory"] or injected["skills"]:
        names = [m["file"] for m in injected["memory"]] + [s["name"] for s in injected["skills"]]
        sink(Event("context", text=", ".join(names), data=injected))
    if missing:
        sink(Event("warning", text=f"Skills no encontradas: {', '.join(missing)}"))
    watcher = asyncio.create_task(_watch_delegations(deleg, sink)) if deleg else None
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


def _delegation(store: Store, root: Path, write: bool) -> dict:
    """Archivo de MCP para que Claude encargue trabajo al llama-server (localharness.mcp_local). Va en una
    carpeta temporal (lleva la clave del llama-server) que se borra al terminar la tarea."""
    d = Path(tempfile.mkdtemp(prefix="lh-mcp-"))
    log = d / "encargos.jsonl"
    env = {"LH_LOCAL_URL": settings.load(store)["local_base_url"], "LH_LOCAL_KEY": llama.API_KEY or "",
           "LH_ROOT": str(root), "LH_LOG": str(log), "LH_WRITE": "1" if write else "0", "PYTHONIOENCODING": "utf-8"}
    cfg = {"mcpServers": {"local": {"type": "stdio", "command": sys.executable,
                                     # por ruta: la CLI lo lanza desde el worktree, donde el paquete no está en el path
                                     "args": [str(Path(mcp_local.__file__).resolve())], "env": env}}}
    path = d / "mcp.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    tools = [DELEGATE_TOOLS["local_ask"]] + ([DELEGATE_TOOLS["local_write_file"]] if write else [])
    # los encargos al modelo local pueden tardar minutos: el tope por defecto de la CLI para una herramienta MCP es corto
    return {"dir": d, "config": str(path), "log": log, "tools": tools, "seen": 0,
            # sin --safe-mode (bloquea el MCP): el CLAUDE.md del usuario/vault se apaga con esta variable (verificado)
            "env": {"MCP_TOOL_TIMEOUT": "900000", "MCP_TIMEOUT": "30000", "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}}


async def _watch_delegations(deleg: dict, sink: Callable[[Event], None], every: float = 1.0) -> None:
    """Mientras trabaja Claude: cada encargo terminado del modelo local aparece como evento `delegate`."""
    while True:
        await asyncio.sleep(every)
        _emit_new(deleg, sink)


def _flush_delegations(deleg: dict, sink: Callable[[Event], None]) -> None:
    from localharness.mcp_local import read_log
    _emit_new(deleg, sink)  # los que terminaron después del último vistazo
    entries = read_log(deleg["log"])
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
