"""Claude Code no interactivo: `claude -p --output-format stream-json --verbose`, prompt por stdin.

Aprendido del código de otros orquestadores (majiayu000/harness, parallel-code, vibe-kanban):
- sin nadie que apruebe permisos, `acceptEdits` deja colgado/denegado cualquier Bash. Se usa
  `--permission-mode bypassPermissions` + lista blanca de herramientas;
- un fallo llega como evento `result` con `is_error` o subtype `error_*` y código de salida 0.

Verificado con la CLI real (2.1.287, Windows, 05/10/2026; fixtures en tests/fixtures_reales/):
- el prompt por stdin funciona con `-p` sin argumento;
- `--tools` es el límite DURO (el `init` solo lista esas herramientas y no puede escribir con solo Read);
- sin aislar, la CLI hija hereda MCP, plugins, hooks y CLAUDE.md del usuario: ~245k tokens de contexto
  para responder «ok». Con `--safe-mode --strict-mcp-config` bajan a ~4,6k (144× menos). `--bare` no
  sirve: prohíbe el login OAuth de la suscripción;
- `rate_limit_event` informa del uso del plan (ventanas de 5 h y 7 días);
- `--json-schema` devuelve la salida validada en `result.structured_output` (fixture claude_json_schema.jsonl).
"""

import json

from localharness.adapters.base import Adapter, RunSpec
from localharness.events import Event

READ_TOOLS = ["Read", "Glob", "Grep"]
WRITE_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write"]  # Bash/PowerShell solo si se conceden explícitamente
SUBAGENT_TOOL = "Agent"  # antes «Task»; con config.subagents el agente puede lanzar subagentes (gasta más plan)


def _names(tools: list[str]) -> list[str]:
    seen: list[str] = []
    for t in tools:
        n = t.split("(")[0]
        if n not in seen:
            seen.append(n)
    return seen


class ClaudeAdapter(Adapter):
    name = "claude"
    # En modo `-p` una ANTHROPIC_API_KEY presente se usa SIEMPRE (docs de autenticación) y cobraría por
    # tokens. Para usar la suscripción hay que quitarla del entorno de la CLI hija.
    env_remove = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

    def __init__(self, binary: str | None = None, allow_api_key: bool = False, isolated: bool = True):
        super().__init__(binary)
        if allow_api_key:
            self.env_remove = ()
        self.isolated = isolated  # sin MCP/plugins/hooks/CLAUDE.md del usuario: el contexto lo pone LocalHarness

    def build_command(self, spec: RunSpec) -> list[str]:
        cmd = [self.binary, "-p", "--output-format", "stream-json", "--verbose"]
        if self.isolated and spec.mcp_config:
            # --safe-mode desactiva TAMBIÉN los servidores de --mcp-config (verificado 06/10/2026: init sin
            # mcp__local__*). Con MCP se aísla de otra forma: sin settings (hooks/plugins del usuario), sin skills y,
            # vía env CLAUDE_CODE_DISABLE_CLAUDE_MDS=1, sin CLAUDE.md. Contexto medido: ~11,6k tokens (4,6k con safe-mode).
            cmd += ["--setting-sources", "", "--disable-slash-commands", "--strict-mcp-config"]
        elif self.isolated:
            cmd += ["--safe-mode", "--strict-mcp-config"]
        if spec.model:
            cmd += ["--model", spec.model]
        if spec.max_turns:
            cmd += ["--max-turns", str(spec.max_turns)]
        if spec.max_budget_usd:
            cmd += ["--max-budget-usd", str(spec.max_budget_usd)]
        if spec.session_id:
            cmd += ["--resume", spec.session_id]
        if spec.json_schema:  # la CLI añade su herramienta StructuredOutput (gasta 1 turno)
            cmd += ["--json-schema", json.dumps(spec.json_schema, ensure_ascii=False, separators=(",", ":"))]
        tools = [*(spec.allowed_tools or (READ_TOOLS if spec.read_only else WRITE_TOOLS)), *spec.extra_tools]
        if spec.mcp_config:  # con --strict-mcp-config solo se cargan los servidores de este archivo
            cmd += ["--mcp-config", spec.mcp_config]
        # --tools limita lo disponible (verificado); --allowedTools auto-aprueba patrones como Bash(git status).
        # Las herramientas MCP no son «built-in»: van solo en --allowedTools.
        cmd += ["--permission-mode", "bypassPermissions",
                "--tools", ",".join(_names(tools)), "--allowedTools", ",".join([*tools, *spec.mcp_tools])]
        return cmd + spec.extra_args

    def parse_line(self, obj: dict) -> list[Event]:
        t = obj.get("type")
        if t == "system" and obj.get("subtype") == "init":
            return [Event("session", data={"session_id": obj.get("session_id"), "model": obj.get("model"),
                                           "tools": obj.get("tools"), "api_key_source": obj.get("apiKeySource")})]
        if t == "assistant":
            msg = obj.get("message")
            if isinstance(msg, str):
                return [Event("text", text=msg)]
            out = []
            for block in (msg or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    out.append(Event("text", text=block["text"]))
                elif block.get("type") == "tool_use":
                    out.append(Event("tool", text=block.get("name", ""), data={"input": block.get("input")}))
            return out
        if t == "rate_limit_event":
            info = obj.get("rate_limit_info") or {}
            windows = info.get("unifiedWindows") or {}
            return [Event("limit", text=str(info.get("status") or ""), data={
                "status": info.get("status"), "type": info.get("rateLimitType"),
                "utilization": info.get("utilization"), "resets_at": info.get("resetsAt"),
                "five_hour": (windows.get("five_hour") or {}).get("utilization"),
                "seven_day": (windows.get("seven_day") or {}).get("utilization"),
                "overage": info.get("isUsingOverage")})]
        if t == "result":
            subtype = obj.get("subtype") or ""
            failed = obj.get("is_error") is True or subtype.startswith("error")
            usage = Event("usage", data={"cost_usd": obj.get("total_cost_usd"), "turns": obj.get("num_turns"),
                                         "usage": obj.get("usage"),
                                         "permission_denials": obj.get("permission_denials") or []})
            if not failed:
                return [usage, Event("result", text=obj.get("result") or "",
                                     data={"session_id": obj.get("session_id"),
                                           "structured": obj.get("structured_output")})]
            detail = obj.get("result") or "; ".join(map(str, obj.get("errors") or [])) or obj.get("error") or ""
            return [usage, Event("error", text=f"claude falló ({subtype or 'desconocido'}): {detail}".rstrip(": "))]
        if t == "error":
            return [Event("error", text=str(obj.get("error") or "error desconocido"))]
        return []  # system hook_*, stream_event, user/tool_result, thinking: ignorados


def login_method(binary: str = "claude") -> str | None:
    """`claude auth status` -> authMethod ('claude.ai' = suscripción; 'api_key' = pago por tokens).
    Solo se lee ese campo: el resto (email, organización) no se guarda."""
    import json, subprocess
    from localharness.binaries import resolve
    try:
        p = subprocess.run([*resolve(binary), "auth", "status"], capture_output=True, text=True, timeout=30)
        return json.loads(p.stdout).get("authMethod")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
