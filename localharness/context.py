"""M5 — skills y memoria del proyecto inyectadas en el prompt (igual para Claude, Codex y modelos locales).

- **Skills**: carpetas con `SKILL.md` (frontmatter `name` y `description`, como las de Claude Code). Se buscan en
  `<LocalHarness>/skills` y en las carpetas de `LOCALHARNESS_SKILL_DIRS` (separadas por `;` en Windows).
- **Memoria**: los `.md` de la carpeta de memoria del proyecto (`projects.memory_dir`). Vive FUERA del worktree, así
  que el agente la lee en su prompt pero no puede reescribirla (la memoria no se escribe sola: decisión de alcance).

La CLI hija de Claude va con `--safe-mode` (sin CLAUDE.md ni skills del usuario): este módulo es la única vía
por la que un agente recibe contexto, y el evento `context` deja registrado exactamente qué se inyectó.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

BUILTIN_SKILLS = Path(__file__).resolve().parent.parent / "skills"
MAX_MEMORY_CHARS = 20_000
MAX_SKILL_CHARS = 30_000


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    body: str

    def summary(self) -> dict:
        return {"name": self.name, "description": self.description, "path": str(self.path), "chars": len(self.body)}


_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def parse_skill(path: Path) -> Skill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    meta: dict[str, str] = {}
    m = _FRONT.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"').strip("'")
        text = text[m.end():]
    name = meta.get("name") or path.parent.name
    return Skill(name, meta.get("description", ""), path, text.strip())


def skill_dirs() -> list[Path]:
    dirs = [BUILTIN_SKILLS]
    env = os.environ.get("LOCALHARNESS_SKILL_DIRS")
    if env:
        dirs += [Path(d) for d in env.split(os.pathsep) if d]
    return [d for d in dirs if d.is_dir()]


def load_skills(dirs: list[Path] | None = None) -> dict[str, Skill]:
    """Catálogo por nombre. Si dos carpetas traen el mismo nombre, gana la primera (las propias)."""
    out: dict[str, Skill] = {}
    for d in dirs if dirs is not None else skill_dirs():
        for f in sorted(d.rglob("SKILL.md")):
            s = parse_skill(f)
            if s and s.name not in out:
                out[s.name] = s
    return out


def load_memory(memory_dir: str | None) -> list[tuple[str, str]]:
    if not memory_dir:
        return []
    d = Path(memory_dir)
    if not d.is_dir():
        return []
    out, used = [], 0
    for f in sorted(d.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if used + len(text) > MAX_MEMORY_CHARS:
            text = text[: max(0, MAX_MEMORY_CHARS - used)] + "\n…(recortado)"
        out.append((f.name, text))
        used += len(text)
        if used >= MAX_MEMORY_CHARS:
            break
    return out


def build_prompt(prompt: str, memory: list[tuple[str, str]], skills: list[Skill]) -> tuple[str, dict]:
    """Prompt final + registro de lo inyectado (para el evento `context`)."""
    parts, info = [], {"memory": [], "skills": [], "chars": 0}
    if memory:
        parts.append("## Memoria del proyecto (solo lectura; decisiones y convenciones a respetar)")
        for name, text in memory:
            parts.append(f"### {name}\n{text}")
            info["memory"].append({"file": name, "chars": len(text)})
    used = 0
    for s in skills:
        body = s.body if used + len(s.body) <= MAX_SKILL_CHARS else s.body[: max(0, MAX_SKILL_CHARS - used)] + "\n…(recortada)"
        if not parts or not any(p.startswith("## Skills") for p in parts):
            parts.append("## Skills (procedimientos a seguir en esta tarea)")
        parts.append(f"### Skill: {s.name}\n{body}")
        info["skills"].append({"name": s.name, "chars": len(body)})
        used += len(body)
    if not parts:
        return prompt, info
    text = "\n\n".join(parts) + "\n\n## Tarea\n" + prompt
    info["chars"] = len(text) - len(prompt)
    return text, info
