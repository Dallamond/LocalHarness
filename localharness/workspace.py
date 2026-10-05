"""Espacio de trabajo por tarea: rama + git worktree. Nada llega a la rama principal sin aprobación."""

import subprocess
import threading
import shutil
from dataclasses import dataclass
from pathlib import Path


_CREATE_LOCK = threading.Lock()  # git worktree add concurrente corrompe metadatos (lección de vibe-kanban)


class GitError(Exception):
    pass


def git(cwd: str | Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


@dataclass
class Workspace:
    repo: Path
    path: Path
    branch: str
    base: str  # commit del que parte

    def diff(self) -> str:
        """Todo lo hecho por el agente respecto a la base, incluidos archivos nuevos."""
        git(self.path, "add", "-A", "-N")  # intent-to-add: los nuevos aparecen en el diff
        return git(self.path, "diff", self.base)

    def stat(self) -> str:
        git(self.path, "add", "-A", "-N")
        return git(self.path, "diff", "--stat", self.base)

    def diff_range(self, frm: str, to: str | None = None) -> str:
        """Diff entre dos commits; sin `to`, contra el árbol de trabajo (incluye archivos nuevos)."""
        if to is None:
            git(self.path, "add", "-A", "-N")
            return git(self.path, "diff", frm)
        return git(self.path, "diff", frm, to)

    def changes(self, frm: str | None = None, to: str | None = None) -> list:
        """Archivos cambiados con estado y líneas, para la política de riesgo."""
        from localharness.policy import parse_numstat
        frm = frm or self.base
        rng = [frm] + ([to] if to else [])
        if to is None:
            git(self.path, "add", "-A", "-N")
        return parse_numstat(git(self.path, "diff", "--numstat", *rng), git(self.path, "diff", "--name-status", *rng))

    def head(self) -> str:
        return git(self.path, "rev-parse", "HEAD").strip()

    def checkpoint(self, message: str) -> str | None:
        git(self.path, "add", "-A")
        if not git(self.path, "status", "--porcelain").strip():
            return None
        git(self.path, "-c", "user.name=localharness", "-c", "user.email=localharness@local", "commit", "-q", "-m", message)
        return git(self.path, "rev-parse", "HEAD").strip()

    def merge(self, into: str | None = None) -> str:
        """Integra la rama de la tarea (solo tras aprobación explícita). Nunca hace push."""
        if git(self.repo, "status", "--porcelain", "--untracked-files=no").strip():
            raise GitError("El repo principal tiene cambios sin confirmar: no se integra nada encima")
        if into:
            git(self.repo, "checkout", "-q", into)
        return git(self.repo, "merge", "--no-ff", "-m", f"localharness: {self.branch}", self.branch)

    def remove(self) -> None:
        git(self.repo, "worktree", "remove", "--force", str(self.path))
        git(self.repo, "branch", "-D", self.branch)


def create(repo: str | Path, task_id: int | str, root: str | Path | None = None, link_node_modules: bool = False) -> Workspace:
    """`task_id` entero → rama `localharness/task-N`; texto (p. ej. «plan-3») → `localharness/plan-3`."""
    repo = Path(repo).resolve()
    git(repo, "rev-parse", "--git-dir")  # falla si no es un repo
    base = git(repo, "rev-parse", "HEAD").strip()
    name = f"task-{task_id}" if isinstance(task_id, int) else task_id
    branch = f"localharness/{name}"
    root = Path(root) if root else repo.parent / ".localharness-worktrees" / repo.name
    root.mkdir(parents=True, exist_ok=True)
    path = (root / name).resolve()
    with _CREATE_LOCK:
        _clean_stale(repo, path, branch)
        git(repo, "worktree", "add", "-q", "-b", branch, str(path), base)
    if link_node_modules:
        _link_node_modules(repo, path)
    return Workspace(repo, path, branch, base)


def _clean_stale(repo: Path, path: Path, branch: str) -> None:
    """Restos de un intento anterior (ruta o rama huérfanas) bloquean `worktree add`."""
    git(repo, "worktree", "prune")
    if path.exists():
        try:
            git(repo, "worktree", "remove", "--force", str(path))
        except GitError:
            shutil.rmtree(path, ignore_errors=True)
            git(repo, "worktree", "prune")
    if branch in git(repo, "branch", "--list", branch):
        git(repo, "branch", "-D", branch)


def _link_node_modules(repo: Path, wt: Path) -> None:
    """Enlaza node_modules del repo. Un symlink NO lo cubre un `.gitignore` con `node_modules/`
    (barra final = solo directorios), así que se excluye explícitamente (lección de parallel-code)."""
    src = repo / "node_modules"
    if not src.is_dir() or (wt / "node_modules").exists():
        return
    try:
        (wt / "node_modules").symlink_to(src, target_is_directory=True)
    except OSError:  # Windows sin permiso de symlinks
        return
    exclude = Path(git(wt, "rev-parse", "--git-path", "info/exclude").strip())
    exclude = exclude if exclude.is_absolute() else wt / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    text = exclude.read_text() if exclude.exists() else ""
    if "node_modules" not in text.split():
        exclude.write_text(text + ("\n" if text and not text.endswith("\n") else "") + "node_modules\n")
