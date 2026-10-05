from localharness.adapters.base import Adapter, AdapterError
from localharness.adapters.claude import ClaudeAdapter
from localharness.adapters.codex import CodexAdapter

ADAPTERS: dict[str, type[Adapter]] = {"claude": ClaudeAdapter, "codex": CodexAdapter}


def get_adapter(name: str, **kw) -> Adapter:
    try:
        return ADAPTERS[name](**kw)
    except KeyError:
        raise AdapterError(f"Proveedor desconocido: {name}") from None
