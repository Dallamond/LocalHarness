"""Ficha guardada de cada GGUF descargado: metadatos leídos de su cabecera y resultados de la prueba real.

Se guarda en `data/model-info.json` (junto a la base de datos) por ruta del archivo. La cabecera se vuelve a leer
solo si el archivo cambia (tamaño o fecha), así la pestaña de Modelos abre rápido aunque tengas muchos.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from localharness import gguf, llama


class ModelInfo:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def get(self, model: str) -> dict:
        return self._load().get(model) or {}

    def all(self) -> dict:
        return self._load()

    def summary(self, model: Path) -> dict | None:
        """Metadatos del GGUF (leídos una vez y guardados)."""
        try:
            st = model.stat()
        except OSError:
            return None
        stamp = f"{st.st_size}:{int(st.st_mtime)}"
        with self._lock:
            data = self._load()
            entry = data.get(str(model)) or {}
            if entry.get("stamp") == stamp and entry.get("meta"):
                return entry["meta"]
            try:
                meta = gguf.inspect(model)
            except (OSError, gguf.GGUFError) as e:
                meta = {"error": str(e)}
            entry.update({"stamp": stamp, "meta": meta, "read_at": time.time()})
            data[str(model)] = entry
            self._save(data)
            return meta

    def update(self, model: str, **kw) -> dict:
        with self._lock:
            data = self._load()
            entry = data.setdefault(model, {})
            entry.update(kw)
            self._save(data)
            return entry


# --- prueba real contra el llama-server arrancado
TOOL = {"type": "function", "function": {
    "name": "read_file", "description": "Lee un archivo del repositorio y devuelve su contenido.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Ruta relativa"}},
                   "required": ["path"]}}}
SCHEMA = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["approve", "request_changes"]},
                                           "reason": {"type": "string"}}, "required": ["verdict", "reason"]}


def _chat(port: int, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    if llama.API_KEY:
        req.add_header("Authorization", f"Bearer {llama.API_KEY}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def probe(port: int, timeout: float = 180) -> dict:
    """Tres comprobaciones rápidas (coste 0, es tu GPU): ¿llama a una herramienta de verdad (tool_calls)?,
    ¿devuelve JSON válido con esquema?, ¿cuántos tok/s genera?"""
    out: dict = {"at": time.time()}
    try:
        r = _chat(port, {"messages": [
            {"role": "system", "content": "Eres un agente de programación. Usa las herramientas cuando hagan falta."},
            {"role": "user", "content": "¿Qué dice el archivo README.md del repositorio? Léelo con la herramienta."}],
            "tools": [TOOL], "tool_choice": "auto", "max_tokens": 1024, "temperature": 0.2}, timeout)
        msg = (r.get("choices") or [{}])[0].get("message") or {}
        calls = msg.get("tool_calls") or []
        args = {}
        if calls:
            try:
                args = json.loads(calls[0].get("function", {}).get("arguments") or "{}")
            except ValueError:
                args = {}
        out["tool_calls"] = bool(calls) and calls[0].get("function", {}).get("name") == "read_file" \
            and "readme" in str(args.get("path", "")).lower()
        out["tool_detail"] = (f"{calls[0]['function']['name']}({json.dumps(args, ensure_ascii=False)})" if calls
                              else (msg.get("content") or "")[:160])
    except (urllib.error.URLError, OSError, ValueError) as e:
        out["tool_calls"] = None
        out["error"] = f"herramientas: {e}"

    try:
        r = _chat(port, {"messages": [{"role": "user", "content":
                  "Revisa este cambio: se borró una comprobación de None en una función pública. "
                  "Responde con tu veredicto."}],
                  "response_format": {"type": "json_schema", "json_schema": {"name": "v", "schema": SCHEMA}},
                  "max_tokens": 1024, "temperature": 0.2}, timeout)
        content = (r.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        try:
            v = json.loads(content[content.find("{"): content.rfind("}") + 1])
            out["json"] = v.get("verdict") in ("approve", "request_changes")
        except ValueError:
            out["json"] = False
        t = r.get("timings") or {}
        if t.get("predicted_per_second"):
            out["tps"] = round(t["predicted_per_second"], 1)
        if t.get("prompt_per_second"):
            out["prompt_tps"] = round(t["prompt_per_second"], 1)
    except (urllib.error.URLError, OSError, ValueError) as e:
        out["json"] = None
        out["error"] = (out.get("error", "") + f" json: {e}").strip()
    return out
