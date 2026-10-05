"""Eventos normalizados: lo único que la GUI y la base de datos conocen, sea cual sea la CLI."""

from dataclasses import dataclass, field
from typing import Any

# kind: session | text | tool | usage | result | error | raw
@dataclass
class Event:
    kind: str
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "text": self.text, "data": self.data}
