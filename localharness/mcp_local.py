"""Servidor MCP (stdio) que deja a Claude encargar trabajo al modelo local: lo que haga Qwen no gasta tu plan.

Claude lo recibe con `--mcp-config` cuando su agente tiene «Puede delegar en el modelo local» (config
`delegate_local`). Herramientas (Claude las ve como `mcp__local__<nombre>`):
- `local_ask`: pensar, resumir, comparar, explicar, revisar. Los archivos los lee ESTE servidor del worktree y se
  los pasa a Qwen: Claude no gasta tokens leyéndolos, solo recibe la conclusión.
- `local_write_file`: Qwen escribe un archivo entero (crear o reescribir) en el worktree. Claude recibe un resumen
  y revisa lo que quiera. Solo si la tarea puede escribir (LH_WRITE=1).
- `local_execute_plan`: Claude manda el PLAN entero (bloques: archivos a escribir y preguntas) y el modelo local
  los hace todos, uno tras otro; si se pide, este servidor ejecuta después una orden de comprobación (tests) y
  devuelve un informe por bloque. Es la herramienta del modo «coordinador» (config `coordinator`): Claude
  planifica y presenta, el modelo local genera. Solo si la tarea puede escribir.
- `local_research`: Qwen busca en la web (DuckDuckGo HTML, sin clave: lo más sencillo para empezar), lee las
  primeras páginas y devuelve una respuesta con fuentes. Claude no gasta tokens buscando ni leyendo. LH_WEB=0 la quita.
- `local_agent`: encarga una TAREA ENTERA al agente local con herramientas (adapters/local_agent.py: lee, busca,
  escribe y ejecuta los tests él solo, en este mismo worktree). Claude recibe su resumen y la lista de archivos que
  cambió, y revisa. Es la pieza del modo «jefe» (Claude dirige y revisa; el local hace). Solo si LH_WRITE=1.
- `run_checks`: ejecuta una orden de la lista blanca (tests, linter) y devuelve la salida. No usa ningún modelo:
  así Claude puede comprobar el trabajo sin tener Bash.

Todo confinado a LH_ROOT (el worktree de la tarea): nada fuera, nada dentro de .git. Cada encargo se apunta en
LH_LOG (JSONL) para que LocalHarness lo muestre y cuente los tokens ahorrados.

Protocolo: JSON-RPC 2.0, un mensaje por línea en stdin/stdout (sin dependencias). stdout es SOLO para el
protocolo; los avisos van a stderr.

El «trabajador local» (lo que ve la oficina): `local_prepare` deja que Claude elija ANTES de encargar qué skills y
qué herramientas lleva el modelo local; se guardan en LH_WORKER (JSON, también lo cambia el usuario desde la GUI
mientras trabaja) y se aplican en cada encargo siguiente. Cada encargo apunta en el log su petición, su respuesta y
su pensamiento (`request`, `answer`, `thinking`): es el chat propio del trabajador.

Variables: LH_LOCAL_URL (llama-server), LH_LOCAL_KEY (su --api-key), LH_ROOT, LH_LOG, LH_WRITE (1/0),
LH_MAX_TOKENS (por defecto 8192), LH_MAX_INPUT_CHARS (texto de archivos por encargo, por defecto 40000),
LH_WEB (1/0, búsqueda web), LH_COORDINATOR (1: Claude no puede hacerlo él; los errores no le dicen «hazlo tú»),
LH_COMMANDS (JSON: lista blanca de órdenes de comprobación; por defecto CHECK_COMMANDS), LH_AGENT_TURNS (pasos del
agente local por encargo, 25), LH_AGENT_TIMEOUT (segundos por encargo de `local_agent`, 1200), LH_WORKER (estado
del trabajador: skills y herramientas), LH_SKILLS (JSON {nombre: {description, body}}: skills que puede llevar),
LH_LIVE (JSON que se reescribe ~1 vez por segundo con lo que el modelo local está pensando y escribiendo AHORA: las
peticiones a llama-server van en streaming para que la oficina lo vea trabajar en vivo).
"""

import asyncio
import hashlib
import subprocess

import html
import json
import os
import re
import shlex
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
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

BLOCK = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Identificador corto del bloque (p. ej. «1», «calc»)"},
        "title": {"type": "string", "description": "Qué es el bloque, en pocas palabras"},
        "kind": {"type": "string", "enum": ["write", "ask"],
                 "description": "write = escribir/reescribir el archivo `path`; ask = pregunta o análisis en texto"},
        "path": {"type": "string", "description": "Solo write: archivo a escribir (relativo al repo)"},
        "instructions": {"type": "string",
                         "description": "Instrucciones autocontenidas: qué hacer, firmas, casos límite, estilo"},
        "files": {"type": "array", "items": {"type": "string"},
                  "description": "Archivos que debe leer (incluye los que escriban bloques anteriores si dependen)"},
    },
    "required": ["instructions"],
}
PLAN = {
    "name": "local_execute_plan",
    "description": (
        "Encarga a un modelo local GRATIS un PLAN ENTERO de una vez: una lista de bloques (archivos a escribir o "
        "reescribir y preguntas/análisis) que hace en orden, cada uno leyendo él los archivos que le indiques. "
        "Opcionalmente ejecuta al final una orden de comprobación (tests) y te devuelve su salida. Recibes un "
        "informe por bloque: léelo, comprueba lo crítico y vuelve a llamarla solo con los bloques que fallaron."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "blocks": {"type": "array", "items": BLOCK, "description": "Los bloques del plan, en orden"},
            "check": {"type": "string",
                      "description": "Orden de comprobación al terminar (p. ej. «python -m unittest»). Lista blanca: "
                                     "tests y linters"},
        },
        "required": ["blocks"],
    },
}

RESEARCH = {
    "name": "local_research",
    "description": (
        "Encarga a un modelo local GRATIS investigar en internet: busca, lee las primeras páginas y te devuelve una "
        "respuesta corta con las fuentes (URL). Úsalo para documentación de librerías, errores, versiones, APIs o "
        "cualquier dato que no esté en el repo. Es un modelo pequeño: comprueba en la fuente lo que sea crítico."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Qué quieres averiguar, con el contexto necesario"},
            "query": {"type": "string", "description": "Búsqueda concreta para el buscador (si no, usa la pregunta)"},
            "pages": {"type": "integer", "description": "Cuántas páginas leer (1-5, por defecto 3)"},
        },
        "required": ["question"],
    },
}

AGENT = {
    "name": "local_agent",
    "description": (
        "Encarga una TAREA ENTERA de programación a un agente local GRATIS que trabaja solo en este repositorio: "
        "lee los archivos, los modifica y ejecuta los tests. Dale una tarea concreta y autocontenida: qué cambiar, "
        "en qué archivos, criterios de aceptación y qué orden de tests ejecutar. Te devuelve su resumen y los "
        "archivos que cambió: revísalos tú (Read) y comprueba con `run_checks`. Si algo está mal, vuelve a "
        "encargárselo diciendo exactamente qué corregir."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "La tarea completa, con criterios de aceptación"},
            "files": {"type": "array", "items": {"type": "string"},
                      "description": "Archivos por los que debe empezar (rutas relativas)"},
            "max_turns": {"type": "integer", "description": "Tope de pasos del agente (por defecto 25)"},
        },
        "required": ["task"],
    },
}
CHECKS = {
    "name": "run_checks",
    "description": (
        "Ejecuta una orden de comprobación (tests o linter, de una lista permitida) en el repositorio y devuelve "
        "el código de salida y la salida. No gasta cuota. Úsalo para verificar lo que haya hecho el modelo local."),
    "inputSchema": {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "Orden, p. ej. «python -m unittest» o «npm test»"}},
        "required": ["command"],
    },
}

# herramientas del agente local (local_agent) que Claude o tú podéis quitarle o darle; las de control van siempre
WORKER_TOOLS = {"leer_archivo": "leer archivos", "listar": "listar carpetas", "buscar_texto": "buscar en el código",
                "escribir_archivo": "escribir archivos", "ejecutar": "ejecutar tests",
                "buscar_web": "buscar en internet", "leer_url": "leer páginas web"}
PREPARE = {
    "name": "local_prepare",
    "description": "",  # se rellena en tools(): lleva la lista de skills disponibles
    "inputSchema": {
        "type": "object",
        "properties": {
            "skills": {"type": "array", "items": {"type": "string"},
                       "description": "Nombres de las skills que debe seguir el modelo local (de la lista)"},
            "tools": {"type": "array", "items": {"type": "string", "enum": list(WORKER_TOOLS)},
                      "description": "Herramientas del agente local (`local_agent`). Omítelo para darle todas"},
            "reason": {"type": "string", "description": "Por qué estas skills y herramientas (lo ve el usuario)"},
        },
        "required": ["skills"],
    },
}
MAX_LOG_REQUEST = 3000
MAX_LOG_ANSWER = 8000
MAX_LOG_THINKING = 6000

SYSTEM_ASK = ("Eres un asistente de programación que ayuda a otro agente más caro a ahorrar trabajo. Responde en "
              "español, concreto y sin relleno. Si te faltan datos, dilo en vez de inventar.")
SYSTEM_WRITE = ("Eres un programador. Devuelve ÚNICAMENTE el contenido completo del archivo pedido, dentro de un solo "
                "bloque de código, sin explicaciones antes ni después. No dejes partes sin hacer ni «...».")
SYSTEM_RESEARCH = ("Eres un investigador. Responde a la pregunta SOLO con lo que digan las fuentes que te paso, en "
                   "español, concreto y sin relleno. Cita las fuentes como [1], [2]… Si no lo dicen, dilo claramente.")
SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LocalHarness/0.1"
MAX_PAGE_CHARS = 8000
MAX_BLOCKS = 20
# órdenes que `local_execute_plan` puede ejecutar como comprobación (sin shell; prefijos, como en local_agent)
CHECK_COMMANDS = ["python -m unittest", "python -m pytest", "pytest", "npm test", "npm run test", "npm run lint",
                  "ruff check", "node --test"]
CHECK_TIMEOUT_S = 300
MAX_CHECK_CHARS = 4000
ENV_DROP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "LH_LOCAL_KEY")


JUNK_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".venv"}


class ToolError(Exception):
    pass


class NoModel(ToolError):
    """No hay llama-server que conteste: no tiene sentido seguir con más bloques."""


class Server:
    def __init__(self, env: dict[str, str] | None = None, transport=None, http_get=None):
        env = env if env is not None else dict(os.environ)
        self.url = (env.get("LH_LOCAL_URL") or "http://127.0.0.1:8080").rstrip("/").removesuffix("/v1")
        self.key = env.get("LH_LOCAL_KEY") or ""
        self.root = Path(env.get("LH_ROOT") or os.getcwd()).resolve()
        self.log = Path(env["LH_LOG"]) if env.get("LH_LOG") else None
        self.write = env.get("LH_WRITE", "1") == "1"
        self.max_tokens = int(env.get("LH_MAX_TOKENS") or 8192)
        self.max_input = int(env.get("LH_MAX_INPUT_CHARS") or 40_000)
        self.web = env.get("LH_WEB", "1") == "1"
        self.coordinator = env.get("LH_COORDINATOR") == "1"
        try:
            self.commands = json.loads(env["LH_COMMANDS"]) if env.get("LH_COMMANDS") else None
        except ValueError:
            self.commands = None
        self.agent_turns = int(env.get("LH_AGENT_TURNS") or 25)
        self.agent_timeout = float(env.get("LH_AGENT_TIMEOUT") or 1200)
        self.worker_path = Path(env["LH_WORKER"]) if env.get("LH_WORKER") else None
        self.skills_path = Path(env["LH_SKILLS"]) if env.get("LH_SKILLS") else None
        self.live_path = Path(env["LH_LIVE"]) if env.get("LH_LIVE") else None
        self.current: dict = {}  # encargo en curso (para el directo)
        self.transport = transport  # pruebas: función (body) -> respuesta JSON de /v1/chat/completions
        self.http_get = http_get or _http_get  # pruebas: función (url, data) -> HTML; sin red de verdad

    # --- protocolo
    def tools(self) -> list[dict]:
        prepare = [self.prepare_tool()] if self.worker_path else []
        return (prepare + [ASK] + ([WRITE, PLAN, AGENT] if self.write else []) + ([CHECKS] if self.commands != [] else [])
                + ([RESEARCH] if self.web else []))

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
        self.current = {"tool": name, "task": str(args.get("task") or args.get("path") or args.get("question")
                                                  or args.get("command") or "")[:300]}
        try:
            if name == "local_prepare" and self.worker_path:
                text, stats = self.prepare(args.get("skills") or [], args.get("tools"), str(args.get("reason") or ""))
                entry["task"] = stats["summary"]
            elif name == "local_ask":
                entry["task"] = str(args.get("task", ""))[:300]
                text, stats = self.ask(str(args.get("task") or ""), args.get("files") or [])
            elif name == "local_write_file" and self.write:
                entry["path"] = str(args.get("path", ""))
                text, stats = self.write_file(str(args.get("path") or ""), str(args.get("instructions") or ""),
                                              args.get("context_files") or [])
            elif name == "local_execute_plan" and self.write:
                text, stats = self.execute_plan(args.get("blocks"), str(args.get("check") or ""))
                entry["task"] = f"plan: {stats['ok']} de {stats['blocks']} bloques"
            elif name == "local_agent" and self.write:
                entry["task"] = str(args.get("task", ""))[:300]
                text, stats = self.agent(str(args.get("task") or ""), args.get("files") or [], args.get("max_turns"))
            elif name == "run_checks" and self.commands != []:
                entry["task"] = str(args.get("command", ""))[:300]
                text = self.run_check(str(args.get("command") or ""))
                if not text.startswith("código de salida"):
                    raise ToolError(text)  # orden no permitida, mal escrita o que no se pudo lanzar
                stats = {"exit": text.split("\n", 1)[0]}
            elif name == "local_research" and self.web:
                entry["task"] = str(args.get("question", ""))[:300]
                text, stats = self.research(str(args.get("question") or ""), str(args.get("query") or ""),
                                            args.get("pages"))
            else:
                raise ToolError(f"Herramienta no disponible: {name}")
            entry.update(stats, ok=True)
            return {"content": [{"type": "text", "text": text}]}
        except ToolError as e:
            msg = self.fallback(str(e))
            entry.update(ok=False, error=msg)
            return {"content": [{"type": "text", "text": f"No se pudo: {msg}"}], "isError": True}
        finally:
            entry["seconds"] = round(time.monotonic() - t0, 1)
            self._log(entry)

    # --- el trabajador local: skills y herramientas
    def available_skills(self) -> dict[str, dict]:
        if not self.skills_path:
            return {}
        try:
            data = json.loads(self.skills_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def worker(self) -> dict:
        """Estado actual (se relee en cada encargo: el usuario puede cambiarlo desde la GUI mientras trabaja)."""
        if not self.worker_path:
            return {"skills": [], "tools": None}
        try:
            w = json.loads(self.worker_path.read_text(encoding="utf-8"))
            return w if isinstance(w, dict) else {"skills": [], "tools": None}
        except (OSError, ValueError):
            return {"skills": [], "tools": None}

    def skills_text(self) -> str:
        cat = self.available_skills()
        parts = [f"## Skill: {n}\n{cat[n].get('body', '').strip()}" for n in self.worker().get("skills") or [] if n in cat]
        return ("\n\n# Skills que debes seguir en este encargo\n\n" + "\n\n".join(parts)) if parts else ""

    def prepare_tool(self) -> dict:
        cat = self.available_skills()
        lines = [f"- {n}: {(v.get('description') or '')[:140]}" for n, v in sorted(cat.items())][:80]
        desc = ("PRIMER PASO antes de encargar nada: equipa al modelo local (el «trabajador local») con las skills y "
                "herramientas que necesita para ESTA tarea. Las skills se añaden a cada encargo siguiente como reglas "
                "que debe seguir; elige pocas y relevantes (cada una ocupa contexto en un modelo pequeño). Puedes "
                "volver a llamarla para cambiarlas. El usuario ve tu elección y puede corregirla.\n"
                "Herramientas de `local_agent`: " + ", ".join(f"{k} ({v})" for k, v in WORKER_TOOLS.items()) + ".\n"
                "Skills disponibles:\n" + ("\n".join(lines) if lines else "(ninguna instalada)"))
        return {**PREPARE, "description": desc}

    def prepare(self, skills, tools, reason: str) -> tuple[str, dict]:
        cat = self.available_skills()
        if not isinstance(skills, list):
            raise ToolError("`skills` tiene que ser una lista de nombres")
        names = [str(n) for n in skills]
        unknown = [n for n in names if n not in cat]
        if unknown:
            raise ToolError(f"no existen estas skills: {', '.join(unknown)}. Disponibles: {', '.join(sorted(cat)) or 'ninguna'}")
        if tools is not None:
            if not isinstance(tools, list) or any(t not in WORKER_TOOLS for t in tools):
                raise ToolError(f"herramientas válidas: {', '.join(WORKER_TOOLS)}")
            tools = list(dict.fromkeys(tools))
        state = {**self.worker(), "skills": list(dict.fromkeys(names)), "tools": tools, "by": "Claude",
                 "reason": reason[:500], "at": time.time()}
        self.worker_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tools_txt = ", ".join(tools) if tools is not None else "todas"
        summary = f"skills: {', '.join(state['skills']) or 'ninguna'} · herramientas: {tools_txt}"
        return (f"Trabajador local equipado. {summary}. Se aplica a los encargos siguientes."), {"summary": summary}

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

    def execute_plan(self, blocks, check: str) -> tuple[str, dict]:
        """Hace los bloques en orden con el modelo local. Un bloque que falla no para el resto (salvo que no haya
        modelo). Cada bloque se apunta en el log como su propio encargo; el resumen del plan, sin tokens."""
        if not isinstance(blocks, list) or not blocks:
            raise ToolError("falta `blocks` (lista de bloques con `instructions`)")
        if len(blocks) > MAX_BLOCKS:
            raise ToolError(f"demasiados bloques ({len(blocks)}); máximo {MAX_BLOCKS} por llamada")
        lines, ok, wrote = [], 0, 0
        for i, b in enumerate(blocks, 1):
            b = b if isinstance(b, dict) else {"instructions": str(b)}
            bid = str(b.get("id") or i)
            path = str(b.get("path") or "")
            kind = b.get("kind") if b.get("kind") in ("write", "ask") else ("write" if path else "ask")
            title = str(b.get("title") or path or str(b.get("instructions") or "")[:60])
            files = [f for f in b.get("files") or [] if isinstance(f, str)]
            entry: dict = {"tool": f"local_execute_plan/{kind}", "at": time.time(), "block": bid, "task": title[:300]}
            self.current = {"tool": entry["tool"], "task": title[:300]}
            if path:
                entry["path"] = path
            t0 = time.monotonic()
            try:
                if kind == "write":
                    text, stats = self.write_file(path, str(b.get("instructions") or ""), files)
                    wrote += 1
                else:
                    text, stats = self.ask(str(b.get("instructions") or ""), files)
                entry.update(stats, ok=True)
                ok += 1
                lines.append(f"## Bloque {bid} — {title} ✅\n{text}")
            except NoModel:
                entry.update(ok=False, error="no hay modelo local")
                raise
            except ToolError as e:
                entry.update(ok=False, error=str(e))
                lines.append(f"## Bloque {bid} — {title} ❌\nNo se pudo: {e}")
            finally:
                entry["seconds"] = round(time.monotonic() - t0, 1)
                self._log(entry)
        stats = {"blocks": len(blocks), "ok": ok}
        if check.strip():
            result = self.run_check(check) if wrote else "(no se ejecutó: ningún bloque escribió archivos)"
            lines.append(f"## Comprobación: `{check}`\n```\n{result}\n```")
            stats["check"] = check
        head = f"Plan hecho por el modelo local: {ok} de {len(blocks)} bloques bien."
        return head + "\n\n" + "\n\n".join(lines), stats

    def run_check(self, command: str) -> str:
        """Orden de comprobación (tests/linter) en la raíz del repo, sin shell y de la lista blanca."""
        try:
            argv = shlex.split(command)
        except ValueError as e:
            return f"orden mal escrita: {e}"
        commands = CHECK_COMMANDS if self.commands is None else self.commands
        allowed = [shlex.split(c) for c in commands]
        if not argv or not any(argv[: len(p)] == p for p in allowed):
            return f"orden no permitida. Permitidas: {'; '.join(commands)}"
        exe = sys.executable if argv[0] in ("python", "python3") else (shutil.which(argv[0]) or argv[0])
        env = {k: v for k, v in os.environ.items() if k not in ENV_DROP}
        try:
            p = subprocess.run([exe, *argv[1:]], cwd=self.root, stdin=subprocess.DEVNULL, capture_output=True,
                               env=env, timeout=CHECK_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return f"tardó más de {CHECK_TIMEOUT_S} s y se paró"
        except OSError as e:
            return f"no se pudo lanzar {argv[0]}: {e}"
        out = (p.stdout + p.stderr).decode("utf-8", "replace").strip()
        if len(out) > MAX_CHECK_CHARS:  # lo útil de unos tests suele estar al final
            out = "[… principio recortado]\n" + out[-MAX_CHECK_CHARS:]
        return f"código de salida {p.returncode}\n{out or '(sin salida)'}"

    def fallback(self, msg: str) -> str:
        """En modo coordinador Claude no tiene con qué hacerlo él: que lo cuente en vez de intentarlo."""
        if not self.coordinator:
            return msg
        return msg.replace("; hazlo tú", "; díselo al usuario (tú solo coordinas, no puedes hacerlo tú)")

    def research(self, question: str, query: str, pages) -> tuple[str, dict]:
        if not question.strip():
            raise ToolError("falta `question`")
        try:
            n = max(1, min(5, int(pages or 3)))
        except (TypeError, ValueError):
            n = 3
        results = self.search(query.strip() or question)
        if not results:
            raise ToolError("el buscador no devolvió resultados (¿sin red?); hazlo tú")
        sources, used = [], []
        for r in results:
            if len(used) >= n:
                break
            try:
                text = page_text(self.http_get(r["url"], None))[:MAX_PAGE_CHARS]
            except Exception:  # noqa: BLE001 — una página caída no para la investigación
                text = ""
            used.append({**r, "read": bool(text)})
            sources.append(f"[{len(used)}] {r['title']} — {r['url']}\n" + (text or f"(no se pudo leer; resumen del "
                                                                                  f"buscador: {r['snippet']})"))
        user = f"PREGUNTA:\n{question}\n\nFUENTES:\n\n" + "\n\n".join(sources)
        answer, stats = self.complete(SYSTEM_RESEARCH, user)
        refs = "\n".join(f"[{i}] {u['title']} — {u['url']}" for i, u in enumerate(used, 1))
        return f"{answer}\n\nFuentes:\n{refs}", {**stats, "sources": [u["url"] for u in used]}

    def agent(self, task: str, files: list, max_turns) -> tuple[str, dict]:
        """El bucle del agente local (adapters/local_agent.py) sobre este worktree, como un encargo más."""
        from localharness.adapters.base import RunSpec
        from localharness.adapters.local_agent import LocalAgentAdapter
        from localharness.events import Event
        if not task.strip():
            raise ToolError("falta `task`")
        try:
            turns = max(3, min(60, int(max_turns or self.agent_turns)))
        except (TypeError, ValueError):
            turns = self.agent_turns
        start = [f for f in files if isinstance(f, str)]
        prompt = task + (f"\n\nEmpieza leyendo: {', '.join(start)}" if start else "") + self.skills_text()
        before = self.snapshot()
        adapter = LocalAgentAdapter(base_url=self.url, api_key=self.key or None, transport=self._httpx(),
                                    http_get=self.http_get, web=self.web,
                                    commands=CHECK_COMMANDS if self.commands is None else self.commands,
                                    only_tools=self.worker().get("tools"))
        seen: dict = {"tools": 0, "errors": [], "usage": {}, "model": None, "thinking": []}

        def on_event(ev: Event) -> None:
            if ev.kind == "tool":
                seen["tools"] += 1
                inp = ev.data.get("input") or {}
                what = inp.get("ruta") or inp.get("comando") or inp.get("texto") or inp.get("consulta") or ""
                self._live("\n\n".join(seen["thinking"]), f"→ {ev.text} {what}".strip())
                self._log({"tool": "local_agent", "progress": True, "text": f"{ev.text} {what}".strip()[:200],
                           "at": time.time()})
            elif ev.kind == "thinking" and ev.text:
                seen["thinking"].append(ev.text)
                self._live("\n\n".join(seen["thinking"]), "")
                self._log({"tool": "local_agent", "progress": True, "thinking": ev.text[-MAX_LOG_THINKING:],
                           "text": "pensando…", "at": time.time()})
            elif ev.kind == "error":
                seen["errors"].append(ev.text)
            elif ev.kind == "usage":
                seen["usage"] = ev.data.get("usage") or {}
                seen["model"] = ev.data.get("model")
        res = asyncio.run(adapter.execute(RunSpec(prompt=prompt, cwd=str(self.root), max_turns=turns), on_event,
                                          self.agent_timeout))
        self._live("\n\n".join(seen["thinking"]), res.get("final") or "", done=True)
        changed = self.changed(before, self.snapshot())
        stats = {"prompt_tokens": seen["usage"].get("prompt_tokens"), "completion_tokens":
                 seen["usage"].get("completion_tokens"), "model": seen["model"], "files": changed,
                 "status": res["status"], "request": task[:MAX_LOG_REQUEST],
                 "answer": (res.get("final") or "")[:MAX_LOG_ANSWER], "skills": self.worker().get("skills") or []}
        if seen["thinking"]:
            stats["thinking"] = "\n\n".join(seen["thinking"])[-MAX_LOG_THINKING:]
        if res["status"] != "done" and not seen["tools"] and seen["errors"]:
            raise ToolError(f"{seen['errors'][-1]}; hazlo tú")
        lines = [f"El agente local terminó: {'OK' if res['status'] == 'done' else res['status']} "
                 f"({seen['tools']} acciones)."]
        if res.get("final"):
            lines.append(f"Su resumen:\n{res['final'].strip()}")
        if seen["errors"]:
            lines.append("Problemas: " + " | ".join(seen["errors"][-3:]))
        lines.append("Archivos que cambió: " + (", ".join(changed) if changed else "ninguno"))
        lines.append("Revisa los cambios (Read) y comprueba con `run_checks` antes de darlo por bueno.")
        return "\n\n".join(lines), stats

    def snapshot(self) -> dict[str, str]:
        """Huella de los archivos con cambios sin guardar en git (modificados o nuevos) para saber qué tocó."""
        try:
            raw = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"], cwd=self.root,
                                 capture_output=True, timeout=30).stdout.decode("utf-8", "replace")
        except (OSError, subprocess.TimeoutExpired):
            return {}
        out = {}
        for item in raw.split("\0"):
            if len(item) < 4:
                continue
            rel = item[3:]
            if any(part in JUNK_DIRS for part in Path(rel).parts) or rel.endswith((".pyc", ".pyo")):
                continue  # restos de ejecutar los tests, no trabajo del agente
            p = self.root / rel
            out[rel] = hashlib.sha1(p.read_bytes()).hexdigest() if p.is_file() else "borrado"
        return out

    @staticmethod
    def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
        return sorted([p for p, h in after.items() if before.get(p) != h] + [p for p in before if p not in after])

    def _httpx(self):
        """Pruebas: el `transport` de función se envuelve en un transporte de httpx para el agente local."""
        if not self.transport:
            return None
        import httpx

        def handler(request):
            if request.url.path.endswith("/v1/models"):
                return httpx.Response(200, json={"data": [{"id": "modelo-de-prueba.gguf"}]})
            return httpx.Response(200, json=self.transport(json.loads(request.content)))
        return httpx.MockTransport(handler)

    def search(self, query: str) -> list[dict]:
        try:
            raw = self.http_get(SEARCH_URL, {"q": query})
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"no se pudo buscar en la web ({e}); hazlo tú") from None
        return parse_ddg(raw)

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
        skills = self.worker().get("skills") or []
        system += self.skills_text()
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
                 "model": _short(data.get("model")), "gen_seconds": round(time.monotonic() - t0, 1),
                 # el chat propio del trabajador local: lo que se le pidió, lo que contestó y lo que pensó
                 "request": user[:MAX_LOG_REQUEST] + ("\n[…]" if len(user) > MAX_LOG_REQUEST else ""),
                 "answer": text[:MAX_LOG_ANSWER], "skills": skills}
        if msg.get("reasoning_content"):
            stats["thinking"] = msg["reasoning_content"][-MAX_LOG_THINKING:]
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
        # en streaming: así se puede enseñar en vivo lo que piensa y escribe (LH_LIVE)
        body = {**body, "stream": True, "stream_options": {"include_usage": True}}
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                if "text/event-stream" not in (r.headers.get("Content-Type") or ""):
                    return json.loads(r.read())  # servidor que no hace streaming: la respuesta entera
                return self.read_stream(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:  # no sigue con más bloques: todos fallarían igual
                raise NoModel("llama-server rechaza la clave (401): ese llama-server no lo arrancó esta sesión de "
                              "LocalHarness o se lanzó a mano con otra --api-key. Páralo y arráncalo desde Modelos "
                              "locales; hazlo tú") from None
            raise ToolError(f"llama-server HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}") from None
        except (OSError, ValueError):
            raise NoModel("no hay ningún modelo local arrancado (Modelos locales → Arrancar); hazlo tú") from None

    def read_stream(self, lines) -> dict:
        """Respuesta SSE de llama-server (`data: {...}` por trozo) → la misma forma que sin streaming. Mientras
        llega, cada ~0,8 s deja en LH_LIVE lo que lleva pensado y escrito."""
        content: list[str] = []
        reasoning: list[str] = []
        model = finish = None
        usage: dict = {}
        timings: dict = {}
        last = 0.0
        for raw in lines:
            line = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)).strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except ValueError:
                continue
            model = chunk.get("model") or model
            usage = chunk.get("usage") or usage
            timings = chunk.get("timings") or timings
            for c in chunk.get("choices") or []:
                delta = c.get("delta") or {}
                if delta.get("content"):
                    content.append(delta["content"])
                if delta.get("reasoning_content"):
                    reasoning.append(delta["reasoning_content"])
                finish = c.get("finish_reason") or finish
            if time.monotonic() - last > 0.8:
                last = time.monotonic()
                self._live("".join(reasoning), "".join(content))
        self._live("".join(reasoning), "".join(content), done=True)
        return {"model": model, "usage": usage, "timings": timings,
                "choices": [{"message": {"content": "".join(content), "reasoning_content": "".join(reasoning)},
                             "finish_reason": finish}]}

    def _live(self, thinking: str, text: str, done: bool = False) -> None:
        """Lo que el modelo local está haciendo AHORA (lo lee el orquestador cada segundo para la oficina)."""
        if not self.live_path:
            return
        data = {**self.current, "thinking": thinking[-4000:], "text": text[-3000:], "done": done, "at": time.time(),
                "skills": self.worker().get("skills") or []}
        tmp = self.live_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.live_path)
        except OSError:
            pass

    def _log(self, entry: dict) -> None:
        if not self.log:
            return
        try:
            with open(self.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


def _http_get(url: str, data: dict | None) -> str:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype and "text" not in ctype:
            raise ValueError(f"no es una página de texto ({ctype})")
        return r.read(2_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")


_DDG_LINK = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DDG_SNIPPET = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
_TAGS = re.compile(r"<[^>]+>")


def parse_ddg(raw: str) -> list[dict]:
    """Resultados de la versión HTML de DuckDuckGo: [{title, url, snippet}]. Sin anuncios ni repetidos."""
    out, seen = [], set()
    snippets = [_clean(m) for m in _DDG_SNIPPET.findall(raw)]
    for i, (href, title) in enumerate(_DDG_LINK.findall(raw)):
        href = html.unescape(href)
        if "uddg=" in href:  # enlace de redirección: //duckduckgo.com/l/?uddg=<url>
            href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
        if href.startswith("//"):
            href = "https:" + href
        if not href.startswith("http") or "duckduckgo.com/y.js" in href or href in seen:
            continue
        seen.add(href)
        out.append({"title": _clean(title), "url": href, "snippet": snippets[i] if i < len(snippets) else ""})
    return out


def _clean(fragment: str) -> str:
    return " ".join(html.unescape(_TAGS.sub("", fragment)).split())


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "pre", "tr", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def page_text(raw: str) -> str:
    """Texto legible de una página HTML (sin scripts, estilos ni menús), con saltos de línea por bloque."""
    p = _Text()
    p.feed(raw)
    lines = (" ".join(ln.split()) for ln in "".join(p.parts).splitlines())
    return "\n".join(ln for ln in lines if ln)


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
    # la CLI de Claude lo lanza por ruta desde el worktree: el paquete (para `local_agent`) tiene que estar en el path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
