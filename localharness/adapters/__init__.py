from localharness.adapters.base import Adapter, AdapterError
from localharness.adapters.claude import ClaudeAdapter
from localharness.adapters.codex import CodexAdapter
from localharness.adapters.local import LocalAdapter
from localharness.adapters.local_agent import LocalAgentAdapter
from localharness.adapters.local_boss import LocalBossAdapter

ADAPTERS: dict[str, type[Adapter]] = {"claude": ClaudeAdapter, "codex": CodexAdapter, "local": LocalAdapter,
                                    "local_agent": LocalAgentAdapter, "local_boss": LocalBossAdapter}


def get_adapter(name: str, **kw) -> Adapter:
    try:
        return ADAPTERS[name](**kw)
    except KeyError:
        raise AdapterError(f"Proveedor desconocido: {name}") from None
