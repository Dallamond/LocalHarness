"""M6 — limpieza de worktrees y ramas `localharness/*` que ya no sirven (al arrancar y con `localharness cleanup`).

Solo se borra lo que está CERRADO en la base de datos y por tanto no tiene trabajo pendiente:
- tareas sueltas integradas, rechazadas, descartadas o terminadas sin cambios (`done`);
- planes integrados, rechazados o terminados sin cambios.
Lo fallido, cancelado o interrumpido se conserva (lo hecho queda en la rama «por si sirve») y lo que no aparece
en la base de datos (otra instalación, a mano) solo se informa: nunca se borra trabajo que no sabemos de quién es.
"""

import re
from pathlib import Path

from localharness import workspace
from localharness.store import Store

CLOSED_TASK = ("merged", "rejected", "discarded", "done")
CLOSED_PLAN = ("merged", "rejected", "done")


def cleanup(store: Store, dry_run: bool = False) -> dict:
    report = {"removed": [], "kept": [], "unknown": [], "errors": []}
    for project in store.list_projects():
        repo = Path(project["repo_path"])
        if not repo.is_dir():
            continue
        try:
            workspace.git(repo, "worktree", "prune")
            branches = workspace.localharness_branches(repo)
        except (workspace.GitError, OSError) as e:
            report["errors"].append(f"{project['name']}: {e}")
            continue
        for branch, path in branches.items():
            item = {"project": project["name"], "branch": branch, "worktree": path}
            m = re.fullmatch(r"localharness/(task|plan)-(\d+)", branch)
            row = None
            if m:
                row = (store.get_task if m[1] == "task" else store.get_plan)(int(m[2]))
            if not row or row["project_id"] != project["id"]:
                report["unknown"].append(item)
                continue
            closed = CLOSED_TASK if m[1] == "task" else CLOSED_PLAN
            if row["status"] not in closed:
                report["kept"].append({**item, "status": row["status"]})
                continue
            if not dry_run:
                try:
                    if path:
                        workspace.git(repo, "worktree", "remove", "--force", path)
                    workspace.git(repo, "branch", "-D", branch)
                except workspace.GitError as e:
                    report["errors"].append(f"{branch}: {e}")
                    continue
            report["removed"].append({**item, "status": row["status"]})
    return report
