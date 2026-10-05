"""Codex no interactivo: `codex exec --json`.

Aprendido de majiayu000/localharness: los items llegan en snake_case y camelCase; hay eventos `warning`,
`error`, `turn.failed`; un item de tipo `error` es un fallo; los tipos de item desconocidos se
exponen (kind `unknown`) en vez de ignorarse; Codex cuenta el caché dentro de `input_tokens`.
"""

from localharness.adapters.base import Adapter, RunSpec
from localharness.events import Event


def _toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _get(d: dict, *keys, default=None):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


class CodexAdapter(Adapter):
    name = "codex"

    def build_command(self, spec: RunSpec) -> list[str]:
        cmd = [self.binary, "exec", "--json", "-C", spec.cwd,
               "--sandbox", "read-only" if spec.read_only else "workspace-write",
               "-c", f'approval_policy="{_toml(spec.approval_policy)}"']
        if spec.model:
            cmd += ["--model", spec.model]
        cmd += spec.extra_args
        if spec.session_id:  # PENDIENTE verificar el orden exacto de `resume` con una ejecución real
            cmd += ["resume", spec.session_id]
        return cmd + ["-"]  # `-` = leer el prompt de stdin (PENDIENTE verificar con la CLI real)

    def parse_line(self, obj: dict) -> list[Event]:
        t = obj.get("type")
        if t == "thread.started":
            return [Event("session", data={"session_id": _get(obj, "thread_id", "threadId")})]
        if t in ("turn.started", "item.started"):
            return []
        if t == "warning":
            return [Event("warning", text=str(_get(obj, "message", "warning", default="")))]
        if t in ("error", "turn.failed"):
            err = obj.get("error")
            msg = _get(obj, "message") or (err.get("message") if isinstance(err, dict) else err) or t
            return [Event("error", text=str(msg))]
        if t == "turn.completed":
            u = obj.get("usage") or {}
            cached = _get(u, "cached_input_tokens", "cachedInputTokens", default=0)
            inp = _get(u, "input_tokens", "inputTokens")
            return [Event("usage", data={"usage": u, "input_uncached": (inp - cached) if inp is not None else None})]
        if t == "item.completed":
            item = obj.get("item") or {}
            kind = item.get("type")
            if kind == "error":
                return [Event("error", text=str(_get(item, "message", default="error desconocido")))]
            if kind in ("agent_message", "agentMessage"):
                return [Event("text", text=item.get("text", ""))]
            if kind in ("command_execution", "commandExecution"):
                return [Event("tool", text=item.get("command", ""), data={
                    "exit_code": _get(item, "exit_code", "exitCode"),
                    "output": _get(item, "aggregated_output", "aggregatedOutput", default="")})]
            if kind in ("file_change", "fileChange", "mcp_tool_call", "mcpToolCall", "web_search", "webSearch"):
                return [Event("tool", text=_get(item, "name", "tool", default=kind), data={"item": item})]
            if kind == "reasoning":
                return []
            return [Event("unknown", text=str(kind or "item_sin_tipo"))]
        return [Event("unknown", text=f"codex_event:{t}")]
