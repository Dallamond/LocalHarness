"""Servidor MCP (stdio) que deja a Claude encargar trabajo al modelo local: lo que haga Qwen no gasta tu plan.

Claude lo recibe con `--mcp-config` cuando su agente tiene «Puede delegar en el modelo local» (config
`delegate_local`). Herramientas (Claude las ve como `mcp__local__<nombre>`):
- `local_ask`: pensar, resumir, comparar, explicar, revisar. Los archivos los lee ESTE servidor del worktree y se
  los pasa a Qwen: Claude no gasta tokens leyéndolos, solo recibe la conclusión.
- `local_write_file`: Qwen escribe un archivo entero (crear o reescribir) en el worktree. Claude recibe un resumen
  y revisa lo que quiera. Solo si la tarea puede escribir (LH_WRITE=1).
- `local_edit_file`: Qwen cambia SOLO trozos de un archivo existente (bloques buscar/reemplazar, ver edits.py):
  mucho más rápido y seguro que reescribirlo entero. Solo si LH_WRITE=1.
- `local_map`: el esquema del repo (archivos con sus funciones, selectores, ids…; repomap.py), sin modelo: así
  Claude planifica sin leer archivos enteros.
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

Varios modelos locales (p. ej. uno por GPU): LH_LOCAL_SERVERS (JSON [{id, name, role, device, url, key}]). Cada
encargo va al servidor cuyo papel encaja (`fuerte`: escribir y `local_agent`; `rapido`: preguntas e investigar;
`general`: todo) y Claude puede elegir otro con el argumento `server`. Si el elegido no contesta, se prueba el
siguiente. Sin LH_LOCAL_SERVERS, un solo servidor: LH_LOCAL_URL.

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
import threading
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
        "Devuelve su respuesta en texto. Es un modelo pequeño: verifica lo que sea crítico. Solo ve `task` y "
        "`files`: no ve el repositorio por su cuenta ni recuerda encargos anteriores (pásale otra vez lo que "
        "necesite), y no escribe archivos ni ejecuta nada."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Qué quieres que haga, con todo el contexto necesario"},
            "files": {"type": "array", "items": {"type": "string"},
                      "description": "Rutas (relativas al repo) que debe leer"},
        },
        "required": ["task"],
    },
    "annotations": {"readOnlyHint": True},  # así Claude Code puede lanzar varias a la vez (una a cada modelo)
}
WRITE = {
    "name": "local_write_file",
    "description": (
        "Encarga a un modelo local GRATIS escribir un archivo COMPLETO (nuevo o reescrito) según tus instrucciones. "
        "Lo escribe él en disco y tú recibes un resumen: ahorra los tokens de generar el código. Da instrucciones "
        "precisas (qué debe contener, funciones y firmas, estilo, casos límite). Revisa después lo importante con "
        "Read y corrige con Edit. Si el archivo existe, el modelo lo ve y lo reescribe entero: para cambiar una "
        "parte de un archivo que ya existe usa `local_edit_file`, que es mucho más rápido y no pierde líneas."),
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

EDIT = {
    "name": "local_edit_file",
    "description": (
        "Encarga a un modelo local GRATIS cambiar SOLO una parte de un archivo que ya existe (añadir una entrada, "
        "cambiar una función, una regla CSS…): devuelve únicamente los trozos que cambian y este servidor los aplica. "
        "Mucho más rápido que reescribirlo y no se come el resto del archivo. Di exactamente qué cambiar y dónde."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Archivo a cambiar (relativo al repo; tiene que existir)"},
            "instructions": {"type": "string", "description": "Qué cambiar y dónde, con el texto nuevo si lo sabes"},
            "context_files": {"type": "array", "items": {"type": "string"},
                              "description": "Otros archivos que debe leer para hacerlo bien"},
        },
        "required": ["path", "instructions"],
    },
}
MAP = {
    "name": "local_map",
    "description": (
        "Esquema del repositorio sin gastar cuota ni modelo: cada archivo con sus funciones/clases, selectores CSS, "
        "ids y títulos HTML o exports JS, y su tamaño. Úsalo ANTES de leer archivos para planificar: muchas veces "
        "basta y te ahorras los Read. `paths` limita a unas carpetas o archivos."),
    "inputSchema": {
        "type": "object",
        "properties": {"paths": {"type": "array", "items": {"type": "string"},
                                 "description": "Carpetas o archivos (por defecto, todo el repo)"}},
    },
    "annotations": {"readOnlyHint": True},
}

MODELS = {
    "name": "local_models",
    "description": (
        "Qué modelo local hay cargado en cada GPU y qué modelos hay en el armario con lo que sabe hacer cada uno "
        "(programar, planificar, ver imágenes, embeddings…) y lo que tardan en cargar. Sin modelo y sin cuota."),
    "inputSchema": {"type": "object", "properties": {}},
    "annotations": {"readOnlyHint": True},
}
USE = {
    "name": "local_use",
    "description": (
        "Pide una CAPACIDAD a los modelos locales («vision» para leer imágenes o capturas, «plan», «code», "
        "«embed»…): LocalHarness elige el modelo del armario que la tiene y cabe, cambia el de una GPU si hace "
        "falta (espera a que acabe lo que esté haciendo; tarda lo que tarde en cargar) y te dice cuál quedó. "
        "Úsalo antes de `local_read_documents` o `local_look` si el modelo cargado no ve imágenes."),
    "inputSchema": {
        "type": "object",
        "properties": {"capability": {"type": "string", "enum": ["plan", "code", "review", "vision", "ocr", "embed",
                                                                 "draft", "tools", "thinking", "fast"]},
                       "server": {"type": "string", "description": "En qué servidor (opcional)"}},
        "required": ["capability"],
    },
}
PLAN_LOCAL = {
    "name": "local_plan",
    "description": (
        "El modelo local PLANIFICA por ti (gratis): parte la tarea en bloques pequeños (un archivo o una edición "
        "cada uno, con `after`) en el formato de `local_execute_plan`, mirando el mapa del repo y los archivos que "
        "le pases. Revisar un plan te cuesta mucho menos que escribirlo: léelo, corrígelo si hace falta y pásalo "
        "a `local_execute_plan`. Con `execute: true` lo ejecuta directamente (para parches de plantilla)."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "La tarea entera, con criterios de aceptación"},
            "files": {"type": "array", "items": {"type": "string"}, "description": "Archivos que debe leer"},
            "execute": {"type": "boolean", "description": "Ejecutarlo en cuanto esté (por defecto, no)"},
            "check": {"type": "string", "description": "Orden de tests si se ejecuta"},
        },
        "required": ["task"],
    },
}
DOCS = {
    "name": "local_read_documents",
    "description": (
        "Un modelo local GRATIS lee documentos y contesta una pregunta sobre ellos: PDF con texto, PDF escaneado o "
        "imágenes (con un modelo de visión: pide antes `local_use` con «vision» si no hay uno cargado), Markdown o "
        "texto. Varios documentos: resume cada uno y luego responde con todos."),
    "inputSchema": {
        "type": "object",
        "properties": {"paths": {"type": "array", "items": {"type": "string"}},
                       "question": {"type": "string", "description": "Qué quieres saber de ellos"}},
        "required": ["paths", "question"],
    },
    "annotations": {"readOnlyHint": True},
}
LOOK = {
    "name": "local_look",
    "description": (
        "Revisión VISUAL de páginas web del repo: hace capturas (escritorio y móvil) con Chrome sin ventana y un "
        "modelo local con visión dice si se ve como se pidió y si hay algo roto (solapado, cortado, ilegible, "
        "vacío). Gratis. Necesita un modelo con visión cargado (`local_use` con «vision»)."),
    "inputSchema": {
        "type": "object",
        "properties": {"pages": {"type": "array", "items": {"type": "string"},
                                 "description": "Páginas .html (rutas relativas)"},
                       "question": {"type": "string", "description": "Qué debería verse (lo pedido en el parche)"},
                       "mobile": {"type": "boolean", "description": "También en móvil (por defecto, sí)"}},
        "required": ["pages", "question"],
    },
    "annotations": {"readOnlyHint": True},
}
SEARCH = {
    "name": "local_search",
    "description": (
        "Busca en el repo los trozos de código o texto más PARECIDOS EN SIGNIFICADO a lo que describes "
        "(embeddings con un modelo local; gratis). Mejor que Grep cuando no sabes cómo se llama algo: «dónde se "
        "guarda el modo noche», «qué test comprueba el pie»."),
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}, "k": {"type": "integer", "description": "Cuántos (5)"}},
        "required": ["query"],
    },
    "annotations": {"readOnlyHint": True},
}

BLOCK = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Identificador corto del bloque (p. ej. «1», «calc»)"},
        "title": {"type": "string", "description": "Qué es el bloque, en pocas palabras"},
        "kind": {"type": "string", "enum": ["edit", "write", "ask"],
                 "description": "edit = cambiar SOLO una parte del archivo `path`, que ya existe (lo normal para "
                                "añadir o retocar); write = crear `path` o reescribirlo entero; ask = pregunta o "
                                "análisis en texto"},
        "path": {"type": "string", "description": "Solo edit/write: archivo (relativo al repo)"},
        "instructions": {"type": "string",
                         "description": "Instrucciones autocontenidas: qué hacer, firmas, casos límite, estilo"},
        "files": {"type": "array", "items": {"type": "string"},
                  "description": "Archivos que debe leer (incluye los que escriban bloques anteriores si dependen)"},
        "after": {"type": "array", "items": {"type": "string"},
                  "description": "ids de los bloques ANTERIORES que tienen que estar hechos antes que este ([] = no "
                                 "depende de ninguno). Si algún bloque lo lleva, los que no dependen entre sí se "
                                 "hacen A LA VEZ; si ninguno lo lleva, van en orden, uno tras otro"},
    },
    "required": ["instructions"],
}
PLAN = {
    "name": "local_execute_plan",
    "description": (
        "Encarga a un modelo local GRATIS un PLAN ENTERO de una vez: una lista de bloques (archivos a cambiar, crear "
        "o reescribir y preguntas/análisis), cada uno leyendo él los archivos que le indiques. Para un archivo que ya "
        "existe usa `kind: edit` (solo los trozos que cambian; un `write` sobre un archivo grande se hace solo como "
        "`edit`). Pon en cada bloque "
        "`after` (de qué bloques anteriores depende; [] si de ninguno) y los independientes se harán a la vez, "
        "repartidos entre los modelos locales: mucho más rápido. Sin `after`, van en orden. Opcionalmente ejecuta "
        "al final una orden de comprobación (tests) y te devuelve su salida. Cada bloque va al modelo que esté "
        "libre (`server` solo desempata). Un bloque de tests espera a los archivos que nombre en sus instrucciones "
        "o en `files`, y los lee: nómbralos. Si la comprobación falla y el error señala un archivo del plan, el modelo "
        "local intenta arreglarlo solo (una ronda) antes de devolvértelo. Recibes un informe por bloque: léelo, comprueba lo crítico y, si "
        "aún falla, vuelve a llamarla solo con el bloque culpable e instrucciones exactas."),
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
    "annotations": {"readOnlyHint": True},
}

AGENT = {
    "name": "local_agent",
    "description": (
        "Encarga una TAREA ENTERA de programación a un agente local GRATIS que trabaja solo en este repositorio: "
        "lee los archivos, los modifica y ejecuta los tests. Dale una tarea concreta y autocontenida: qué cambiar, "
        "en qué archivos, criterios de aceptación y qué orden de tests ejecutar. Te devuelve su resumen y los "
        "archivos que cambió: revísalos tú (Read) y comprueba con `run_checks`. ÚSALO POCO: el 08/10 se atascó "
        "releyendo en la mayoría de encargos (93 min perdidos). NO lo uses para arreglar un test o archivo que "
        "falla ni para añadir entradas: para eso, `local_edit_file` o un bloque `edit` con la salida del error. Se "
        "para solo si pasa varios pasos sin escribir nada."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "La tarea completa, con criterios de aceptación"},
            "files": {"type": "array", "items": {"type": "string"},
                      "description": "Archivos por los que debe empezar (rutas relativas)"},
            "max_turns": {"type": "integer", "description": "Tope de pasos del agente (por defecto 15, máx. 30)"},
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
    "annotations": {"readOnlyHint": True},
}

# herramientas del agente local (local_agent) que Claude o tú podéis quitarle o darle; las de control van siempre
WORKER_TOOLS = {"leer_archivo": "leer archivos", "listar": "listar carpetas", "buscar_texto": "buscar en el código",
                "editar_archivo": "cambiar trozos de archivos", "escribir_archivo": "escribir archivos",
                "ejecutar": "ejecutar tests",
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
              "español, concreto y sin relleno. Solo conoces lo que viene en este mensaje: no ves el repositorio "
              "salvo los ARCHIVOS incluidos y no recuerdas encargos anteriores. Si te faltan datos o archivos, dilo "
              "en vez de inventar: nunca supongas nombres de archivos, carpetas ni dependencias que no veas aquí.")
NO_FILES = (" En este encargo NO te han pasado ningún archivo del repositorio. Si la tarea es sobre el repo o sobre sus archivos, "
            "NO la contestes de memoria: responde solo «Necesito que me pases los archivos en `files`».")
SYSTEM_WRITE = ("Eres un programador. Devuelve ÚNICAMENTE el contenido completo del archivo pedido, dentro de un solo "
                "bloque de código, sin explicaciones antes ni después. No dejes partes sin hacer ni «...».")
SYSTEM_RESEARCH = ("Eres un investigador. Responde a la pregunta SOLO con lo que digan las fuentes que te paso, en "
                   "español, concreto y sin relleno. Cita las fuentes como [1], [2]… Si no lo dicen, dilo claramente.")
SEARCH_URL = "https://html.duckduckgo.com/html/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LocalHarness/0.1"
MAX_PAGE_CHARS = 8000
MAX_BLOCKS = 20
# si la comprobación del plan falla, cuántas veces lo intenta arreglar el modelo local solo. Eran 2: el 08/10
# (parches 10-27) saltó 27 veces, gastó 77 min de GPU y arregló UNA: casi siempre el fallo estaba en otro archivo
AUTO_FIX_ROUNDS = 1
EDIT_OVER_CHARS = 6000  # un bloque `write` sobre un archivo existente más grande que esto se hace como `edit`
EDIT_RETRIES = 1  # si los trozos no encajan, se le devuelve el error y lo intenta otra vez
WRITES = ("write", "edit")  # bloques del plan que cambian archivos
AGENT_IDLE_TURNS = 8  # `local_agent` se para si pasa más pasos seguidos que esto sin escribir nada
# órdenes que `local_execute_plan` puede ejecutar como comprobación (sin shell; prefijos, como en local_agent)
CHECK_COMMANDS = ["python -m unittest", "python -m pytest", "pytest", "npm test", "npm run test", "npm run lint",
                  "ruff check", "node --test"]
CHECK_TIMEOUT_S = 300
MAX_CHECK_CHARS = 4000
ENV_DROP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "LH_LOCAL_KEY")


JUNK_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", ".venv"}


# qué papel de servidor prefiere cada tipo de encargo (en orden); `general` vale para todo
LIGHT = ("rapido", "general", "fuerte")
HEAVY = ("fuerte", "general", "rapido")
TOOL_WEIGHT = {"local_ask": LIGHT, "local_research": LIGHT, "local_write_file": HEAVY, "local_agent": HEAVY,
               "local_edit_file": HEAVY, "local_execute_plan/ask": LIGHT, "local_execute_plan/write": HEAVY,
               "local_execute_plan/edit": HEAVY, "local_plan": HEAVY, "local_read_documents": LIGHT,
               "local_look": LIGHT}
ROLE_TEXT = {"fuerte": "escribir código y tareas enteras", "rapido": "preguntas, resúmenes e investigar",
             "general": "de todo"}
SERVER_TOOLS = ("local_ask", "local_write_file", "local_edit_file", "local_execute_plan", "local_research",
                "local_agent", "local_plan", "local_read_documents", "local_look")


def thinking_body(level: str | None, effort: str | None = None) -> dict:
    """Pensamiento del servidor (Ajustes → servidores locales) en cada petición; igual que adapters.local.
    `effort`: lo que pide el encargo a los modelos con reasoning_effort (gpt-oss) si el servidor está en «normal»."""
    from localharness.adapters.local import thinking_body as base
    return base(level, effort)


LOAD_WAIT_S = 420  # cuánto espera un encargo a un modelo que está cargando (gpt-oss-20b: ~185 s)
LOAD_POLL_S = 5


class ToolError(Exception):
    pass


class NoModel(ToolError):
    """No hay llama-server que conteste: no tiene sentido seguir con más bloques."""


def _per_call(name: str, default):
    """Atributo propio de cada encargo: con varios modelos locales, Claude puede pedir dos cosas a la vez y cada
    `tools/call` va en su hilo (main), así que a qué servidor va y qué hace no se pueden compartir."""
    def get(self):
        if not hasattr(self._tl, name):
            setattr(self._tl, name, default(self))
        return getattr(self._tl, name)

    def put(self, value):
        setattr(self._tl, name, value)
    return property(get, put)


class Server:
    url = _per_call("url", lambda self: self._default["url"])
    key = _per_call("key", lambda self: self._default.get("key") or "")
    server_id = _per_call("server_id", lambda self: self._default["id"])
    order = _per_call("order", lambda self: [])  # servidores a probar en el encargo en curso (el primero, el elegido)
    current = _per_call("current", lambda self: {})  # encargo en curso (para el directo)

    def __init__(self, env: dict[str, str] | None = None, transport=None, http_get=None):
        env = env if env is not None else dict(os.environ)
        self._tl = threading.local()
        self._lock = threading.Lock()  # log y directo: los escriben varios encargos a la vez
        self._live_by: dict[str, dict] = {}  # el directo de cada modelo local (id del servidor → lo último)
        url = (env.get("LH_LOCAL_URL") or "http://127.0.0.1:8080").rstrip("/").removesuffix("/v1")
        try:
            servers = json.loads(env["LH_LOCAL_SERVERS"]) if env.get("LH_LOCAL_SERVERS") else []
        except ValueError:
            servers = []
        servers = [srv for srv in servers if isinstance(srv, dict) and srv.get("url") and srv.get("id")]
        if not servers:
            servers = [{"id": "principal", "name": "Principal", "role": "general", "url": url,
                        "key": env.get("LH_LOCAL_KEY") or ""}]
        self.servers = [{**srv, "url": str(srv["url"]).rstrip("/").removesuffix("/v1"), "key": srv.get("key") or "",
                         "role": srv.get("role") or "general"} for srv in servers]
        self._default = self.servers[0]
        self._inflight = {srv["id"]: 0 for srv in self.servers}  # encargos en curso de cada modelo (reparto por cola)
        self._models: dict[str, str | None] = {}
        self._ctx: dict[str, int | None] = {}  # contexto por ranura de cada servidor (/props)
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
        self.agent_turns = int(env.get("LH_AGENT_TURNS") or 15)
        self.agent_timeout = float(env.get("LH_AGENT_TIMEOUT") or 1200)
        self.worker_path = Path(env["LH_WORKER"]) if env.get("LH_WORKER") else None
        self.skills_path = Path(env["LH_SKILLS"]) if env.get("LH_SKILLS") else None
        self.live_path = Path(env["LH_LIVE"]) if env.get("LH_LIVE") else None
        self.api = (env.get("LH_API") or "").rstrip("/")  # la API de LocalHarness (cambiar de modelo)
        self.embed_url = (env.get("LH_EMBED_URL") or "").rstrip("/")  # llama-server de embeddings (RAG)
        self.auto_swap = env.get("LH_AUTO_SWAP") == "1"  # cambiar solo de modelo cuando un encargo lo necesita
        self.api_call = None  # pruebas: función (método, ruta, cuerpo) -> JSON, en vez de la API de verdad
        self.embed_post = None  # pruebas: función (url, cuerpo) -> JSON de /v1/embeddings
        self.transport = transport  # pruebas: función (body) -> respuesta JSON de /v1/chat/completions
        self.http_get = http_get or _http_get  # pruebas: función (url, data) -> HTML; sin red de verdad

    # --- protocolo
    def tools(self) -> list[dict]:
        prepare = [self.prepare_tool()] if self.worker_path else []
        tools = (prepare + [MAP, ASK] + ([EDIT, WRITE, PLAN, PLAN_LOCAL, AGENT] if self.write else [])
                 + ([CHECKS] if self.commands != [] else []) + ([RESEARCH] if self.web else [])
                 + [DOCS, LOOK] + ([SEARCH] if self.embed_url else []) + ([MODELS, USE] if self.api else []))
        return [self.with_server(t) for t in tools] if len(self.servers) > 1 else tools

    # --- varios modelos locales
    def use(self, srv: dict) -> None:
        self.url, self.key, self.server_id = srv["url"], srv.get("key") or "", srv["id"]

    def route(self, kind: str, wanted=None) -> list[dict]:
        """Orden en que probar los servidores para un encargo: el que pidió Claude (`server`) o el de papel más
        adecuado primero; los demás detrás por si el primero no contesta."""
        prefs = TOOL_WEIGHT.get(kind, LIGHT)
        order = sorted(self.servers, key=lambda srv: prefs.index(srv["role"]) if srv["role"] in prefs else 9)
        if wanted:
            chosen = [srv for srv in self.servers if srv["id"] == str(wanted)]
            if not chosen:
                raise ToolError(f"no hay ningún modelo local llamado {wanted!r}; usa uno de: "
                                f"{', '.join(srv['id'] for srv in self.servers)}")
            order = chosen + [srv for srv in order if srv is not chosen[0]]
        return order

    def claim(self, kind: str, wanted=None) -> list[dict]:
        """Como `route`, pero mirando la cola: va primero el modelo con menos encargos en curso (a igualdad, el
        elegido o el de su papel) y se le apunta este. El 08/10 Claude mandó 12 de 13 bloques al rápido y el fuerte
        se quedó 5 min parado: los dos van a ~25-30 tok/s, así que esperar en cola nunca compensa. Suéltalo con
        `release`."""
        order = self.route(kind, wanted)
        with self._lock:
            rank = {srv["id"]: i for i, srv in enumerate(order)}
            order = sorted(order, key=lambda srv: (self._inflight.get(srv["id"], 0), rank[srv["id"]]))
            self._inflight[order[0]["id"]] = self._inflight.get(order[0]["id"], 0) + 1
        return order

    def release(self, server_id: str) -> None:
        with self._lock:
            self._inflight[server_id] = max(0, self._inflight.get(server_id, 0) - 1)

    def model_of(self, srv: dict) -> str | None:
        """Qué GGUF tiene cargado (para que Claude sepa con quién habla). Se pregunta una vez; None si no contesta."""
        if srv["id"] not in self._models:
            req = urllib.request.Request(srv["url"] + "/v1/models")
            if srv.get("key"):
                req.add_header("Authorization", f"Bearer {srv['key']}")
            try:
                with urllib.request.urlopen(req, timeout=2) as r:
                    self._models[srv["id"]] = _short((json.loads(r.read()).get("data") or [{}])[0].get("id"))
            except (OSError, ValueError):
                self._models[srv["id"]] = None
        return self._models[srv["id"]]

    def servers_text(self) -> str:
        lines = []
        for srv in self.servers:
            model = self.model_of(srv) if not self.transport else None
            where = f", {srv['device']}" if srv.get("device") else ""
            lines.append(f"«{srv['id']}» ({model or 'apagado o sin datos'}{where}): {ROLE_TEXT.get(srv['role'], '')}")
        return ("Hay varios modelos locales y se trabaja con todos a la vez: " + "; ".join(lines) + ". Si no indicas "
                "`server`, cada encargo va al que mejor encaja por su papel (y si no contesta, al otro).")

    def with_server(self, tool: dict) -> dict:
        if tool["name"] not in SERVER_TOOLS:
            return tool
        prop = {"type": "string", "enum": [srv["id"] for srv in self.servers],
                "description": "Qué modelo local lo hace (opcional; por defecto, el que encaja por su papel)"}
        schema = {**tool["inputSchema"], "properties": {**tool["inputSchema"]["properties"], "server": prop}}
        if tool["name"] == "local_execute_plan":  # en un plan, cada bloque puede ir a un modelo distinto
            block = {**BLOCK, "properties": {**BLOCK["properties"], "server": prop}}
            schema["properties"]["blocks"] = {**schema["properties"]["blocks"], "items": block}
        desc = tool["description"]
        if tool["name"] == "local_ask":
            desc += " " + self.servers_text()
        return {**tool, "description": desc, "inputSchema": schema}

    def first_up(self, order: list[dict]) -> dict:
        """El primero que contesta (/health). Para `local_agent`, que hace muchas peticiones seguidas."""
        if self.transport or len(order) == 1:
            return order[0]
        for srv in order:
            try:
                with urllib.request.urlopen(srv["url"] + "/health", timeout=2):
                    return srv
            except urllib.error.HTTPError:
                return srv  # 503 = cargando: estará listo enseguida
            except (OSError, ValueError):
                continue
        return order[0]

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
        claimed = None
        self.current = {"tool": name, "task": str(args.get("task") or args.get("path") or args.get("question")
                                                  or args.get("command") or "")[:300]}
        try:
            if name in SERVER_TOOLS and name != "local_execute_plan":  # el plan reparte bloque a bloque
                self.order = self.claim(name, args.get("server"))
                claimed = self.order[0]["id"]
                self.use(self.order[0])
                self.current["server"] = self.server_id
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
            elif name == "local_edit_file" and self.write:
                entry["path"] = str(args.get("path", ""))
                text, stats = self.edit_file(str(args.get("path") or ""), str(args.get("instructions") or ""),
                                             args.get("context_files") or [])
            elif name == "local_models" and self.api:
                text, stats = self.models_text(), {}
            elif name == "local_use" and self.api:
                entry["task"] = str(args.get("capability") or "")
                text, stats = self.use_capability(str(args.get("capability") or ""), args.get("server"))
            elif name == "local_plan" and self.write:
                entry["task"] = str(args.get("task", ""))[:300]
                text, stats = self.plan(str(args.get("task") or ""), args.get("files") or [],
                                        bool(args.get("execute")), str(args.get("check") or ""))
            elif name == "local_read_documents":
                entry["task"] = str(args.get("question", ""))[:300]
                text, stats = self.read_documents(args.get("paths") or [], str(args.get("question") or ""))
            elif name == "local_look":
                entry["task"] = str(args.get("question", ""))[:300]
                text, stats = self.look(args.get("pages") or [], str(args.get("question") or ""),
                                        args.get("mobile", True) is not False)
            elif name == "local_search" and self.embed_url:
                entry["task"] = str(args.get("query", ""))[:300]
                text, stats = self.search_repo(str(args.get("query") or ""), args.get("k"))
            elif name == "local_map":
                from localharness.repomap import repo_map
                entry["task"] = ", ".join(str(x) for x in args.get("paths") or []) or "todo el repo"
                text = repo_map(self.root, [str(x) for x in args.get("paths") or []])
                stats = {"chars": len(text)}
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
            if len(self.servers) > 1 and name in SERVER_TOOLS and name != "local_execute_plan":
                entry.setdefault("server", self.server_id)
            return {"content": [{"type": "text", "text": text}]}
        except ToolError as e:
            msg = self.fallback(str(e))
            entry.update(ok=False, error=msg)
            if len(self.servers) > 1 and name in SERVER_TOOLS and name != "local_execute_plan":
                entry.setdefault("server", self.server_id)
            return {"content": [{"type": "text", "text": f"No se pudo: {msg}"}], "isError": True}
        finally:
            if claimed:
                self.release(claimed)
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
        answer, stats = self.complete(SYSTEM_ASK + ("" if ctx else NO_FILES), user)
        return answer, {**stats, "files": read}

    def write_file(self, path: str, instructions: str, context_files: list) -> tuple[str, dict]:
        if not instructions.strip():
            raise ToolError("faltan `instructions`")
        target = self.safe(path)
        old = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
        ctx, read = self.read_files([f for f in context_files if f != path])
        user = f"ARCHIVO A ESCRIBIR: {path}\n\nINSTRUCCIONES:\n{instructions}"
        if old is not None:
            user += f"\n\nCONTENIDO ACTUAL (reescríbelo entero):\n```\n{old[: self.input_budget()]}\n```"
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

    def edit_file(self, path: str, instructions: str, context_files: list) -> tuple[str, dict]:
        """El modelo devuelve solo los trozos que cambian (edits.py) y se aplican aquí. Si no encajan, se le
        devuelve el error con las líneas más parecidas y lo intenta otra vez (EDIT_RETRIES)."""
        # aquí y no arriba: la CLI de Claude lanza este archivo por ruta y el paquete entra en el path en main()
        from localharness.edits import SYSTEM_EDIT, EditError, apply_edits, parse_edits
        if not instructions.strip():
            raise ToolError("faltan `instructions`")
        target = self.safe(path)
        if not target.is_file():
            raise ToolError(f"{path} no existe: para crearlo usa `local_write_file` (o un bloque `write`)")
        old = target.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        ctx, read = self.read_files([f for f in context_files if f != path])
        budget = self.input_budget()
        if len(old) > budget:
            raise ToolError(f"{path} es demasiado grande para el contexto del modelo local ({len(old)} caracteres); "
                            "pártelo o hazlo tú")
        user = (f"ARCHIVO A CAMBIAR: {path}\n\nINSTRUCCIONES:\n{instructions}\n\nCONTENIDO ACTUAL:\n```\n{old}\n```")
        if ctx:
            user += f"\n\nARCHIVOS DE CONTEXTO:\n{ctx}"
        stats: dict = {}
        tokens = 0
        for attempt in range(EDIT_RETRIES + 1):
            raw, stats = self.complete(SYSTEM_EDIT, user)
            tokens += int(stats.get("completion_tokens") or 0)
            try:
                new, n = apply_edits(old, parse_edits(raw))
                break
            except EditError as e:
                if attempt == EDIT_RETRIES:
                    raise ToolError(f"los cambios del modelo local no encajan en {path}: {e}") from None
                user += (f"\n\nTU RESPUESTA ANTERIOR NO SE PUDO APLICAR: {e}\nRepite los bloques copiando BUSCAR "
                         "exactamente del CONTENIDO ACTUAL.")
        if not new.strip():
            raise ToolError("el cambio dejaba el archivo vacío; no se aplicó")
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(new if new.endswith("\n") else new + "\n")
        diff = short_diff(old, new, path)
        return (f"Cambiado {path}: {n} trozo(s), {diff['added']} líneas añadidas y {diff['removed']} quitadas. Lo hizo "
                f"el modelo local; el cambio:\n```diff\n{diff['text']}\n```"), {
                    **stats, "completion_tokens": tokens, "files": read, "edits": n, "attempts": attempt + 1}

    # --- armario de modelos (la API de LocalHarness cambia el modelo de cada GPU)
    def _api(self, method: str, path: str, body: dict | None = None, timeout: float = 900) -> dict:
        if self.api_call:
            return self.api_call(method, path, body)
        req = urllib.request.Request(self.api + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("detail")
            except ValueError:
                detail = None
            raise ToolError(f"LocalHarness: {detail or f'HTTP {e.code}'}") from None
        except (OSError, ValueError) as e:
            raise ToolError(f"no contesta LocalHarness en {self.api}: {e}") from None

    def models_text(self) -> str:
        info = self._api("GET", "/api/llama/profiles")
        status = self._api("GET", "/api/llama")
        lines = [f"Topología: {info.get('topology') or 'separado'}.", "Cargados ahora:"]
        for srv in status.get("servers") or []:
            st = srv.get("status") or {}
            lines.append(f"- «{srv['id']}» ({srv.get('device') or 'auto'}): {srv.get('model_name') or 'apagado'} "
                         f"[{st.get('state')}]")
        lines.append("Armario (capacidades · dónde cabe entero · segundos de carga):")
        for p in info.get("profiles") or []:
            where = ", ".join(k for k, v in (p.get("fits") or {}).items() if v.get("fit") == "gpu") or "en ninguna sola"
            load = f" · {p['load_s']:.0f} s" if p.get("load_s") else ""
            lines.append(f"- {p['name']} ({p['size_gb']} GB): {', '.join(p['caps']) or '—'} · {where}{load}")
        return "\n".join(lines)

    def use_capability(self, cap: str, server) -> tuple[str, dict]:
        if not cap:
            raise ToolError("falta `capability`")
        r = self._api("POST", "/api/llama/use", {"capability": cap, "server": server or None})
        self._models.pop(r.get("server"), None)
        self._ctx.pop(r.get("server"), None)
        verb = "Cargado" if r.get("changed") else "Ya estaba cargado"
        return (f"{verb} {r.get('model')} en «{r.get('server')}» para «{cap}». Los encargos que pidan ese servidor "
                f"(`server`) lo usan."), {"server": r.get("server"), "model": r.get("model"), "changed": r.get("changed")}

    # --- el modelo local planifica (P8), con JSON garantizado (P9)
    def plan(self, task: str, files: list, execute: bool, check: str) -> tuple[str, dict]:
        from localharness.repomap import repo_map
        if not task.strip():
            raise ToolError("falta `task`")
        ctx, read = self.read_files(files)
        user = (f"TAREA:\n{task}\n\nMAPA DEL REPO:\n{repo_map(self.root)[:12000]}"
                + (f"\n\nARCHIVOS:\n{ctx}" if ctx else ""))
        errors: list[str] = []
        stats: dict = {}
        blocks: list = []
        for _ in range(2):
            raw, stats = self.complete(SYSTEM_PLAN, user + (
                "\n\nTU PLAN ANTERIOR TENÍA ESTOS ERRORES, corrígelos:\n- " + "\n- ".join(errors) if errors else ""),
                schema=PLAN_SCHEMA, effort="medium")
            try:
                blocks = json.loads(strip_fence(raw)).get("blocks") or []
            except (ValueError, AttributeError):
                blocks, errors = [], ["la respuesta no era un JSON con `blocks`"]
                continue
            errors = validate_plan(blocks, self.root)
            if not errors:
                break
        if errors:
            raise ToolError("el plan del modelo local no vale: " + "; ".join(errors[:5]) + ". Planifícalo tú")
        stats = {**stats, "files": read, "blocks": len(blocks)}
        listing = "\n".join(f"- {b['id']} [{b['kind']}] {b.get('path') or ''} ← after {b.get('after') or []}: "
                            f"{str(b.get('title') or b['instructions'])[:100]}" for b in blocks)
        if not execute:
            return (f"Plan del modelo local ({len(blocks)} bloques):\n{listing}\n\nJSON para `local_execute_plan` "
                    f"(revísalo y corrígelo si hace falta):\n```json\n{json.dumps(blocks, ensure_ascii=False)}\n```"), stats
        text, run = self.execute_plan(blocks, check)
        return f"Plan del modelo local ({len(blocks)} bloques):\n{listing}\n\n{text}", {**stats, **run}

    # --- documentos e imágenes (P14) y revisión visual (P15)
    def vision_complete(self, question: str, images: list[Path], extra_text: str = "") -> tuple[str, dict]:
        from localharness.vision import image_part
        parts = [{"type": "text", "text": question + (f"\n\n{extra_text}" if extra_text else "")}]
        parts += [image_part(p) for p in images]
        try:
            return self.complete(SYSTEM_ASK, parts)
        except ToolError as e:
            if not any(w in str(e).lower() for w in ("image", "mmproj", "multimodal")):
                raise
            if not (self.auto_swap and self.api):
                raise ToolError("el modelo cargado no ve imágenes: pide antes `local_use` con «vision»") from None
        # gestor de turnos (P16, Ajustes → llama.auto_swap): carga él mismo un modelo con visión y lo reintenta
        _, got = self.use_capability("vision", None)
        srv = next((x for x in self.servers if x["id"] == got.get("server")), None)
        if srv:
            self.order = [srv]
            self.use(srv)
        return self.complete(SYSTEM_ASK, parts)

    def read_documents(self, paths: list, question: str) -> tuple[str, dict]:
        import tempfile

        from localharness import vision
        if not question.strip() or not paths:
            raise ToolError("faltan `paths` y `question`")
        answers, stats = [], {}
        with tempfile.TemporaryDirectory(prefix="lh-docs-") as tmp:
            for rel in [p for p in paths if isinstance(p, str)][:10]:
                p = self.safe(rel)
                if not p.is_file():
                    answers.append(f"### {rel}\n(no existe)")
                    continue
                ext = p.suffix.lower()
                try:
                    if ext in vision.IMAGE_EXT:
                        a, stats = self.vision_complete(question, [p])
                    elif ext == ".pdf":
                        pages = vision.pdf_text(p)
                        scanned = [i for i, t in enumerate(pages) if len(t) < vision.MIN_TEXT_PER_PAGE]
                        text = "\n\n".join(f"[pág. {i + 1}]\n{t}" for i, t in enumerate(pages) if t)
                        if scanned:
                            imgs = vision.pdf_page_images(p, scanned[:8], Path(tmp))
                            a, stats = self.vision_complete(question, imgs, f"TEXTO DE LAS OTRAS PÁGINAS:\n{text[:self.input_budget() // 2]}" if text else "")
                        else:
                            a, stats = self.complete(SYSTEM_ASK, f"{question}\n\nDOCUMENTO {rel}:\n{text[:self.input_budget()]}")
                    elif ext in vision.TEXT_EXT:
                        a, stats = self.ask(question, [rel])
                    else:
                        a = f"(no sé leer {ext})"
                except vision.VisionError as e:
                    a = f"(no se pudo: {e})"
                answers.append(f"### {rel}\n{a}")
        if len(answers) > 1:
            joined = "\n\n".join(answers)
            final, stats = self.complete(SYSTEM_ASK, f"{question}\n\nRESPUESTAS POR DOCUMENTO:\n{joined}\n\n"
                                                     "Responde a la pregunta con todo junto, diciendo de qué documento sale cada cosa.")
            return final + "\n\n---\n" + joined, {**stats, "documents": len(answers)}
        return answers[0], {**stats, "documents": 1}

    def look(self, pages: list, question: str, mobile: bool) -> tuple[str, dict]:
        import tempfile

        from localharness import vision
        if not pages or not question.strip():
            raise ToolError("faltan `pages` y `question`")
        out, stats = [], {}
        with tempfile.TemporaryDirectory(prefix="lh-look-") as tmp:
            for rel in [p for p in pages if isinstance(p, str)][:6]:
                p = self.safe(rel)
                if not p.is_file():
                    out.append(f"### {rel}\n(no existe)")
                    continue
                shots = []
                try:
                    for name, size in vision.VIEWPORTS.items():
                        if name == "móvil" and not mobile:
                            continue
                        shots.append(vision.screenshot(p, Path(tmp) / f"{p.stem}-{len(shots)}.png", size))
                except vision.VisionError as e:
                    raise ToolError(str(e)) from None
                ask = (f"Son capturas de la página {rel} (" + " y ".join(n for n in vision.VIEWPORTS
                                                                         if n != "móvil" or mobile) + "). "
                       f"Lo que debería verse: {question}\n¿Se ve así? Señala solo problemas concretos y visibles: "
                       "elementos solapados, cortados o fuera de la pantalla, texto ilegible o sin contraste, partes "
                       "vacías, imágenes rotas. Si está bien, dilo en una línea.")
                a, stats = self.vision_complete(ask, shots)
                out.append(f"### {rel}\n{a}")
        return "\n\n".join(out), {**stats, "pages": len(out)}

    # --- RAG (P12)
    def search_repo(self, query: str, k) -> tuple[str, dict]:
        from localharness import rag
        if not query.strip():
            raise ToolError("falta `query`")
        try:
            n = max(1, min(15, int(k or 5)))
        except (TypeError, ValueError):
            n = 5
        try:
            hits = rag.search(self.root, query, self.embed_url, n, post=self.embed_post)
        except (OSError, ValueError, KeyError) as e:
            raise ToolError(f"no contesta el modelo de embeddings en {self.embed_url}: {e}") from None
        if not hits:
            return "Sin resultados.", {"hits": 0}
        return "\n\n".join(f"--- {h['path']}:{h['line']} (parecido {h['score']})\n{h['text'][:700]}"
                           for h in hits), {"hits": len(hits)}

    def execute_plan(self, blocks, check: str) -> tuple[str, dict]:
        """Hace los bloques con los modelos locales. Si algún bloque trae `after`, se respetan esas dependencias y
        los independientes van a la vez (cada uno a su servidor por su tipo, en su hilo); si no, en orden como
        siempre. Un bloque que falla no para el resto, pero los que dependen de él no se hacen. Sin modelo que
        conteste se para todo. Cada bloque se apunta en el log como su propio encargo; el resumen, sin tokens."""
        if not isinstance(blocks, list) or not blocks:
            raise ToolError("falta `blocks` (lista de bloques con `instructions`)")
        if len(blocks) > MAX_BLOCKS:
            raise ToolError(f"demasiados bloques ({len(blocks)}); máximo {MAX_BLOCKS} por llamada")
        items = []
        for i, b in enumerate(blocks, 1):
            b = b if isinstance(b, dict) else {"instructions": str(b)}
            path = str(b.get("path") or "")
            items.append({"b": b, "id": str(b.get("id") or i), "path": path,
                          "kind": (b.get("kind") if b.get("kind") in WRITES + ("ask",)
                                   else ("write" if path else "ask")),
                          "title": str(b.get("title") or path or str(b.get("instructions") or "")[:60]),
                          "files": [f for f in b.get("files") or [] if isinstance(f, str)]})
        ids = [it["id"] for it in items]
        if len(set(ids)) != len(ids):
            raise ToolError("hay dos bloques con el mismo `id`")
        graph = any(isinstance(it["b"].get("after"), list) for it in items)
        for k, it in enumerate(items):
            if not graph:  # como siempre: cada bloque espera al anterior
                it["after"] = [items[k - 1]["id"]] if k else []
                continue
            after = [str(a) for a in it["b"].get("after") or []]
            bad = [a for a in after if a not in ids[:k]]
            if bad:
                raise ToolError(f"el bloque {it['id']} depende de {', '.join(bad)}, que no es un bloque anterior")
            it["after"] = after
        waited = tests_after_code(items) if graph else []

        results: dict[str, tuple[bool, str]] = {}  # id → (bien, texto del informe)
        wrote = 0
        stop = threading.Event()
        stop_msg: list[str] = []

        def run(it: dict) -> tuple[bool, str]:
            entry: dict = {"tool": f"local_execute_plan/{it['kind']}", "at": time.time(), "block": it["id"],
                           "task": it["title"][:300]}
            if it["path"]:
                entry["path"] = it["path"]
            t0 = time.monotonic()
            claimed = None
            try:
                self.order = self.claim(entry["tool"], it["b"].get("server"))
                claimed = self.order[0]["id"]
                self.use(self.order[0])
                self.current = {"tool": entry["tool"], "task": it["title"][:300], "server": self.server_id}
                how = self.how_to_write(it)
                if how != it["kind"]:
                    entry["as"] = how
                instructions = str(it["b"].get("instructions") or "")
                if how == "edit":
                    try:
                        text, stats = self.edit_file(it["path"], instructions, it["files"])
                    except NoModel:
                        raise
                    except ToolError as e:
                        if it["kind"] == "edit":
                            raise
                        # era un `write` que se intentó como edición: se hace como lo pidió Claude
                        entry["as"] = f"write (la edición falló: {str(e)[:120]})"
                        text, stats = self.write_file(it["path"], instructions, it["files"])
                elif how == "write":
                    text, stats = self.write_file(it["path"], instructions, it["files"])
                else:
                    text, stats = self.ask(str(it["b"].get("instructions") or ""), it["files"])
                entry.update(stats, ok=True)
                return True, text
            except NoModel as e:
                stop_msg.append(str(e))
                stop.set()
                entry.update(ok=False, error="no hay modelo local")
                return False, str(e)
            except ToolError as e:
                entry.update(ok=False, error=str(e))
                return False, f"No se pudo: {e}"
            finally:
                if claimed:
                    self.release(claimed)
                entry["seconds"] = round(time.monotonic() - t0, 1)
                if len(self.servers) > 1:
                    entry.setdefault("server", self.server_id)
                self._log(entry)

        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
        pending = list(items)
        running: dict = {}
        most = 0
        t_plan = time.monotonic()
        with ThreadPoolExecutor(max_workers=max(2, 2 * len(self.servers)) if graph else 1) as pool:
            while pending or running:
                for it in list(pending):
                    if stop.is_set():
                        break
                    # sin `after` el orden es solo orden: un bloque malo no impide los siguientes (como siempre)
                    failed = [a for a in it["after"] if graph and a in results and not results[a][0]]
                    if failed:
                        pending.remove(it)
                        results[it["id"]] = (False, f"No se hizo: depende de {', '.join(failed)}, que falló")
                    elif all(a in results for a in it["after"]):
                        pending.remove(it)
                        running[pool.submit(run, it)] = it
                most = max(most, len(running))
                if not running:
                    break  # parado (sin modelo) o nada más que se pueda hacer
                done, _ = wait(list(running), return_when=FIRST_COMPLETED)
                for fut in done:
                    it = running.pop(fut)
                    results[it["id"]] = fut.result()
                    wrote += it["kind"] in WRITES and results[it["id"]][0]
        if stop.is_set():
            raise NoModel(stop_msg[0])

        ok = sum(1 for good, _ in results.values() if good)
        lines = []
        for it in items:
            good, text = results.get(it["id"], (False, "No se hizo"))
            lines.append(f"## Bloque {it['id']} — {it['title']} {'✅' if good else '❌'}\n{text}")
        if waited:
            lines.append("(Los tests esperaron a los archivos que comprueban y los leyeron: "
                         + "; ".join(f"{t} → {', '.join(ps)}" for t, ps in waited) + ")")
        stats = {"blocks": len(items), "ok": ok, "parallel": most, "plan_seconds": round(time.monotonic() - t_plan, 1)}
        if check.strip():
            result = self.run_check(check) if wrote else "(no se ejecutó: ningún bloque escribió archivos)"
            fixes = []
            while wrote and check_failed(result) and len(fixes) < AUTO_FIX_ROUNDS and not stop.is_set():
                fixed = self.auto_fix(check, result, items, results, run, len(fixes) + 1)
                if not fixed:
                    lines.append("(Sin arreglo automático: el error no señala ningún archivo de este plan; mira tú "
                                 "qué otro archivo hay que tocar.)")
                    break
                fixes.append(fixed)
                result = self.run_check(check)
            if fixes:
                lines.append("## Arreglo automático (modelo local, sin ti)\n" + "\n".join(
                    f"- Ronda {i}: corrigió `{path}`" + ("" if good else " (no pudo cambiarlo)")
                    for i, (path, good) in enumerate(fixes, 1))
                    + ("\nAhora la comprobación pasa." if not check_failed(result) else
                       "\nSigue fallando: reencarga tú solo el bloque culpable con instrucciones exactas."))
                stats["auto_fix"] = len(fixes)
            lines.append(f"## Comprobación: `{check}`\n```\n{result}\n```")
            stats["check"] = check
            stats["check_ok"] = not check_failed(result)
        head = f"Plan hecho por el modelo local: {ok} de {len(items)} bloques bien"
        head += f" (hasta {most} a la vez, {stats['plan_seconds']} s)." if most > 1 else "."
        return head + "\n\n" + "\n\n".join(lines), stats

    def auto_fix(self, check: str, result: str, items: list, results: dict, run, n: int) -> tuple[str, bool] | None:
        """Una ronda de arreglo sin Claude, SOLO si la salida de la comprobación nombra un archivo que escribió este
        plan: se corrige ese archivo (como edición) con el error delante; si nombra varios, primero el test. El 08/10
        (parches 10-27) el arreglo a ciegas, con una pregunta previa de «qué archivo», se probó 27 veces y acertó 1:
        el fallo solía estar en un archivo que el plan no tocaba (mapa, antología, otro test), y eso solo lo ve
        Claude."""
        out = result[-2500:]
        written = [it for it in items if it["kind"] in WRITES and it["path"] and results.get(it["id"], (False,))[0]]
        named = [it for it in written if it["path"] in out or Path(it["path"]).name in out]
        if not named:
            return None
        orig = next((it for it in named if is_test_path(it["path"])), named[0])
        choice = orig["path"]
        others = [f for f in dict.fromkeys([*orig["files"], *(it["path"] for it in written)]) if f != choice]
        fix = {"b": {"instructions": (
                   f"{orig['b'].get('instructions') or ''}\n\nCORRECCIÓN: con el archivo ya escrito, `{check}` falla "
                   f"así:\n```\n{out}\n```\nCambia lo justo para que pase. Si es un test, que compruebe lo que pide el "
                   "encargo mirando el contenido REAL de los archivos de contexto (no inventes etiquetas ni clases, "
                   "usa node:test y node:assert, y no lo relajes hasta no comprobar nada)."),
                   "server": orig["b"].get("server")},
               "id": f"arreglo{n}", "path": choice, "kind": "edit", "files": others[:5],
               "title": f"arreglo {n}: {choice}"}
        good, _ = run(fix)
        return choice, good

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
        # un archivo reescrito en el mismo segundo y con el mismo tamaño haría que Python usara su .pyc viejo
        env["PYTHONDONTWRITEBYTECODE"] = "1"
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
            turns = max(3, min(30, int(max_turns or self.agent_turns)))
        except (TypeError, ValueError):
            turns = self.agent_turns
        start = [f for f in files if isinstance(f, str)]
        prompt = task + (f"\n\nEmpieza leyendo: {', '.join(start)}" if start else "") + self.skills_text()
        before = self.snapshot()
        srv = self.first_up(self.order or self.servers)
        self.use(srv)
        self.current["server"] = self.server_id
        self._live("", "")
        thinking = srv.get("thinking") if srv.get("thinking") in ("apagado", "profundo") else None
        adapter = LocalAgentAdapter(base_url=self.url, api_key=self.key or None, transport=self._httpx(),
                                    http_get=self.http_get, web=self.web,
                                    commands=CHECK_COMMANDS if self.commands is None else self.commands,
                                    only_tools=self.worker().get("tools"), max_idle_turns=AGENT_IDLE_TURNS)
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
        res = asyncio.run(adapter.execute(RunSpec(prompt=prompt, cwd=str(self.root), max_turns=turns,
                                                  thinking=thinking), on_event, self.agent_timeout))
        self._live("\n\n".join(seen["thinking"]), res.get("final") or "", done=True)
        changed = self.changed(before, self.snapshot())
        stats = {"prompt_tokens": seen["usage"].get("prompt_tokens"), "completion_tokens":
                 seen["usage"].get("completion_tokens"), "model": seen["model"], "files": changed,
                 "status": res["status"], "request": task[:MAX_LOG_REQUEST],
                 "answer": (res.get("final") or "")[:MAX_LOG_ANSWER], "skills": self.worker().get("skills") or [],
                 "server": self.server_id}
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
            # stdin=DEVNULL siempre: cada encargo va en su hilo mientras el principal lee stdin, y en Windows heredar
            # ese stdin (una tubería con una lectura en curso) deja colgado el subprocess (así se quedaba local_agent)
            raw = subprocess.run(["git", "status", "--porcelain", "-z", "--untracked-files=all"], cwd=self.root,
                                 stdin=subprocess.DEVNULL, capture_output=True,
                                 timeout=30).stdout.decode("utf-8", "replace")
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
            room = self.input_budget() - used
            if room <= 0:
                parts.append(f"--- {f} --- (omitido: ya no cabe más contexto)")
                continue
            cut = text[:room]
            parts.append(f"--- {f} ---\n{cut}" + ("\n[… recortado]" if len(cut) < len(text) else ""))
            used += len(cut)
            read.append(f)
        return "\n\n".join(parts), read

    def how_to_write(self, it: dict) -> str:
        """Cómo se hace un bloque del plan: `edit` si lo pidió Claude y el archivo existe, o si pidió `write` sobre un
        archivo existente grande (reescribirlo entero era lo más lento y lo que perdía líneas); si no, como venga."""
        if it["kind"] not in WRITES or not it["path"]:
            return "ask"
        try:
            target = self.safe(it["path"])
        except ToolError:
            return it["kind"]  # que falle donde siempre, con su mensaje
        if not target.is_file():
            return "write"
        if it["kind"] == "edit" or target.stat().st_size > EDIT_OVER_CHARS:
            return "edit"
        return "write"

    def input_budget(self) -> int:
        """Cuántos caracteres de archivos caben en un encargo al modelo en curso: su contexto real (`/props` →
        `n_ctx`, por ranura) menos la respuesta y el prompt de sistema, a ~3 caracteres por token. LH_MAX_INPUT_CHARS
        es el tope. Antes era un número fijo: con 16k de contexto se pasaba y con 64k se quedaba corto."""
        ctx = self.context_of(next((s for s in self.servers if s["id"] == self.server_id), self.servers[0]))
        if not ctx:
            return self.max_input
        room = (ctx - min(self.max_tokens, ctx // 2) - 1500) * 3
        return max(8000, min(self.max_input, room))

    def context_of(self, srv: dict) -> int | None:
        """Tamaño de contexto por ranura del llama-server (se pregunta una vez; None si no contesta o en pruebas)."""
        if self.transport:
            return srv.get("n_ctx")
        if srv["id"] not in self._ctx:
            req = urllib.request.Request(srv["url"] + "/props")
            if srv.get("key"):
                req.add_header("Authorization", f"Bearer {srv['key']}")
            try:
                with urllib.request.urlopen(req, timeout=2) as r:
                    props = json.loads(r.read())
                self._ctx[srv["id"]] = int((props.get("default_generation_settings") or {}).get("n_ctx")
                                           or props.get("n_ctx") or 0) or None
            except (OSError, ValueError, TypeError):
                self._ctx[srv["id"]] = None
        return self._ctx[srv["id"]]

    def complete(self, system: str, user, schema: dict | None = None, effort: str = "low") -> tuple[str, dict]:
        """Un encargo al modelo. `schema`: JSON Schema que la respuesta TIENE que cumplir (llama-server lo impone con
        una gramática: se acaban los planes y JSON mal formados). `effort`: razonamiento de gpt-oss y similares; el
        08/10, con los mismos encargos, «low» escribió 3-4 veces más rápido que «medium» y el mismo código."""
        skills = self.worker().get("skills") or []
        system += self.skills_text()
        # cache_prompt: los bloques de un plan comparten prompt de sistema y archivos; llama-server reutiliza lo ya
        # procesado en la ranura en vez de leerlo otra vez
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.2, "max_tokens": self.max_tokens, "cache_prompt": True, "_effort": effort}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "respuesta", "strict": True,
                                                                              "schema": schema}}
        t0 = time.monotonic()
        data = self._post_any(body)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = (msg.get("content") or "").strip()
        usage = data.get("usage") or {}
        timings = data.get("timings") or {}
        stats = {"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                 "tps": round(timings["predicted_per_second"], 1) if timings.get("predicted_per_second") else None,
                 "model": _short(data.get("model")), "gen_seconds": round(time.monotonic() - t0, 1),
                 # el chat propio del trabajador local: lo que se le pidió, lo que contestó y lo que pensó
                 "request": _as_text(user)[:MAX_LOG_REQUEST] + ("\n[…]" if len(_as_text(user)) > MAX_LOG_REQUEST
                                                                 else ""),
                 "answer": text[:MAX_LOG_ANSWER], "skills": skills, "server": self.server_id}
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

    def _post_any(self, body: dict) -> dict:
        """Al servidor elegido; si está apagado, a los siguientes del orden (un 401 no: fallarían igual)."""
        body = dict(body)
        effort = body.pop("_effort", None)
        if self.transport:
            srv = next((x for x in self.servers if x["id"] == self.server_id), self.servers[0])
            return self.transport({**body, **thinking_body(srv.get("thinking"), effort)})
        order = self.order or [next(srv for srv in self.servers if srv["id"] == self.server_id)]
        for i, srv in enumerate(order):
            self.use(srv)
            self.current["server"] = srv["id"]
            self._live("", "")  # ese modelo ya está con el encargo (la oficina lo pone a trabajar)
            try:
                return self._post({**body, **thinking_body(srv.get("thinking"), effort)})
            except Exception as e:
                self._live("", "", done=True)
                if not isinstance(e, NoModel) or i == len(order) - 1 or "401" in str(e):
                    raise
        raise NoModel("no hay ningún modelo local arrancado; hazlo tú")

    def _post(self, body: dict) -> dict:
        """Si el modelo aún está cargando (503 «Loading model»), espera a que acabe en vez de fallar: el 08/10 se
        perdió un parche entero porque gpt-oss tarda 3 min en cargar y cada encargo fallaba al instante."""
        deadline = time.monotonic() + LOAD_WAIT_S
        while True:
            try:
                return self._post_once(body)
            except ToolError as e:
                if "HTTP 503" not in str(e) or time.monotonic() > deadline:
                    raise
                self._live("", "esperando a que el modelo termine de cargar…")
                time.sleep(LOAD_POLL_S)

    def _post_once(self, body: dict) -> dict:
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
        pieces, t_first = 0, 0.0  # trozos recibidos (≈ tokens) para la velocidad en vivo
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
                if delta.get("content") or delta.get("reasoning_content"):
                    pieces += 1
                    t_first = t_first or time.monotonic()
                finish = c.get("finish_reason") or finish
            if time.monotonic() - last > 0.8:
                last = time.monotonic()
                el = last - t_first if t_first else 0
                self._live("".join(reasoning), "".join(content), tps=round(pieces / el, 1) if el > 0.5 else None,
                           tokens=pieces)
        final = round(timings["predicted_per_second"], 1) if timings.get("predicted_per_second") else None
        self._live("".join(reasoning), "".join(content), done=True, tps=final,
                   tokens=usage.get("completion_tokens") or pieces)
        return {"model": model, "usage": usage, "timings": timings,
                "choices": [{"message": {"content": "".join(content), "reasoning_content": "".join(reasoning)},
                             "finish_reason": finish}]}

    def _live(self, thinking: str, text: str, done: bool = False, tps: float | None = None,
              tokens: int | None = None) -> None:
        """Lo que el modelo local está haciendo AHORA (lo lee el orquestador cada segundo para la oficina). Con varios
        modelos a la vez, cada uno tiene su entrada en `servers`; arriba va el último que escribió."""
        if not self.live_path:
            return
        sid = self.current.get("server") or self.server_id
        data = {**self.current, "server": sid, "thinking": thinking[-4000:], "text": text[-3000:], "done": done,
                "at": time.time(), "skills": self.worker().get("skills") or [], "tps": tps, "tokens": tokens,
                "model": self._models.get(sid)}
        tmp = self.live_path.with_suffix(f".{sid}.tmp")
        try:
            with self._lock:
                self._live_by[sid] = data
                tmp.write_text(json.dumps({**data, "servers": self._live_by}, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, self.live_path)
        except OSError:
            pass

    def _log(self, entry: dict) -> None:
        if not self.log:
            return
        try:
            with self._lock, open(self.log, "a", encoding="utf-8") as f:
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


def _as_text(user) -> str:
    """El texto de un mensaje (con imágenes, las partes de texto y cuántas imágenes llevaba)."""
    if isinstance(user, str):
        return user
    texts = [p.get("text", "") for p in user if p.get("type") == "text"]
    images = sum(1 for p in user if p.get("type") == "image_url")
    return "\n".join(texts) + (f"\n[{images} imagen(es)]" if images else "")


PLAN_SCHEMA = {
    "type": "object",
    "properties": {"blocks": {"type": "array", "minItems": 1, "maxItems": 12, "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "title": {"type": "string"},
                       "kind": {"type": "string", "enum": ["edit", "write", "ask"]},
                       "path": {"type": "string"}, "instructions": {"type": "string"},
                       "files": {"type": "array", "items": {"type": "string"}},
                       "after": {"type": "array", "items": {"type": "string"}}},
        "required": ["id", "kind", "instructions", "after"]}}},
    "required": ["blocks"],
}
SYSTEM_PLAN = (
    "Eres el planificador de un equipo de modelos locales. Parte la tarea en BLOQUES PEQUEÑOS: cada bloque cambia "
    "UN archivo (`edit` si ya existe —solo los trozos que cambian—, `write` si es nuevo) o hace una pregunta "
    "(`ask`). Instrucciones AUTOCONTENIDAS: quien haga el bloque solo verá sus instrucciones y los `files` que "
    "pongas (no ve la tarea ni los demás bloques): di exactamente qué escribir, con nombres, textos y selectores. "
    "`after`: ids de bloques anteriores de los que depende ([] si de ninguno): los tests dependen del código que "
    "comprueban. Usa solo rutas que existan en el MAPA o archivos nuevos que crees tú. Responde SOLO con el JSON.")


def validate_plan(blocks: list, root: Path) -> list[str]:
    """Errores de un plan (vacío = vale): ids únicos, `after` solo hacia atrás, rutas dentro del repo, `edit` sobre
    archivos que existen."""
    errors, seen = [], []
    for b in blocks if isinstance(blocks, list) else []:
        bid = str(b.get("id") or "")
        if not bid or bid in seen:
            errors.append(f"bloque sin id o con id repetido: {bid!r}")
        bad = [a for a in b.get("after") or [] if a not in seen]
        if bad:
            errors.append(f"el bloque {bid} depende de {bad}, que no son bloques anteriores")
        path = str(b.get("path") or "")
        if b.get("kind") in ("edit", "write"):
            p = (root / path).resolve() if path else None
            if not path or not p.is_relative_to(root) or ".git" in p.relative_to(root).parts:
                errors.append(f"el bloque {bid} no tiene una ruta válida dentro del repo: {path!r}")
            elif b.get("kind") == "edit" and not p.is_file():
                errors.append(f"el bloque {bid} edita {path}, que no existe (usa write para crearlo)")
        if not str(b.get("instructions") or "").strip():
            errors.append(f"el bloque {bid} no tiene instrucciones")
        seen.append(bid)
    if not seen:
        errors.append("el plan no tiene bloques")
    return errors


def short_diff(old: str, new: str, path: str, limit: int = 60) -> dict:
    """El cambio en formato diff (recortado) y cuántas líneas entran y salen: Claude lo revisa sin hacer Read."""
    import difflib
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{path}", f"b/{path}", n=1,
                                      lineterm=""))[2:]
    added = sum(1 for ln in lines if ln.startswith("+"))
    removed = sum(1 for ln in lines if ln.startswith("-"))
    text = "\n".join(ln[:200] for ln in lines[:limit])
    if len(lines) > limit:
        text += f"\n[… {len(lines) - limit} líneas más]"
    return {"text": text or "(sin cambios)", "added": added, "removed": removed}


def check_failed(result: str) -> bool:
    """La comprobación se ejecutó y no salió con 0 (si ni se ejecutó, no hay nada que arreglar aquí)."""
    first = result.split("\n", 1)[0]
    return first.startswith("código de salida ") and first != "código de salida 0"


def is_test_path(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    return (p.startswith(("tests/", "test/")) or "/tests/" in p or "/test/" in p or ".test." in name
            or ".spec." in name or name.startswith("test_") or name.endswith("_test.py"))


def tests_after_code(items: list[dict]) -> list[tuple[str, list[str]]]:
    """En un plan en paralelo, cada bloque que escribe un test espera a los bloques que escriben los archivos que
    nombra (en sus instrucciones o en `files`) y los lee. Si no, adivina el marcado: el 08/10 fallaron así 5 de 7
    primeras rondas (buscaba un div y era un button, un span y era un p…). No se toca si crearía un ciclo."""
    code = [it for it in items if it["kind"] in WRITES and it["path"] and not is_test_path(it["path"])]
    by_id = {it["id"]: it for it in items}

    def needs(it: dict, target: str, seen: set) -> bool:  # ¿`it` depende (aunque sea de lejos) de `target`?
        for a in it["after"]:
            if a == target:
                return True
            if a not in seen:
                seen.add(a)
                if needs(by_id[a], target, seen):
                    return True
        return False
    out = []
    for t in items:
        if t["kind"] not in WRITES or not is_test_path(t["path"]):
            continue
        text = str(t["b"].get("instructions") or "") + " " + " ".join(t["files"])
        deps = [c for c in code if (c["path"] in text or Path(c["path"]).name in text)
                and c["id"] not in t["after"] and not needs(c, t["id"], set())]
        if deps:
            t["after"] = [*t["after"], *(c["id"] for c in deps)]
            t["files"] = list(dict.fromkeys([*t["files"], *(c["path"] for c in deps)]))
            out.append((t["path"], [c["path"] for c in deps]))
    return out


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
    lock = threading.Lock()

    def answer(msg: dict) -> None:
        reply = server.handle(msg)
        if reply is not None:
            with lock:  # una respuesta por línea, sin mezclarse con otra que acabe a la vez
                out.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
                out.flush()

    for raw in stdin:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("method") == "tools/call":
            # cada encargo en su hilo: con dos modelos locales, Claude puede tener a los dos trabajando a la vez
            threading.Thread(target=answer, args=(msg,), daemon=True).start()
        else:
            answer(msg)


if __name__ == "__main__":
    main()
