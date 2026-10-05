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
TEXT_EXT = {".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".js", ".ts", ".vue", ".tsx", ".jsx", ".css",
            ".html", ".rs", ".go", ".java", ".cs", ".sh", ".ps1", ".sql", ".ini", ".cfg"}


class LocalAdapter(Adapter):
    name = "local"
    is_cli = False
    can_write = False

    def __init__(self, binary: str | None = None, base_url: str | None = None, temperature: float = 0.2,
                 max_tokens: int = 4096, repo_context: int = 24_000, transport=None):
        super().__init__(binary)
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
        if spec.model:
            body["model"] = spec.model
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
        async with httpx.AsyncClient(transport=self.transport) as client:
            model = spec.model
            try:
                r = await client.get(self.base_url + "/v1/models", timeout=5)
                model = model or ((r.json().get("data") or [{}])[0].get("id"))
            except (httpx.HTTPError, ValueError):
                on_event(Event("error", text=f"No responde llama-server en {self.base_url}. "
                                             "Arráncalo con: python -m localharness llama serve <modelo>"))
                return _out("failed", time.monotonic() - t0)
            on_event(Event("session", data={"session_id": None, "model": model, "tools": [],
                                            "base_url": self.base_url}))
            body = {**self.payload(spec), "stream": True, "stream_options": {"include_usage": True}}
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
                            if delta.get("reasoning_content"):
                                reasoning.append(delta["reasoning_content"])
                            if delta.get("content"):
                                content.append(delta["content"])
                                buf.append(delta["content"])
                                if not spec.json_schema and "\n\n" in "".join(buf[-2:]):  # un evento por párrafo
                                    on_event(Event("text", text="".join(buf).strip()))
                                    buf.clear()
                            finish = choice.get("finish_reason") or finish
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
        on_event(Event("usage", data={"cost_usd": 0.0, "turns": 1, "usage": usage, "local": True,
                                      "tps": timings.get("predicted_per_second"), "finish_reason": finish,
                                      "reasoning_chars": len("".join(reasoning)) or None}))
        if finish == "length":
            on_event(Event("warning", text="Respuesta cortada por max_tokens"))
        if spec.json_schema and structured is None:
            return _out("failed", time.monotonic() - t0, text)
        on_event(Event("result", text=text, data={"structured": structured}))
        return _out("done", time.monotonic() - t0, text, structured)


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
