"""Contrato de un proveedor: construir el comando y traducir su salida JSONL a Event.

Un agente es una *configuración* (proveedor + modelo + límites), no código nuevo.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from localharness.events import Event


class AdapterError(Exception):
    pass


THINKING_LEVELS = ("apagado", "normal", "profundo")


@dataclass
class RunSpec:
    prompt: str
    cwd: str
    model: str | None = None
    max_turns: int | None = None
    read_only: bool = False          # planificar/revisar sin tocar archivos
    allowed_tools: list[str] | None = None   # Claude: lista blanca; None = valores por defecto
    extra_tools: list[str] = field(default_factory=list)  # Claude: añadidas a la lista (p. ej. Agent = subagentes)
    mcp_config: str | None = None    # Claude: archivo JSON de servidores MCP (p. ej. delegar en el modelo local)
    mcp_tools: list[str] = field(default_factory=list)    # sus herramientas (mcp__servidor__nombre), auto-aprobadas
    env: dict[str, str] = field(default_factory=dict)     # variables extra para el proceso hijo
    max_budget_usd: float | None = None      # Claude: tope de gasto por tarea
    approval_policy: str = "never"           # Codex: nadie contesta preguntas en modo automático
    session_id: str | None = None    # para reanudar
    json_schema: dict | None = None  # Claude: salida estructurada validada (llega en result.structured_output)
    extra_args: list[str] = field(default_factory=list)
    thinking: str | None = None      # apagado | normal | profundo (None = normal: lo que haga el modelo por defecto)
    # agente local: pregunta al Director del plan (reanuda su sesión) → (respuesta, coste en $). None = sin Director
    ask_director: Callable[[str], Awaitable[tuple[str, float]]] | None = None


class Adapter(ABC):
    name = "base"
    is_cli = True     # False: el adaptador ejecuta por sí mismo (execute), p. ej. un servidor HTTP local
    can_write = True  # False: no puede modificar archivos (no se le asignan subtareas de implementación)
    env_remove: tuple[str, ...] = ()  # variables que NO deben llegar a la CLI hija

    def __init__(self, binary: str | None = None):
        self.binary = binary or self.name

    @abstractmethod
    def build_command(self, spec: RunSpec) -> list[str]: ...

    def stdin_text(self, spec: RunSpec) -> str | None:
        """El prompt va por stdin: sin límite de 32k de la línea de órdenes de Windows ni problemas de comillas."""
        return spec.prompt

    @abstractmethod
    def parse_line(self, obj: dict) -> list[Event]: ...

    def parse(self, line: str) -> list[Event]:
        line = line.strip()
        if not line:
            return []
        try:
            obj = json.loads(line)
        except ValueError:
            return [Event("raw", text=line)]
        if not isinstance(obj, dict):
            return [Event("raw", text=line)]
        return self.parse_line(obj)
