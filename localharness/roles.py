"""Objetivo 5 — catálogo de roles: plantillas de agente en archivos `roles/*.md` (editables, como las skills).

Cada rol es un `.md` con frontmatter (proveedor, modelo, límites, skills…) y un cuerpo con las instrucciones del
rol. Al arrancar el servidor (y antes de planificar) los roles se SINCRONIZAN como agentes normales: así el
Director los ve en su lista, la GUI los muestra en el equipo y no hay que crearlos a mano.

- El agente de un rol lleva `config.from_role`: el archivo manda y se reescribe en cada sincronización (cambiar el
  rol = editar su archivo). Un agente creado a mano con el mismo nombre NO se toca (se avisa).
- Las instrucciones del rol van en `config.instructions` y se añaden al prompt de cada tarea del agente.

LOCALHARNESS_ROLES_DIR cambia la carpeta (vacía = sin roles; las pruebas la vacían para no mezclarlos).

Claves del frontmatter: name, description, provider, model, role, read_only, max_turns, max_budget_usd,
delegate_local, subagents, skills ([a, b]), tool_mode, web, timeout_s.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from localharness.context import _FRONT
from localharness.store import Store

BUILTIN_ROLES = Path(__file__).resolve().parent.parent / "roles"
CONFIG_KEYS = ("read_only", "max_turns", "max_budget_usd", "delegate_local", "subagents", "skills", "tool_mode",
               "web", "timeout_s")


@dataclass
class Role:
    name: str
    description: str
    provider: str
    path: Path
    instructions: str = ""
    model: str | None = None
    role: str | None = None
    config: dict = field(default_factory=dict)

    def agent_config(self) -> dict:
        cfg = {k: v for k, v in self.config.items() if v not in (None, [], "")}
        cfg.update(description=self.description, from_role=self.name)
        if self.instructions:
            cfg["instructions"] = self.instructions
        return cfg

    def summary(self) -> dict:
        return {"name": self.name, "description": self.description, "provider": self.provider, "model": self.model,
                "role": self.role, "config": self.config, "path": str(self.path)}


def _value(raw: str):
    v = raw.strip().strip('"').strip("'")
    if raw.strip().startswith("[") and raw.strip().endswith("]"):
        return [x.strip().strip('"').strip("'") for x in raw.strip()[1:-1].split(",") if x.strip()]
    if v.lower() in ("true", "sí", "si", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def parse_role(path: Path) -> Role | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = _FRONT.match(text)
    if not m:
        return None
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            meta[k.strip()] = _value(v)
    provider = meta.get("provider")
    if not isinstance(provider, str) or not provider:
        return None
    return Role(name=str(meta.get("name") or path.stem), description=str(meta.get("description") or ""),
                provider=provider, path=path, instructions=text[m.end():].strip(),
                model=meta.get("model") or None, role=meta.get("role") or None,
                config={k: meta[k] for k in CONFIG_KEYS if k in meta})


def role_dirs() -> list[Path]:
    env = os.environ.get("LOCALHARNESS_ROLES_DIR")
    if env is None:
        return [BUILTIN_ROLES]
    return [Path(d) for d in env.split(os.pathsep) if d]


def load_roles(dirs: list[Path] | None = None) -> dict[str, Role]:
    out: dict[str, Role] = {}
    for d in role_dirs() if dirs is None else dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            r = parse_role(p)
            if r:
                out[r.name] = r
    return out


def sync_roles(store: Store, roles: dict[str, Role] | None = None) -> list[str]:
    """Crea o actualiza un agente por rol. Devuelve un registro legible de lo hecho."""
    from localharness.adapters import ADAPTERS
    log = []
    for r in (load_roles() if roles is None else roles).values():
        if r.provider not in ADAPTERS:
            log.append(f"rol {r.name}: proveedor desconocido {r.provider!r}, ignorado")
            continue
        cfg = r.agent_config()
        a = store.find_agent(r.name)
        if not a:
            store.add_agent(r.name, r.provider, model=r.model, role=r.role, config=cfg)
            log.append(f"rol {r.name}: agente creado")
        elif json.loads(a["config"] or "{}").get("from_role") == r.name:
            if (a["provider"], a["model"], a["role"], json.loads(a["config"] or "{}")) != (r.provider, r.model, r.role, cfg):
                store.update_agent(a["id"], provider=r.provider, model=r.model, role=r.role, config=cfg)
                log.append(f"rol {r.name}: agente actualizado desde {r.path.name}")
        else:
            log.append(f"rol {r.name}: ya hay un agente propio con ese nombre, no se toca")
    return log
