"""Proveedor `local_agent`: un modelo local (llama-server) que trabaja como AGENTE con herramientas.

A diferencia de `local` (un solo mensaje con todo el contexto), aquí LocalHarness hace el bucle:
  1. manda a Qwen la tarea + las herramientas;
  2. Qwen pide una herramienta (`tool_calls`);
  3. LocalHarness la ejecuta, confinada al worktree, y le devuelve el resultado;
  4. se repite hasta `terminar` o un tope (turnos, tiempo).
Qwen nunca toca nada directamente: cada herramienta la ejecuta y comprueba LocalHarness, y cada una es un evento
`tool` como los de Claude (la GUI lo muestra igual).

Herramientas v1 (pocas a propósito; los modelos pequeños fallan más cuantas más hay): leer_archivo, listar,
buscar_texto, escribir_archivo (si puede escribir), buscar_web, leer_url, avisar_progreso, terminar.
Pendiente (docs/DISENO-OFICINA.md §4b): ejecutar (lista blanca), preguntar_director.

Fiabilidad con modelos de 7–14B:
- `tool_mode: native` (por defecto) usa `tools` de la API; `json` no manda `tools` y obliga a responder con un
  JSON {"herramienta", "argumentos"} (`response_format`) para modelos sin plantilla de herramientas.
- Llamadas mal formadas: se le devuelve el error y reintenta. Sin herramienta: se le recuerda una vez.
- La misma llamada 3 veces seguidas = bucle: se para.
- Salidas de herramientas recortadas y, si la conversación crece, los resultados viejos se resumen.

Configuración (`config` del agente): las de `local` (base_url, temperature, max_tokens) más `max_turns`
(por defecto 25), `tool_mode`, `max_tool_chars` (por defecto 6000), `max_context_chars` (por defecto 60000),
`web` (True/False).
"""

import json
import time
from collections.abc import Callable
from pathlib import Path

from localharness.adapters.base import RunSpec
from localharness.adapters.local import LocalAdapter, _out, _short
from localharness.events import Event
from localharness.mcp_local import SEARCH_URL, _http_get, page_text, parse_ddg

MAX_SAME_CALL = 3
MAX_BAD_REPLIES = 2
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".mypy_cache"}


def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": props,
                                                            "required": required}}}


S = {"type": "string"}
TOOLS = {
    "leer_archivo": _fn("leer_archivo", "Lee un archivo del repositorio (ruta relativa).", {"ruta": S}, ["ruta"]),
    "listar": _fn("listar", "Lista archivos y carpetas de una carpeta del repositorio ('.' = raíz).",
                  {"carpeta": S}, []),
    "buscar_texto": _fn("buscar_texto", "Busca un texto en los archivos del repositorio; devuelve ruta:línea.",
                        {"texto": S, "carpeta": S}, ["texto"]),
    "escribir_archivo": _fn("escribir_archivo", "Crea o reescribe ENTERO un archivo del repositorio.",
                            {"ruta": S, "contenido": S}, ["ruta", "contenido"]),
    "buscar_web": _fn("buscar_web", "Busca en internet. Devuelve títulos, URL y resúmenes.", {"consulta": S},
                      ["consulta"]),
    "leer_url": _fn("leer_url", "Lee el texto de una página web (http/https).", {"url": S}, ["url"]),
    "avisar_progreso": _fn("avisar_progreso", "Cuenta en una frase corta qué estás haciendo (lo ve el humano).",
                           {"texto": S}, ["texto"]),
    "terminar": _fn("terminar", "Termina la tarea. `resumen`: qué hiciste o tu respuesta final. "
                                "`comprobacion`: cómo lo comprobaste.", {"resumen": S, "comprobacion": S},
                    ["resumen"]),
}

SYSTEM = """Eres un agente de programación que trabaja SOLO, dentro de un equipo dirigido por un Director.
Trabajas en un repositorio (rutas relativas a su raíz) usando herramientas: llámalas de una en una, mira el
resultado y decide el siguiente paso. No inventes el contenido de archivos ni de páginas: léelos.
Cuando hayas acabado, llama a `terminar` con un resumen y cómo lo comprobaste. Responde en español."""

JSON_MODE = """
FORMATO OBLIGATORIO: responde SIEMPRE con un único objeto JSON {{"herramienta": "<nombre>", "argumentos": {{...}}}}.
Herramientas disponibles:
{tools}"""


class ToolFail(Exception):
    pass


class LocalAgentAdapter(LocalAdapter):
    name = "local_agent"
    can_write = True  # escribe en su worktree con `escribir_archivo`

    def __init__(self, binary: str | None = None, base_url: str | None = None, temperature: float = 0.2,
                 max_tokens: int = 4096, api_key: str | None = None, transport=None, http_get=None,
                 tool_mode: str = "native", max_tool_chars: int = 6000, max_context_chars: int = 60_000,
                 web: bool = True, **_):
        super().__init__(binary, base_url, temperature, max_tokens, 0, api_key, transport)
        self.tool_mode = tool_mode if tool_mode in ("native", "json") else "native"
        self.max_tool_chars, self.max_context_chars, self.web = max_tool_chars, max_context_chars, web
        self.http_get = http_get or _http_get  # pruebas: sin red de verdad

    def tool_names(self, read_only: bool) -> list[str]:
        names = list(TOOLS)
        if read_only:
            names.remove("escribir_archivo")
        if not self.web:
            names = [n for n in names if n not in ("buscar_web", "leer_url")]
        return names

    def body(self, messages: list[dict], names: list[str]) -> dict:
        b: dict = {"messages": messages, "temperature": self.temperature, "max_tokens": self.max_tokens}
        if self.tool_mode == "native":
            b["tools"] = [TOOLS[n] for n in names]
        else:
            b["response_format"] = {"type": "json_schema", "json_schema": {"name": "llamada", "strict": True, "schema": {
                "type": "object", "properties": {"herramienta": {"type": "string", "enum": names},
                                                 "argumentos": {"type": "object"}},
                "required": ["herramienta", "argumentos"]}}}
        return b

    async def execute(self, spec: RunSpec, on_event: Callable[[Event], None], timeout_s: float) -> dict:
        try:
            import httpx
        except ImportError:
            on_event(Event("error", text="El agente local necesita httpx: pip install -e .[server]"))
            return _out("failed", 0.0)
        t0 = time.monotonic()
        root = Path(spec.cwd).resolve()
        names = self.tool_names(spec.read_only)
        system = SYSTEM
        if self.tool_mode == "json":
            system += JSON_MODE.format(tools="\n".join(
                f"- {n}({', '.join(TOOLS[n]['function']['parameters']['properties'])}): "
                f"{TOOLS[n]['function']['description']}" for n in names))
        messages = [{"role": "system", "content": system}, {"role": "user", "content": spec.prompt}]
        max_turns = spec.max_turns or 25
        totals = {"prompt_tokens": 0, "completion_tokens": 0}
        last_calls: list[str] = []
        bad, turns, model, tps = 0, 0, spec.model, None
        async with httpx.AsyncClient(transport=self.transport, headers=self.headers) as client:
            try:
                r = await client.get(self.base_url + "/v1/models", timeout=5)
                model = _short((r.json().get("data") or [{}])[0].get("id")) or spec.model
            except (httpx.HTTPError, ValueError):
                on_event(Event("error", text=f"No responde llama-server en {self.base_url}. Arráncalo en Modelos locales."))
                return _out("failed", time.monotonic() - t0)
            on_event(Event("session", data={"session_id": None, "model": model, "tools": names, "agentic": True,
                                            "tool_mode": self.tool_mode, "base_url": self.base_url}))

            def finish(status: str, text: str | None) -> dict:
                on_event(Event("usage", data={"cost_usd": 0.0, "turns": turns, "usage": totals, "local": True,
                                              "model": model, "tps": tps, "agentic": True}))
                if status == "done":
                    on_event(Event("result", text=text or "", data={"structured": None}))
                return _out(status, time.monotonic() - t0, text)

            while turns < max_turns:
                left = timeout_s - (time.monotonic() - t0)
                if left <= 0:
                    on_event(Event("error", text=f"Tiempo agotado ({timeout_s:.0f} s)"))
                    return finish("timeout", None)
                turns += 1
                self.compact(messages)
                try:
                    resp = await client.post(self.base_url + "/v1/chat/completions", json=self.body(messages, names),
                                             timeout=left)
                except httpx.TimeoutException:
                    on_event(Event("error", text=f"Tiempo agotado ({timeout_s:.0f} s)"))
                    return finish("timeout", None)
                except httpx.HTTPError as e:
                    on_event(Event("error", text=f"Conexión con llama-server: {type(e).__name__}: {e}"))
                    return finish("failed", None)
                if resp.status_code != 200:
                    on_event(Event("error", text=f"llama-server HTTP {resp.status_code}: {resp.text[:400]}"))
                    return finish("failed", None)
                data = resp.json()
                usage, timings = data.get("usage") or {}, data.get("timings") or {}
                for k in totals:
                    totals[k] += usage.get(k) or 0
                if timings.get("predicted_per_second"):
                    tps = round(timings["predicted_per_second"], 1)
                on_event(Event("speed", data={"tps": tps, "tokens": totals["completion_tokens"], "turn": turns,
                                              "phase": "trabajando", "model": model}))
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                if msg.get("reasoning_content"):
                    on_event(Event("thinking", text=msg["reasoning_content"][-2000:]))
                calls = self.calls(msg)
                if calls is None:  # no pidió ninguna herramienta
                    text = (msg.get("content") or "").strip()
                    if bad < MAX_BAD_REPLIES - 1:
                        bad += 1
                        messages.append({"role": "assistant", "content": text})
                        messages.append({"role": "user", "content": "Usa una herramienta. Si ya has acabado, llama a "
                                                                    "`terminar` con tu resumen."})
                        continue
                    if text:  # se acepta su texto como respuesta final
                        on_event(Event("warning", text="El modelo respondió sin llamar a `terminar`: se toma su texto"))
                        return finish("done", text)
                    on_event(Event("error", text="El modelo local no usa las herramientas (prueba tool_mode «json» "
                                                 "o Qwen3.5-9B)"))
                    return finish("failed", None)
                bad = 0
                messages.append(self.assistant_message(msg, calls))
                for call in calls:
                    key = f"{call['name']}:{json.dumps(call['args'], sort_keys=True, ensure_ascii=False)}"
                    last_calls = (last_calls + [key])[-MAX_SAME_CALL:]
                    if len(last_calls) == MAX_SAME_CALL and len(set(last_calls)) == 1:
                        on_event(Event("error", text=f"El agente repite la misma llamada ({call['name']}): parado"))
                        return finish("failed", None)
                    if call["name"] == "terminar":
                        a = call["args"]
                        text = str(a.get("resumen") or "").strip() or "(sin resumen)"
                        if a.get("comprobacion"):
                            text += f"\n\nComprobación: {a['comprobacion']}"
                        return finish("done", text)
                    on_event(Event("tool", text=call["name"], data={"input": call["args"]}))
                    try:
                        if call.get("error"):
                            raise ToolFail(call["error"])
                        if call["name"] not in names:
                            raise ToolFail(f"herramienta desconocida: {call['name']} (hay: {', '.join(names)})")
                        out = self.run_tool(root, call["name"], call["args"], on_event)
                    except ToolFail as e:
                        out = f"ERROR: {e}"
                    except Exception as e:  # noqa: BLE001 — un fallo de herramienta no tumba el bucle
                        out = f"ERROR: {type(e).__name__}: {e}"
                    if len(out) > self.max_tool_chars:
                        out = out[: self.max_tool_chars] + f"\n[… recortado, {len(out)} caracteres en total]"
                    messages.append(self.tool_message(call, out))
            on_event(Event("error", text=f"Tope de turnos ({max_turns}) sin terminar"))
            return finish("failed", None)

    # --- protocolo de llamadas (nativo o JSON)
    def calls(self, msg: dict) -> list[dict] | None:
        if self.tool_mode == "native":
            raw = msg.get("tool_calls") or []
            if not raw:
                parsed = _json_call(msg.get("content") or "")  # algunos modelos lo escriben en el texto
                return [parsed] if parsed else None
            out = []
            for i, tc in enumerate(raw):
                fn = tc.get("function") or {}
                call = {"id": tc.get("id") or f"call_{i}", "name": fn.get("name") or "", "args": {}}
                try:
                    args = fn.get("arguments") or "{}"
                    call["args"] = json.loads(args) if isinstance(args, str) else dict(args)
                    if not isinstance(call["args"], dict):
                        raise ValueError
                except (ValueError, TypeError):
                    call["error"] = "los argumentos no son un JSON válido; repite la llamada bien formada"
                out.append(call)
            return out
        parsed = _json_call(msg.get("content") or "")
        return [parsed] if parsed else None

    def assistant_message(self, msg: dict, calls: list[dict]) -> dict:
        if self.tool_mode == "native" and msg.get("tool_calls"):
            return {"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg["tool_calls"]}
        return {"role": "assistant", "content": msg.get("content") or json.dumps(
            {"herramienta": calls[0]["name"], "argumentos": calls[0]["args"]}, ensure_ascii=False)}

    def tool_message(self, call: dict, out: str) -> dict:
        if self.tool_mode == "native" and not call.get("from_text"):
            return {"role": "tool", "tool_call_id": call["id"], "content": out}
        return {"role": "user", "content": f"RESULTADO DE {call['name']}:\n{out}"}

    def compact(self, messages: list[dict]) -> None:
        """Si la conversación no cabe, los resultados de herramientas más viejos se sustituyen por un aviso."""
        size = sum(len(m.get("content") or "") for m in messages)
        for m in messages[2:-4]:
            if size <= self.max_context_chars:
                break
            c = m.get("content") or ""
            if (m["role"] == "tool" or c.startswith("RESULTADO DE")) and len(c) > 200:
                m["content"] = c[:200] + "\n[… resultado antiguo recortado para ahorrar contexto]"
                size -= len(c) - len(m["content"])

    # --- herramientas (todas confinadas al worktree)
    def run_tool(self, root: Path, name: str, a: dict, on_event: Callable[[Event], None]) -> str:
        if name == "leer_archivo":
            p = safe(root, a.get("ruta"))
            if not p.is_file():
                raise ToolFail(f"no existe el archivo {a.get('ruta')}")
            return p.read_text(encoding="utf-8", errors="replace")
        if name == "listar":
            p = safe(root, a.get("carpeta") or ".")
            if not p.is_dir():
                raise ToolFail(f"no existe la carpeta {a.get('carpeta')}")
            items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            return "\n".join(f"{x.name}/" if x.is_dir() else x.name for x in items if x.name not in SKIP_DIRS) or "(vacía)"
        if name == "buscar_texto":
            needle = str(a.get("texto") or "")
            if not needle:
                raise ToolFail("falta `texto`")
            return grep(safe(root, a.get("carpeta") or "."), root, needle)
        if name == "escribir_archivo":
            p = safe(root, a.get("ruta"))
            content = str(a.get("contenido") or "")
            existed = p.is_file()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(content if content.endswith("\n") else content + "\n")
            return f"{'Reescrito' if existed else 'Creado'} {a.get('ruta')} ({content.count(chr(10)) + 1} líneas)"
        if name == "buscar_web":
            q = str(a.get("consulta") or "").strip()
            if not q:
                raise ToolFail("falta `consulta`")
            results = parse_ddg(self.http_get(SEARCH_URL, {"q": q}))[:8]
            if not results:
                return "Sin resultados."
            return "\n\n".join(f"[{i}] {r['title']}\n{r['url']}\n{r['snippet']}" for i, r in enumerate(results, 1))
        if name == "leer_url":
            url = str(a.get("url") or "")
            if not url.startswith(("http://", "https://")):
                raise ToolFail("la URL debe empezar por http:// o https://")
            return page_text(self.http_get(url, None)) or "(página sin texto legible)"
        if name == "avisar_progreso":
            on_event(Event("progress", text=str(a.get("texto") or "")[:300]))
            return "ok"
        raise ToolFail(f"herramienta desconocida: {name}")


def safe(root: Path, rel) -> Path:
    if not isinstance(rel, str) or not rel.strip():
        raise ToolFail("falta la ruta")
    p = (root / rel).resolve()
    if not p.is_relative_to(root):
        raise ToolFail(f"{rel} está fuera del repositorio")
    if ".git" in p.relative_to(root).parts:
        raise ToolFail("no se toca .git")
    return p


def grep(base: Path, root: Path, needle: str, limit: int = 60) -> str:
    hits, low = [], needle.lower()
    for p in sorted(base.rglob("*")):
        if len(hits) >= limit:
            break
        if not p.is_file() or SKIP_DIRS.intersection(p.relative_to(root).parts) or p.stat().st_size > 1_000_000:
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, 1):
            if low in line.lower():
                hits.append(f"{p.relative_to(root).as_posix()}:{i}: {line.strip()[:200]}")
                if len(hits) >= limit:
                    break
    return "\n".join(hits) or "Sin coincidencias."


def _json_call(text: str) -> dict | None:
    """{"herramienta": ..., "argumentos": {...}} (o name/arguments) escrito como texto."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if "{" not in t:
        return None
    try:
        v, _ = json.JSONDecoder().raw_decode(t[t.index("{"):])
    except ValueError:
        return None
    if not isinstance(v, dict):
        return None
    name = v.get("herramienta") or v.get("name") or v.get("tool")
    args = v.get("argumentos") or v.get("arguments") or v.get("args") or {}
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    return {"id": "call_texto", "name": name, "args": args, "from_text": True}
