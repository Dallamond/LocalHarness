"""Servidor MCP (stdio) que deja a Claude encargar trabajo al modelo local: lo que haga Qwen no gasta tu plan.

Claude lo recibe con `--mcp-config` cuando su agente tiene «Puede delegar en el modelo local» (config
`delegate_local`). Herramientas (Claude las ve como `mcp__local__<nombre>`):
- `local_ask`: pensar, resumir, comparar, explicar, revisar. Los archivos los lee ESTE servidor del worktree y se
  los pasa a Qwen: Claude no gasta tokens leyéndolos, solo recibe la conclusión.
- `local_write_file`: Qwen escribe un archivo entero (crear o reescribir) en el worktree. Claude recibe un resumen
  y revisa lo que quiera. Solo si la tarea puede escribir (LH_WRITE=1).

Todo confinado a LH_ROOT (el worktree de la tarea): nada fuera, nada dentro de .git. Cada encargo se apunta en
LH_LOG (JSONL) para que LocalHarness lo muestre y cuente los tokens ahorrados.

Protocolo: JSON-RPC 2.0, un mensaje por línea en stdin/stdout (sin dependencias). stdout es SOLO para el
protocolo; los avisos van a stderr.

Variables: LH_LOCAL_URL (llama-server), LH_LOCAL_KEY (su --api-key), LH_ROOT, LH_LOG, LH_WRITE (1/0),
LH_MAX_TOKENS (por defecto 8192), LH_MAX_INPUT_CHARS (texto de archivos por encargo, por defecto 40000).
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROTOCOL = "2025-06-18"

ASK = {
    "name": "local_ask",
    "description": (
        "Encarga a un modelo local GRATIS (no gasta tu cuota) pensar, resumir, explicar, comparar opciones, proponer "
        "alternativas o revisar código. Pásale las rutas en `files`: los lee él, tú NO necesitas leerlos antes. "
        "Devuelve su respuesta en texto. Es un modelo pequeño: verifica lo que sea crítico."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Qué quieres que haga, con todo el contexto necesario"},
            "files": {"type": "array", "items": {"type": "string"},
                      "description": "Rutas (relativas al repo) que debe leer"},
        },
        "required": ["task"],
    },
}
WRITE = {
    "name": "local_write_file",
    "description": (
        "Encarga a un modelo local GRATIS escribir un archivo COMPLETO (nuevo o reescrito) según tus instrucciones. "
        "Lo escribe él en disco y tú recibes un resumen: ahorra los tokens de generar el código. Da instrucciones "
        "precisas (qué debe contener, funciones y firmas, estilo, casos límite). Revisa después lo importante con "
        "Read y corrige con Edit. Si el archivo existe, el modelo lo ve y lo reescribe entero."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta del archivo a escribir (relativa al repo)"},
            "instructions": {"type": "string", "description": "Qué debe contener el archivo"},
            "context_files": {"type": "array", "items": {"type": "string"},
                              "description": "Otros archivos que debe leer para hacerlo bien"},
        },
        "required": ["path", "instructions"],
    },
}

SYSTEM_ASK = ("Eres un asistente de programación que ayuda a otro agente más caro a ahorrar trabajo. Responde en "
              "español, concreto y sin relleno. Si te faltan datos, dilo en vez de inventar.")
SYSTEM_WRITE = ("Eres un programador. Devuelve ÚNICAMENTE el contenido completo del archivo pedido, dentro de un solo "
                "bloque de código, sin explicaciones antes ni después. No dejes partes sin hacer ni «...».")


class ToolError(Exception):
    pass


class Server:
    def __init__(self, env: dict[str, str] | None = None, transport=None):
        env = env if env is not None else dict(os.environ)
        self.url = (env.get("LH_LOCAL_URL") or "http://127.0.0.1:8080").rstrip("/").removesuffix("/v1")
        self.key = env.get("LH_LOCAL_KEY") or ""
        self.root = Path(env.get("LH_ROOT") or os.getcwd()).resolve()
        self.log = Path(env["LH_LOG"]) if env.get("LH_LOG") else None
        self.write = env.get("LH_WRITE", "1") == "1"
        self.max_tokens = int(env.get("LH_MAX_TOKENS") or 8192)
        self.max_input = int(env.get("LH_MAX_INPUT_CHARS") or 40_000)
        self.transport = transport  # pruebas: función (body) -> respuesta JSON de /v1/chat/completions

    # --- protocolo
    def tools(self) -> list[dict]:
        return [ASK, WRITE] if self.write else [ASK]

    def handle(self, msg: dict) -> dict | None:
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:  # notificación (p. ej. notifications/initialized): sin respuesta
            return None
        try:
            if method == "initialize":
                result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion") or PROTOCOL,
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "localharness-local", "version": "0.1.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tools()}
            elif method == "tools/call":
                p = msg.get("params") or {}
                result = self.call(p.get("name"), p.get("arguments") or {})
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Método desconocido: {method}"}}
        except Exception as e:  # noqa: BLE001 — un fallo nunca tumba el servidor
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def call(self, name: str, args: dict) -> dict:
        t0 = time.monotonic()
        entry: dict = {"tool": name, "at": time.time()}
        try:
            if name == "local_ask":
                entry["task"] = str(args.get("task", ""))[:300]
                text, stats = self.ask(str(args.get("task") or ""), args.get("files") or [])
            elif name == "local_write_file" and self.write:
                entry["path"] = str(args.get("path", ""))
                text, stats = self.write_file(str(args.get("path") or ""), str(args.get("instructions") or ""),
                                              args.get("context_files") or [])
            else:
                raise ToolError(f"Herramienta no disponible: {name}")
            entry.update(stats, ok=True)
            return {"content": [{"type": "text", "text": text}]}
        except ToolError as e:
            entry.update(ok=False, error=str(e))
            return {"content": [{"type": "text", "text": f"No se pudo: {e}"}], "isError": True}
        finally:
            entry["seconds"] = round(time.monotonic() - t0, 1)
            self._log(entry)

    # --- herramientas
    def ask(self, task: str, files: list) -> tuple[str, dict]:
        if not task.strip():
            raise ToolError("falta `task`")
        ctx, read = self.read_files(files)
        user = task + (f"\n\nARCHIVOS:\n{ctx}" if ctx else "")
        answer, stats = self.complete(SYSTEM_ASK, user)
        return answer, {**stats, "files": read}

    def write_file(self, path: str, instructions: str, context_files: list) -> tuple[str, dict]:
        if not instructions.strip():
            raise ToolError("faltan `instructions`")
        target = self.safe(path)
        old = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
        ctx, read = self.read_files([f for f in context_files if f != path])
        user = f"ARCHIVO A ESCRIBIR: {path}\n\nINSTRUCCIONES:\n{instructions}"
        if old is not None:
            user += f"\n\nCONTENIDO ACTUAL (reescríbelo entero):\n```\n{old[: self.max_input]}\n```"
        if ctx:
            user += f"\n\nARCHIVOS DE CONTEXTO:\n{ctx}"
        raw, stats = self.complete(SYSTEM_WRITE, user)
        content = strip_fence(raw)
        if not content.strip():
            raise ToolError("el modelo local devolvió un archivo vacío")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(content if content.endswith("\n") else content + "\n")
        lines = content.count("\n") + 1
        preview = "\n".join(content.splitlines()[:12])
        verb = "Reescrito" if old is not None else "Creado"
        return (f"{verb} {path} ({lines} líneas). Lo escribió el modelo local: revisa lo importante.\n"
                f"Primeras líneas:\n```\n{preview}\n```"), {**stats, "files": read, "lines": lines}

    # --- utilidades
    def safe(self, path: str) -> Path:
        if not path or not path.strip():
            raise ToolError("falta `path`")
        p = (self.root / path).resolve()
        if not p.is_relative_to(self.root):
            raise ToolError(f"{path} está fuera del repositorio")
        if ".git" in p.relative_to(self.root).parts:
            raise ToolError("no se toca .git")
        return p

    def read_files(self, files: list) -> tuple[str, list[str]]:
        parts, read, used = [], [], 0
        for f in files:
            if not isinstance(f, str):
                continue
            p = self.safe(f)
            if not p.is_file():
                parts.append(f"--- {f} --- (no existe)")
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            room = self.max_input - used
            if room <= 0:
                parts.append(f"--- {f} --- (omitido: ya no cabe más contexto)")
                continue
            cut = text[:room]
            parts.append(f"--- {f} ---\n{cut}" + ("\n[… recortado]" if len(cut) < len(text) else ""))
            used += len(cut)
            read.append(f)
        return "\n\n".join(parts), read

    def complete(self, system: str, user: str) -> tuple[str, dict]:
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.2, "max_tokens": self.max_tokens}
        t0 = time.monotonic()
        data = self.transport(body) if self.transport else self._post(body)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = (msg.get("content") or "").strip()
        usage = data.get("usage") or {}
        timings = data.get("timings") or {}
        stats = {"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                 "tps": round(timings["predicted_per_second"], 1) if timings.get("predicted_per_second") else None,
                 "model": _short(data.get("model")), "gen_seconds": round(time.monotonic() - t0, 1)}
        if not text:
            if msg.get("reasoning_content"):
                raise ToolError("el modelo local se quedó pensando y no llegó a responder (sube LH_MAX_TOKENS o "
                                "usa un modelo sin razonamiento); hazlo tú")
            raise ToolError("el modelo local devolvió una respuesta vacía; hazlo tú")
        if choice.get("finish_reason") == "length":
            text += "\n\n[Aviso: respuesta cortada por límite de tokens]"
        return text, stats

    def _post(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ToolError(f"llama-server HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}") from None
        except (OSError, ValueError):
            raise ToolError("no hay ningún modelo local arrancado (Modelos locales → Arrancar); hazlo tú") from None

    def _log(self, entry: dict) -> None:
        if not self.log:
            return
        try:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


def strip_fence(text: str) -> str:
    """El contenido del primer bloque ``` (si lo hay); si no, el texto tal cual."""
    t = text.strip()
    if "```" not in t:
        return t
    start = t.index("```")
    body = t[start + 3:]
    body = body.split("\n", 1)[1] if "\n" in body else ""  # fuera la etiqueta de lenguaje
    end = body.rfind("```")
    return body[:end].rstrip() if end >= 0 else body.rstrip()


def _short(model_id: str | None) -> str | None:
    if not model_id:
        return None
    return Path(model_id.replace("\\", "/")).name.removesuffix(".gguf")


def read_log(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


def main() -> None:
    server = Server()
    stdin = sys.stdin.buffer
    out = sys.stdout.buffer
    for raw in stdin:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = server.handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            out.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()


if __name__ == "__main__":
    main()
