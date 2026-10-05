"""Acciones de revisión sobre una tarea, comunes al CLI y a la API. Ninguna hace push."""

import datetime
from pathlib import Path

from localharness import workspace
from localharness.store import Store

REVIEWABLE = ("review", "approved")
FINISHED = ("review", "approved", "failed", "timeout", "cancelled", "interrupted")


class ActionError(Exception):
    pass


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def task_workspace(store: Store, task: dict) -> workspace.Workspace | None:
    if not task.get("worktree") or not task.get("branch"):
        return None
    project = store.get_project(task["project_id"])
    return workspace.Workspace(Path(project["repo_path"]), Path(task["worktree"]), task["branch"],
                               task["base_commit"])


def target_branch(store: Store, task: dict) -> str:
    project = store.get_project(task["project_id"])
    return workspace.git(project["repo_path"], "rev-parse", "--abbrev-ref", "HEAD").strip()


def review_data(store: Store, task: dict) -> dict:
    ws = task_workspace(store, task)
    if not ws or not ws.path.exists():
        return {"available": False, "stat": "", "diff": "", "target": None}
    base, head = task.get("base_commit") or ws.base, task.get("head_commit")
    if head:  # resultado fijado en su commit (las subtareas de un plan comparten rama)
        stat, diff = workspace.git(ws.path, "diff", "--stat", base, head), ws.diff_range(base, head)
    else:
        stat, diff = workspace.git(ws.path, "diff", "--stat", base), ws.diff_range(base)
    return {"available": True, "stat": stat, "diff": diff, "target": target_branch(store, task)}


def _get(store: Store, tid: int) -> dict:
    task = store.get_task(tid)
    if not task:
        raise ActionError(f"No existe la tarea #{tid}")
    return task


def approve(store: Store, tid: int) -> dict:
    task = _get(store, tid)
    if task["status"] != "review":
        raise ActionError(f"Solo se aprueba una tarea en 'review' (está en '{task['status']}')")
    store.update_task(tid, status="approved")
    return _get(store, tid)


def merge(store: Store, tid: int, into: str | None = None, require_approved: bool = False) -> dict:
    """Integra la rama de la tarea en la rama actual del repo (o `into`). Nunca hace push."""
    task = _get(store, tid)
    allowed = ("approved",) if require_approved else REVIEWABLE
    if task["status"] not in allowed:
        raise ActionError(f"Solo se integra una tarea en {' o '.join(allowed)} (está en '{task['status']}')")
    ws = task_workspace(store, task)
    target = into or target_branch(store, task)
    try:
        ws.merge(into)
        ws.remove()
    except workspace.GitError as e:
        raise ActionError(str(e)) from None
    store.update_task(tid, status="merged", finished_at=now())
    return {**_get(store, tid), "target": target}


def discard(store: Store, tid: int, status: str = "discarded") -> dict:
    """Rechaza/descarta: borra worktree y rama. Lo hecho por el agente se pierde."""
    task = _get(store, tid)
    if task["status"] in ("running", "pending"):
        raise ActionError("La tarea está en marcha: cancélala antes")
    if task["status"] == "merged":
        raise ActionError("La tarea ya está integrada")
    ws = task_workspace(store, task)
    if ws:
        try:
            ws.remove()
        except workspace.GitError:
            pass  # ya no existía: no impide marcarla
    store.update_task(tid, status=status, finished_at=now())
    return _get(store, tid)
