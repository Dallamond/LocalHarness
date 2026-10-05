"""Política de aprobación N0/N1/N2 con reglas deterministas sobre el diff (hoja de ruta §3).

N0 automático · N1 jefe técnico · N2 tú. El nivel final es el MÁXIMO entre el riesgo declarado por el
planificador, el que calculan estas reglas y lo que pida el revisor: un LLM puede subir el nivel, nunca bajarlo.
"""

import fnmatch
from dataclasses import dataclass, field

N0, N1, N2 = 0, 1, 2
LEVEL_NAME = {N0: "N0", N1: "N1", N2: "N2"}
RISK_LEVEL = {"low": N0, "medium": N1, "high": N2}

# Propuesta de la hoja de ruta (§7.4), editable por proyecto
DEFAULT_SENSITIVE = [".env*", "*.pem", "*.key", "migrations/*", "*/migrations/*", ".github/*", "*.lock", "package-lock.json",
                     "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "uv.lock", "Cargo.lock"]
DEFAULT_DEPENDENCY = ["package.json", "requirements*.txt", "pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml",
                      "go.mod", "Gemfile", "*.csproj"]
DEFAULT_CONFIG = ["Dockerfile", "docker-compose*.yml", ".gitlab-ci.yml", "Makefile", "*.config.js", "*.config.ts"]


@dataclass
class Policy:
    max_files: int = 8        # «grande» = más de 8 archivos…
    max_lines: int = 300      # …o más de 300 líneas cambiadas
    sensitive: list[str] = field(default_factory=lambda: list(DEFAULT_SENSITIVE))
    dependency: list[str] = field(default_factory=lambda: list(DEFAULT_DEPENDENCY))
    config: list[str] = field(default_factory=lambda: list(DEFAULT_CONFIG))
    max_auto_subtasks: int = 3  # un plan con más subtareas es «grande»: lo apruebas tú

    @classmethod
    def from_dict(cls, d: dict | None) -> "Policy":
        p = cls()
        for k, v in (d or {}).items():
            if hasattr(p, k):
                setattr(p, k, v)
        return p


@dataclass
class FileChange:
    path: str
    status: str   # A añadido · M modificado · D borrado · R renombrado
    added: int = 0
    deleted: int = 0


@dataclass
class Assessment:
    level: int
    reasons: list[str]

    @property
    def name(self) -> str:
        return LEVEL_NAME[self.level]

    def as_dict(self) -> dict:
        return {"level": self.name, "reasons": self.reasons}


def _match(path: str, patterns: list[str]) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in patterns)


def assess_changes(changes: list[FileChange], policy: Policy | None = None) -> Assessment:
    """Nivel mínimo exigido por las reglas. Sin cambios = N0; cambios normales = N1; lo delicado = N2."""
    policy = policy or Policy()
    if not changes:
        return Assessment(N0, ["sin cambios en archivos"])
    reasons: list[str] = []
    deleted = [c.path for c in changes if c.status == "D"]
    if deleted:
        reasons.append(f"borra archivos: {', '.join(deleted[:5])}")
    for label, patterns in (("archivos sensibles", policy.sensitive), ("dependencias", policy.dependency),
                            ("configuración/CI", policy.config)):
        hit = [c.path for c in changes if _match(c.path, patterns)]
        if hit:
            reasons.append(f"toca {label}: {', '.join(hit[:5])}")
    lines = sum(c.added + c.deleted for c in changes)
    if len(changes) > policy.max_files:
        reasons.append(f"{len(changes)} archivos (> {policy.max_files})")
    if lines > policy.max_lines:
        reasons.append(f"{lines} líneas cambiadas (> {policy.max_lines})")
    if reasons:
        return Assessment(N2, reasons)
    return Assessment(N1, [f"{len(changes)} archivo(s), {lines} línea(s) dentro de umbral"])


def combine(*levels: int) -> int:
    return max(levels) if levels else N0


def parse_numstat(numstat: str, name_status: str) -> list[FileChange]:
    """Une `git diff --numstat` y `git diff --name-status` (mismo rango) en FileChange."""
    status: dict[str, str] = {}
    for line in name_status.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            status[parts[-1]] = parts[0][0]
    out = []
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, d, path = parts[0], parts[1], parts[-1]
        if " => " in path:  # renombrado: numstat muestra «viejo => nuevo»
            path = path.split(" => ")[-1].replace("}", "").strip()
        out.append(FileChange(path, status.get(path, "M"), int(a) if a.isdigit() else 0, int(d) if d.isdigit() else 0))
    return out
