"""Proveedor `local` (M4): un llama-server (llama.cpp) por su API compatible con OpenAI. Sin coste de plan.

No es un agente con herramientas: no lee ni escribe archivos. Sirve para tareas acotadas en las que todo el
contexto va en el prompt: planificar (Director, con un resumen del repo inyectado) y revisar diffs (jefe técnico).
Por eso `can_write = False`: el Director nunca le asigna subtareas de implementación.

Configuración del agente (`config`): `base_url` (por defecto http://127.0.0.1:8080), `temperature`, `max_tokens`,
`repo_context` (caracteres de contexto del repo a inyectar; 0 = nada), `timeout_s`.
El cliente de streaming sigue el de Arena LLM (`server/runs/llm.py`).
"""

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from localharness.adapters.base import Adapter, AdapterError, RunSpec
from localharness.events import Event

DEFAULT_URL = "http://127.0.0.1:8080"
SPEED_EVERY_S = 1.5  # cada cuánto se emite el evento `speed` (tokens/s en vivo) mientras genera
TEXT_EXT = {".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".js", ".ts", ".vue", ".tsx", ".jsx", ".css",
            ".html", ".rs", ".go", ".java", ".cs", ".sh", ".ps1", ".sql", ".ini", ".cfg"}


class LocalAdapter(Adapter):
    name = "local"
    is_cli = False
    can_write = False

    def __init__(self, binary: str | None = None, base_url: str | None = None, temperature: float = 0.2,
                 max_tokens: int = 4096, repo_context: int = 24_000, api_key: str | None = None, transport=None):
        super().__init__(binary)
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}  # sin clave el servidor la ignora
        self.base_url = (base_url or DEFAULT_URL).rstrip("/").removesuffix("/v1")
        self.temperature, self.max_tokens, self.repo_context = temperature, max_tokens, repo_context
        self.transport = transport  # pruebas: httpx.MockTransport

    def build_command(self, spec: RunSpec) -> list[str]:  # no es una CLI
        return []

    def parse_line(self, obj: dict) -> list[Event]:
        return []

    def payload(self, spec: RunSpec) -> dict:
        system = ("Eres un asistente de programación dentro de un equipo de agentes. No puedes leer ni modificar "
                  "archivos: todo lo que necesitas está en el mensaje. Responde en español, de forma concreta.")
        user = spec.prompt
        if self.repo_context and spec.cwd:
            ctx = repo_context(Path(spec.cwd), self.repo_context)
            if ctx:
                user = f"{user}\n\nCONTEXTO DEL REPOSITORIO (directorio actual):\n{ctx}"
        body: dict = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                      "temperature": self.temperature, "max_tokens": self.max_tokens}
        if spec.json_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "salida", "strict": True, "schema": spec.json_schema}}
        return body

    async def execute(self, spec: RunSpec, on_event: Callable[[Event], None], timeout_s: float) -> dict:
        try:
            import httpx
        except ImportError:
            on_event(Event("error", text="El proveedor local necesita httpx: pip install -e .[server]"))
            return _out("failed", 0.0)
        t0 = time.monotonic()
        content, reasoning, buf = [], [], []
        usage: dict = {}
        timings: dict = {}
        finish = None
        async with httpx.AsyncClient(transport=self.transport, headers=self.headers) as client:
            try:
                r = await client.get(self.base_url + "/v1/models", timeout=5)
                served = (r.json().get("data") or [{}])[0].get("id")
            except (httpx.HTTPError, ValueError):
                on_event(Event("error", text=f"No responde llama-server en {self.base_url}. "
                                             "Arráncalo con: python -m localharness llama serve <modelo>"))
                return _out("failed", time.monotonic() - t0)
            # llama-server sirve UN modelo: el que esté arrancado, se llame como se llame el agente
            model = _short(served) or spec.model
            on_event(Event("session", data={"session_id": None, "model": model, "tools": [],
                                            "base_url": self.base_url, "requested": spec.model}))
            if spec.model and served and not _same_model(spec.model, served):
                on_event(Event("warning", text=f"El agente pide «{spec.model}» pero el arrancado es «{model}»: "
                                               "responde el arrancado"))
            body = {**self.payload(spec), "stream": True, "stream_options": {"include_usage": True}}
            tokens, phase, last_tick, t_first = 0, "", time.monotonic(), None
            try:
                async with client.stream("POST", self.base_url + "/v1/chat/completions", json=body,
                                         timeout=timeout_s) as resp:
                    if resp.status_code != 200:
                        raw = (await resp.aread()).decode("utf-8", "replace")
                        on_event(Event("error", text=f"llama-server HTTP {resp.status_code}: {raw[:400]}"))
                        return _out("failed", time.monotonic() - t0)
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except ValueError:
                            continue
                        if "error" in chunk:
                            on_event(Event("error", text=f"llama-server: {chunk['error']}"))
                            return _out("failed", time.monotonic() - t0)
                        usage = chunk.get("usage") or usage
                        timings = chunk.get("timings") or timings
                        for choice in chunk.get("choices") or []:
                            delta = choice.get("delta") or {}
                            if delta.get("reasoning_content") or delta.get("content"):
                                tokens += 1  # llama-server manda un token por trozo
                                if t_first is None:  # la velocidad cuenta desde el primer token, no desde el prompt
                                    t_first = last_tick = time.monotonic()
                                phase = "pensando" if delta.get("reasoning_content") else "escribiendo"
                            if delta.get("reasoning_content"):
                                reasoning.append(delta["reasoning_content"])
                            if delta.get("content"):
                                content.append(delta["content"])
                                buf.append(delta["content"])
                                if not spec.json_schema and "\n\n" in "".join(buf[-2:]):  # un evento por párrafo
                                    on_event(Event("text", text="".join(buf).strip()))
                                    buf.clear()
                            finish = choice.get("finish_reason") or finish
                        tick = time.monotonic()
                        if t_first and tick - last_tick >= SPEED_EVERY_S:
                            last_tick = tick
                            on_event(Event("speed", data={"tps": _rate(tokens, tick - t_first), "tokens": tokens,
                                                          "phase": phase, "model": model}))
            except httpx.TimeoutException:
                on_event(Event("error", text=f"Tiempo agotado ({timeout_s:.0f} s)"))
                return _out("timeout", time.monotonic() - t0)
            except httpx.HTTPError as e:
                on_event(Event("error", text=f"Conexión con llama-server: {type(e).__name__}: {e}"))
                return _out("failed", time.monotonic() - t0)
        text = "".join(content).strip()
        if buf and not spec.json_schema and "".join(buf).strip():
            on_event(Event("text", text="".join(buf).strip()))
        structured = None
        if spec.json_schema:
            structured = _parse_json(text)
            if structured is None:
                on_event(Event("error", text=f"El modelo local no devolvió JSON válido: {text[:300]}"))
            else:
                on_event(Event("text", text=json.dumps(structured, ensure_ascii=False)))
        tps = timings.get("predicted_per_second") or (_rate(tokens, time.monotonic() - t_first) if t_first else None)
        tps = round(tps, 1) if tps else None
        on_event(Event("usage", data={"cost_usd": 0.0, "turns": 1, "usage": usage, "local": True, "model": model,
                                      "tps": tps, "tokens": tokens or None, "finish_reason": finish,
                                      "reasoning_chars": len("".join(reasoning)) or None}))
        if not text and reasoning:  # los modelos que razonan (DeepSeek-R1, Qwen3…) pueden gastarlo todo pensando
            on_event(Event("error", text=f"El modelo se quedó pensando ({tokens} tokens) y no llegó a responder. "
                                         "Sube «Tokens de respuesta» del agente en Ajustes o usa un modelo sin razonamiento."))
            return _out("failed", time.monotonic() - t0, text)
        if finish == "length":
            on_event(Event("warning", text="Respuesta cortada por max_tokens"))
        if spec.json_schema and structured is None:
            return _out("failed", time.monotonic() - t0, text)
        on_event(Event("result", text=text, data={"structured": structured}))
        return _out("done", time.monotonic() - t0, text, structured)


def _rate(tokens: int, seconds: float) -> float | None:
    return round(tokens / seconds, 1) if seconds > 0 else None


def _short(model_id: str | None) -> str | None:
    """llama-server llama al modelo por la ruta del GGUF: se deja el nombre del archivo sin extensión."""
    if not model_id:
        return None
    return Path(model_id.replace("\\", "/")).name.removesuffix(".gguf") or model_id


def _same_model(wanted: str, served: str) -> bool:
    a, b = wanted.lower(), (_short(served) or served).lower()
    return a in b or b in a


def _out(status: str, dur: float, final: str | None = None, structured: dict | None = None) -> dict:
    return {"status": status, "exit_code": 0 if status == "done" else None, "duration_s": dur, "final": final,
            "structured": structured}


def _parse_json(text: str) -> dict | None:
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    if "{" in t and not t.startswith("{"):
        t = t[t.index("{"):]
    try:
        v = json.loads(t)
    except ValueError:
        try:  # texto extra tras el objeto
            v, _ = json.JSONDecoder().raw_decode(t)
        except ValueError:
            return None
    return v if isinstance(v, dict) else None


def repo_context(cwd: Path, budget: int) -> str:
    """Mapa del repo para un modelo sin herramientas: lista de archivos y el contenido de los pequeños."""
    try:
        files = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files"], cwd=cwd, capture_output=True,
                               encoding="utf-8", errors="replace", timeout=20).stdout.split("\n")
    except (OSError, subprocess.TimeoutExpired):
        return ""
    files = [f for f in files if f]
    if not files:
        return ""
    parts = ["Archivos:\n" + "\n".join(files[:400]) + ("\n…" if len(files) > 400 else "")]
    used = len(parts[0])
    for f in sorted(files, key=lambda x: (x.count("/"), len(x))):
        p = cwd / f
        if p.suffix.lower() not in TEXT_EXT or not p.is_file() or p.stat().st_size > 20_000:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        block = f"\n--- {f} ---\n{text}"
        if used + len(block) > budget:
            continue
        parts.append(block)
        used += len(block)
    return "".join(parts)


def config_kwargs(cfg: dict) -> dict:
    keys = ("base_url", "temperature", "max_tokens", "repo_context")
    return {k: cfg[k] for k in keys if k in cfg}


__all__ = ["LocalAdapter", "AdapterError", "repo_context", "config_kwargs"]
