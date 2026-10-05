"""Difusión de eventos en vivo a los clientes SSE (copiado de Arena LLM `server/hub.py`)."""

import asyncio
import json
from typing import Any


class EventHub:
    def __init__(self, queue_size: int = 100):
        self.queue_size = queue_size
        self._subscribers: set[asyncio.Queue[tuple[str, str]]] = set()

    def subscribe(self) -> asyncio.Queue[tuple[str, str]]:
        q: asyncio.Queue[tuple[str, str]] = asyncio.Queue(self.queue_size)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[tuple[str, str]]) -> None:
        self._subscribers.discard(q)

    @property
    def subscribers(self) -> int:
        return len(self._subscribers)

    def publish(self, event: str, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        for q in list(self._subscribers):
            if q.full():  # cliente lento: se descarta lo más viejo, nunca se bloquea el sondeo
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait((event, payload))


def sse_format(event: str, payload: str) -> str:
    return f"event: {event}\ndata: {payload}\n\n"
