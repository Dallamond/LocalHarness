"""Ciclo de una tarea: worktree -> agente -> checkpoint -> diff listo para revisar. Sin push automático."""

import json
from collections.abc import Callable

from localharness import workspace
from localharness.adapters import get_adapter
from localharness.adapters.base import RunSpec
from localharness.events import Event
from localharness.runner import run
from localharness.store import Store


async def execute_task(store: Store, task_id: int, *, binaries: dict[str, str] | None = None,
                       on_event: Callable[[int, Event], None] | None = None,
                       worktree_root: str | None = None, timeout_s: float = 1800.0) -> dict:
    task = store.get_task(task_id)
    if not task:
        raise ValueError(f"Tarea {task_id} no existe")
    project = store.get_project(task["project_id"])
    agent = store.get_agent(task["agent_id"]) if task["agent_id"] else None
    if not project or not agent:
        raise ValueError("La tarea necesita proyecto y agente")
    busy = [t for t in store.list_tasks(project["id"], status="running") if t["id"] != task_id]
    if busy:  # conflictos de merge entre tareas: por ahora, una tarea por repo a la vez
        raise ValueError(f"El proyecto ya tiene una tarea en curso: #{busy[0]['id']}")
    cfg = json.loads(agent["config"] or "{}")
    adapter = get_adapter(agent["provider"], binary=(binaries or {}).get(agent["provider"]) or cfg.get("binary"))

    ws = workspace.create(project["repo_path"], task_id, worktree_root)
    store.update_task(task_id, status="running", branch=ws.branch, worktree=str(ws.path), base_commit=ws.base)

    def sink(ev: Event) -> None:
        store.add_event(task_id, ev.kind, ev.text, ev.data)
        if ev.kind == "session" and ev.data.get("session_id"):
            store.update_task(task_id, session_id=ev.data["session_id"])
        if ev.kind == "usage" and ev.data.get("cost_usd") is not None:
            store.update_task(task_id, cost_usd=ev.data["cost_usd"])
        if on_event:
            on_event(task_id, ev)

    spec = RunSpec(prompt=task["prompt"], cwd=str(ws.path), model=agent["model"],
                   max_turns=cfg.get("max_turns"), max_budget_usd=cfg.get("max_budget_usd"),
                   read_only=bool(cfg.get("read_only")), allowed_tools=cfg.get("tools"))
    res = await run(adapter, spec, sink, timeout_s=cfg.get("timeout_s") or timeout_s)
    ws.checkpoint(f"localharness: {task['title']}")
    status = "review" if res["status"] == "done" else res["status"]  # 'review' = esperando tu aprobación
    store.update_task(task_id, status=status, final=res["final"], finished_at=_now())
    return {**res, "status": status, "diff": ws.diff(), "stat": ws.stat()}


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
