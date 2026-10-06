"""Espacio de trabajo por tarea: rama + git worktree. Nada llega a la rama principal sin aprobación."""

import subprocess
import threading
import shutil
from dataclasses import dataclass
from pathlib import Path


_CREATE_LOCK = threading.Lock()  # git worktree add concurrente corrompe metadatos (lección de vibe-kanban)


class GitError(Exception):
    pass


class MergeConflict(GitError):
    def __init__(self, branch: str, target: str, files: list[str]):
        self.branch, self.target, self.files = branch, target, files
        shown = ", ".join(files[:8]) + (f" y {len(files) - 8} más" if len(files) > 8 else "")
        super().__init__(f"Conflicto al integrar {branch} en {target}: {shown}. No se ha tocado tu rama. "
                         "Pide al agente que rehaga el cambio sobre la versión actual, o resuélvelo a mano.")


def conflicts(repo: str | Path, target: str, branch: str) -> list[str]:
    """Archivos que darían conflicto al integrar `branch` en `target`, sin tocar el árbol de trabajo
    (`git merge-tree --write-tree`, git ≥ 2.38). Vacío si no hay conflicto o si git es antiguo."""
    p = subprocess.run(["git", "-c", "core.quotepath=off", "merge-tree", "--write-tree", "--name-only",
                        "--no-messages", target, branch], cwd=repo, capture_output=True, encoding="utf-8",
                       errors="replace")
    if p.returncode != 1:  # 0 = limpio; otro = error (git antiguo): el merge real lo detectará y abortará
        return []
    return [f for f in p.stdout.splitlines()[1:] if f.strip()]


def localharness_branches(repo: str | Path) -> dict[str, str | None]:
    """Ramas `localharness/*` del repo → ruta de su worktree (None si no tiene)."""
    branches = {b.strip(): None for b in git(repo, "branch", "--list", "--format=%(refname:short)",
                                             "localharness/*").splitlines() if b.strip()}
    path = None
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("branch refs/heads/localharness/"):
            branches[line[18:]] = path
    return branches


def git(cwd: str | Path, *args: str) -> str:
    # UTF-8 explícito: en Windows text=True decodifica en cp1252 y rompe las tildes de los diffs
    p = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=cwd, capture_output=True,
                       encoding="utf-8", errors="replace")
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
        """Integra la rama de la tarea (solo tras aprobación explícita). Nunca hace push.
        Con conflictos NO deja el repo a medias: se detectan antes (merge-tree) y, si aun así el merge falla,
        se aborta y se vuelve a la rama en la que estabas. Lanza MergeConflict con los archivos."""
        if git(self.repo, "status", "--porcelain", "--untracked-files=no").strip():
            raise GitError("El repo principal tiene cambios sin confirmar: no se integra nada encima")
        prev = git(self.repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        target = into or prev
        files = conflicts(self.repo, target, self.branch)
        if files:
            raise MergeConflict(self.branch, target, files)
        if into and into != prev:
            git(self.repo, "checkout", "-q", into)
        try:
            return git(self.repo, "merge", "--no-ff", "-m", f"localharness: {self.branch}", self.branch)
        except GitError:
            files = [f for f in git(self.repo, "diff", "--name-only", "--diff-filter=U").splitlines() if f]
            try:
                git(self.repo, "merge", "--abort")
            except GitError:
                pass
            if into and into != prev:
                git(self.repo, "checkout", "-q", prev)
            if files:
                raise MergeConflict(self.branch, target, files) from None
            raise

    def remove(self) -> None:
        git(self.repo, "worktree", "remove", "--force", str(self.path))
        git(self.repo, "branch", "-D", self.branch)


def init_repo(path: str | Path) -> None:
    """Convierte una carpeta en repo con un commit inicial de todo lo que hay (solo cuando tú lo pides)."""
    git(path, "init", "-q")
    git(path, "add", "-A")
    git(path, "-c", "user.name=localharness", "-c", "user.email=localharness@local", "commit", "-q",
        "--allow-empty", "-m", "LocalHarness: estado inicial")


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
