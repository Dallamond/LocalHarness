"""Contrato de un proveedor: construir el comando y traducir su salida JSONL a Event.

Un agente es una *configuración* (proveedor + modelo + límites), no código nuevo.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from localharness.events import Event


class AdapterError(Exception):
    pass


@dataclass
class RunSpec:
    prompt: str
    cwd: str
    model: str | None = None
    max_turns: int | None = None
    read_only: bool = False          # planificar/revisar sin tocar archivos
    allowed_tools: list[str] | None = None   # Claude: lista blanca; None = valores por defecto
    max_budget_usd: float | None = None      # Claude: tope de gasto por tarea
    approval_policy: str = "never"           # Codex: nadie contesta preguntas en modo automático
    session_id: str | None = None    # para reanudar
    extra_args: list[str] = field(default_factory=list)


class Adapter(ABC):
    name = "base"
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
