# LocalHarness — guía de funciones e implementación

Qué hace cada pieza y cómo está hecha. Todo lo que dice esta guía está en el código a fecha 06/10/2026; lo que
es plan futuro se marca como **(futuro)**. Estado y traspaso: `docs/ESTADO.md`. Rumbo: `docs/OBJETIVOS.md`.

## 1. Conceptos

| Concepto | Qué es | En el código |
|---|---|---|
| Proyecto | Un repo git registrado (con al menos un commit). Puede tener carpeta de memoria | tabla `projects` |
| Agente | Una **configuración**, no código: proveedor, modelo, rol y `config` (límites, herramientas, skills…) | tabla `agents` |
| Rol | Texto libre del agente (`director`, `jefe`, `trabajador`, `consultas`…). Hoy no fija herramientas ni límites | `agents.role` |
| Tarea | Una petición a un agente. Trabaja en su rama y worktree. Suelta o parte de un plan | tabla `tasks` |
| Plan / misión | Petición grande: el Director la parte en pasos. Una rama `localharness/plan-N` y un worktree. En la GUI futura se llamará «misión» | tabla `plans` |
| Paso / subtarea | Una tarea del plan (`kind` = `worker`), con agente, riesgo, skills y su propio commit | `tasks.plan_id`, `seq` |
| Skill | Carpeta con `SKILL.md`: un procedimiento que se inyecta como texto en el prompt | `context.py`, `skills/` |
| Memoria | Los `.md` de la carpeta de memoria del proyecto. Solo lectura para el agente | `projects.memory_dir` |
| Encargo / delegación | Trabajo que un agente Claude pasa al modelo local por MCP | `mcp_local.py`, eventos `delegate` |
| Bandeja | «Pendiente de ti»: lo que espera tu decisión | `hierarchy.inbox`, `GET /api/inbox` |
| Niveles | N0 automático · N1 jefe técnico · N2 tú | `policy.py` |

Estados de una tarea: `pending` → `running` → `review` (hay cambios, espera tu revisión) o `done` (sin cambios:
consultas, planes, revisiones) · `approved` → `merged` · `rejected` / `discarded` · `failed` / `timeout` /
`cancelled` · `interrupted` (el servidor se cerró con la tarea en marcha).

Estados de un plan: `planning` → `awaiting_you` o `approved` → `running` ⇄ `paused` (te necesita) → `ready` (listo
para integrar) → `merged` · `done` (nada que integrar) · `rejected` · `failed` / `cancelled` / `interrupted`.

Concurrencia: **una tarea en marcha por repo** (las subtareas de un plan van en serie sobre el mismo worktree) y,
en la API, un plan en marcha por proyecto.

## 2. Proveedores

`localharness/adapters/`: cada adaptador construye el comando (o hace la llamada HTTP) y traduce la salida a
eventos comunes. El registro está en `adapters/__init__.py` (`ADAPTERS`).

| Proveedor | Qué es | Escribe archivos | Coste |
|---|---|---|---|
| `claude` | CLI oficial `claude -p` con tu suscripción | sí | gasta plan |
| `codex` | `codex exec --json` | sí | aparcado |
| `local` | un mensaje a llama-server con el contexto del repo | no | 0 |
| `local_agent` | bucle de agente con herramientas sobre llama-server | sí | 0 (salvo `preguntar_director`) |

Cuándo usar cada uno:
- **Director y jefe técnico gratis**: `local`. Planifica y revisa diffs bien (ver la tabla de modelos en `docs/ESTADO.md`).
- **Implementar**: `claude` (Sonnet con topes). Con «Puede delegar en el modelo local» ahorra plan en lectura,
  código nuevo y búsquedas.
- **Trabajador gratis que lee, escribe y ejecuta tests**: `local_agent`. v1, aún sin probar con Qwen real.
- `codex`: no instalado; el parser está escrito desde documentación y no se ha verificado.

### 2.1 `claude` (`adapters/claude.py`)
Comando: `claude -p --output-format stream-json --verbose`, prompt **por stdin** (sin límite de 32k de Windows ni
problemas de comillas). Después:
- **Aislamiento.** Sin delegación: `--safe-mode --strict-mcp-config` (sin MCP, plugins, hooks ni CLAUDE.md del
  usuario: de ~245k a ~4,6k tokens de contexto). Con delegación (`--mcp-config`): `--safe-mode` desactiva también
  esos servidores, así que se usa `--setting-sources "" --disable-slash-commands --strict-mcp-config` y la variable
  `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` (~11,6k tokens).
- **Topes**: `--model`, `--max-turns`, `--max-budget-usd`. `--json-schema` para salida estructurada (Director y
  jefe técnico). `--resume <session_id>` para continuar una conversación.
- **Herramientas**: `--permission-mode bypassPermissions` + `--tools` (límite duro, verificado) + `--allowedTools`
  (auto-aprobación; ahí van también las MCP). Por defecto `Read,Glob,Grep,Edit,Write`; con `read_only`
  `Read,Glob,Grep`; `config.tools` las sustituye. Bash/PowerShell solo si se conceden en `tools`.
  `config.subagents` añade `Agent` (la CLI lo lista como `Task`).
- **Suscripción**: se quitan `ANTHROPIC_API_KEY` y `ANTHROPIC_AUTH_TOKEN` del entorno de la CLI hija (con `-p`
  una API key presente se usaría siempre y cobraría por tokens). `doctor` comprueba `claude auth status` = `claude.ai`.
- **Windows**: `binaries.py` lanza el `claude.exe` real al que apunta el shim `.cmd` de npm (sin cmd.exe).
- Un fallo llega como `result` con `is_error` o subtype `error_*` y código de salida 0: se traduce a `error`.

### 2.2 `codex` (`adapters/codex.py`) — aparcado
`codex exec --json -C <worktree> --sandbox read-only|workspace-write -c approval_policy="never" [--model]`, prompt
por stdin (`-`). Sin verificar con la CLI real (orden de `resume` y `-` pendientes). Ignora `max_turns`,
`max_budget_usd` y `tools`.

### 2.3 `local` (`adapters/local.py`)
No es una CLI (`is_cli = False`): habla con llama-server por su API compatible con OpenAI. Un solo mensaje:
- Antes pide `/v1/models`: responde **el modelo arrancado**, se llame como se llame el agente. Si el agente pide
  otro, avisa (`warning`). El evento `session` lleva el modelo real y `requested`.
- El prompt lleva el **contexto del repo** (`repo_context`, por defecto 24 000 caracteres): lista de `git ls-files`
  (hasta 400) y el contenido de los archivos de texto de menos de 20 KB que quepan.
- Streaming SSE: un evento `text` por párrafo y `speed` cada 1,5 s (tok/s, tokens, fase pensando/escribiendo).
- Con `json_schema` manda `response_format` y analiza el JSON de forma tolerante (bloques ```, texto extra).
- Un modelo que razona y gasta todos los tokens pensando sin responder termina en `failed` con un mensaje claro.
- `can_write = False`: el Director nunca le asigna subtareas (solo agentes que pueden escribir).
- Lleva la cabecera `Authorization: Bearer <clave>` si el llama-server se lanzó desde la GUI.

### 2.4 `local_agent` (`adapters/local_agent.py`)
LocalHarness hace el bucle: manda a Qwen la tarea y las herramientas, Qwen pide una (`tool_calls`), LocalHarness la
ejecuta **confinada al worktree** y devuelve el resultado, hasta `terminar` o un tope. Cada herramienta es un
evento `tool`, igual que en Claude.

| Herramienta | Qué hace | Cuándo está |
|---|---|---|
| `leer_archivo(ruta)` | lee un archivo del repo | siempre |
| `listar(carpeta)` | lista una carpeta (sin `.git`, `node_modules`, `.venv`…) | siempre |
| `buscar_texto(texto, carpeta)` | `ruta:línea` de las coincidencias (máx. 60) | siempre |
| `escribir_archivo(ruta, contenido)` | crea o reescribe entero | si no es `read_only` |
| `ejecutar(comando)` | orden de la lista blanca, sin shell | si la lista no está vacía |
| `buscar_web(consulta)` | DuckDuckGo HTML, 8 resultados | si `web` |
| `leer_url(url)` | texto legible de una página http/https | si `web` |
| `preguntar_director(pregunta)` | pregunta al Director del plan | solo dentro de un plan con Director de Claude |
| `avisar_progreso(texto)` | frase corta para la GUI (evento `progress`) | siempre |
| `terminar(resumen, comprobacion)` | cierra la tarea | siempre |

Límites y fiabilidad:
- Rutas: nada fuera del worktree, nada dentro de `.git`.
- `max_turns` por defecto 25; el tiempo total es el timeout de la tarea.
- Salidas de herramientas recortadas a `max_tool_chars` (6000); si la conversación pasa de `max_context_chars`
  (60 000), los resultados viejos se recortan.
- Argumentos mal formados: se le devuelve el error y reintenta. Sin herramienta: se le recuerda una vez; la segunda
  se acepta su texto como respuesta final (con aviso). La misma llamada 3 veces seguidas = bucle: se para.
- `tool_mode: json` para modelos sin plantilla de herramientas: no manda `tools` y obliga a responder
  `{"herramienta", "argumentos"}` con `response_format`. En modo nativo también entiende la llamada escrita como texto.
- `ejecutar`: prefijos permitidos por defecto `python -m unittest`, `python -m pytest`, `pytest`, `npm test`,
  `npm run test`, `npm run lint`, `ruff check`, `node --test` (ampliable con `commands`). `python` se cambia por el
  intérprete de LocalHarness. Tiempo máximo `command_timeout_s` (120). Se quitan del entorno `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY` y `LH_LOCAL_KEY`. **Ojo: no aísla la red.**
- `preguntar_director`: reanuda la sesión de Claude del Director (`--resume`) en solo lectura, 3 turnos y tope de
  0,2 $. Máximo 3 preguntas por tarea; el coste se suma a la tarea. Eventos `ask_director` y `director_answer`.

## 3. Claude delega en el modelo local (`mcp_local.py`)

Servidor MCP stdio propio (JSON-RPC 2.0 a mano, sin dependencias). Se activa con `config.delegate_local` en un
agente `claude` («Puede delegar en el modelo local» en Ajustes). Cómo se cablea (`orchestrator._delegation`):
1. Carpeta temporal con `mcp.json` (lleva la clave de llama-server; se borra al acabar la tarea) y `encargos.jsonl`.
2. El servidor se lanza **por ruta** con el Python de LocalHarness (desde el worktree el paquete no está en el path).
   Variables: `LH_LOCAL_URL` (la URL de Ajustes), `LH_LOCAL_KEY`, `LH_ROOT` (worktree), `LH_LOG`, `LH_WRITE`.
   Opcionales: `LH_MAX_TOKENS` (8192), `LH_MAX_INPUT_CHARS` (40 000), `LH_WEB` (1/0).
3. `--mcp-config`, herramientas `mcp__local__*` auto-aprobadas, `MCP_TOOL_TIMEOUT=900000`, `MCP_TIMEOUT=30000`.
4. Al prompt se añade una guía de cuándo delegar. En solo lectura no hay `local_write_file`.

| Herramienta | Qué hace |
|---|---|
| `local_ask(task, files)` | el servidor lee los archivos del worktree y Qwen responde: Claude no gasta tokens leyéndolos |
| `local_write_file(path, instructions, context_files)` | Qwen escribe el archivo entero; Claude recibe un resumen y las primeras líneas |
| `local_research(question, query, pages)` | DuckDuckGo HTML, lee 1–5 páginas (3 por defecto) y responde con fuentes `[1]`, `[2]`… |

Si no hay modelo arrancado, la página no carga o Qwen devuelve vacío, la herramienta responde «hazlo tú». Cada
encargo queda en `encargos.jsonl`; el orquestador lo lee cada segundo y emite `delegate` (tarjetas verdes «🦙» en el
chat) y, al final, `delegate_summary` con los tokens hechos en local. Medido: en tareas muy pequeñas cuesta más que
no delegar (el contexto base sube de 4,6k a 11,6k tokens); el ahorro llega con archivos grandes y mucho código.

## 4. Jerarquía (`hierarchy.py`, `policy.py`)

```
Tú ──aprueba── planes, riesgo alto, integrar, push
 └─ Director        solo lectura; devuelve un plan JSON (--json-schema PLAN_SCHEMA)
     └─ Trabajadores  pasos EN SERIE sobre la rama del plan, un commit por paso
         └─ Jefe técnico  revisa el diff de cada paso N1 (REVIEW_SCHEMA: approve | request_changes | escalate)
```
1. **Planificar.** Se crea la rama `localharness/plan-N`. El Director recibe la petición, la lista de agentes que
   pueden escribir (con su `description`), el catálogo de skills y el **manual** `manual/director.md`. El plan:
   `summary`, `risk` y 1–12 `subtasks` con `title`, `prompt`, `agent`, `risk` y `skills`. `validate_plan` exige
   agentes existentes (el Director solo elige, no crea) y descarta skills inventadas.
2. **Nivel del plan.** N2 si tiene más de `max_auto_subtasks` (3) pasos, alguno de riesgo alto o el Director lo marca de riesgo alto. Con el ajuste
   `plans.always_review` (por defecto activo) el plan **siempre** te espera (`awaiting_you`). Mientras espera puedes
   editar los pasos (`PUT /api/plans/{id}`, validado igual que el del Director) o pedir al Director que rehaga uno
   con un comentario (`POST /api/plans/{id}/redo`: reanuda su sesión con `STEP_SCHEMA`).
3. **Ejecutar.** Cada paso: `nivel = máx(riesgo declarado, reglas sobre el diff)`. Sin cambios → N0. N1 → lo revisa
   el jefe técnico; si aprueba con riesgo ≤ medio queda `approved`; si no, sube a N2. Sin jefe técnico, N1 → N2.
   Un diff de más de 60 000 caracteres se escala sin revisar. El revisor solo puede **subir** el nivel.
4. **N2** → el plan se para (`paused`) y el paso aparece en la bandeja. «Aprobar y seguir» o «Rechazar y seguir»
   (rechazar deshace **solo** su commit con `reset --hard`, y solo si es la punta de la rama).
5. Al acabar: `ready` si hay pasos aprobados (integrar es siempre tuyo) o `done` (se borra la rama).

Reglas deterministas (`policy.assess_changes`, editables en Ajustes → Aprobaciones): N2 si borra archivos, toca
archivos sensibles (`.env*`, `*.pem`, `*.key`, `migrations/`, `.github/`, lockfiles), dependencias
(`package.json`, `requirements*.txt`, `pyproject.toml`…), configuración/CI (`Dockerfile`, `Makefile`…), más de 8
archivos o más de 300 líneas. Si no, N1.

Bandeja (`inbox`): `plan_approval`, `task_decision` (paso N2 parado), `plan_merge` y `task_review` (tareas
sueltas en `review` o `approved`).

**Manual del Director** (`manual/director.md`): el ciclo (clasificar → entender lo justo → elegir equipo →
planificar con criterio de aceptación), reglas de reparto (leer y buscar en local, lógica delicada en Claude, el más
barato que lo haga bien) y reglas del plan. Se edita sin tocar código; si falta, se usa un texto mínimo de reserva.

## 5. Skills y memoria (`context.py`)

- **Skills**: carpetas con `SKILL.md` (frontmatter `name`, `description`). Se buscan en `skills/` del repo, en las
  carpetas de Ajustes → Skills y en `LOCALHARNESS_SKILL_DIRS`. Si dos tienen el mismo nombre, gana la primera.
  Propias: `tests-primero`, `cambios-minimos`, `revision-de-diff`.
- Se inyectan las del agente (`config.skills`), las de la tarea (`run --skill`, `skills` en `POST /api/tasks`) y
  las que elige el Director por paso. Las que no existen dan un `warning`.
- **Memoria**: los `.md` de `projects.memory_dir` (`project memory <nombre> [ruta]`, por defecto
  `data/memory/<proyecto>`). Vive fuera del worktree: el agente la lee en el prompt pero no la reescribe.
- Topes: 20 000 caracteres de memoria y 30 000 de skills (Ajustes). El prompt queda: memoria → skills → `## Tarea`.
- El evento `context` registra exactamente qué se inyectó. Al reanudar una sesión de Claude no se repite.

## 6. Flujo git (`workspace.py`, `actions.py`, `maintenance.py`)

- **Worktree por tarea o plan**: rama `localharness/task-N` o `localharness/plan-N`, en
  `<carpeta del repo>/../.localharness-worktrees/<repo>/`. La creación va con un candado (git worktree add en paralelo
  corrompe metadatos) y limpia restos de intentos anteriores.
- **Checkpoint**: al terminar (o cancelar) se hace commit de todo lo del worktree con autor `localharness`. El diff
  revisable es `base_commit..head_commit`, incluidos archivos nuevos.
- **Conversación**: responder a una tarea terminada (`POST /api/tasks/{id}/reply`) sigue en la misma rama; el diff
  cuenta desde la base original y el coste se acumula. Claude reanuda su sesión; `local` recibe toda la conversación.
- **Integrar solo con aprobación**: en la API, aprobar y luego integrar con `confirm: true`; en la CLI, `merge` pide
  confirmación. `merge --no-ff` en tu rama actual (o `--into`). Se niega si el repo principal tiene cambios sin
  confirmar.
- **Conflictos**: antes de integrar, `git merge-tree --write-tree` (git ≥ 2.38) detecta los archivos en conflicto
  sin tocar nada. Si aun así el merge falla, se aborta y se vuelve a tu rama. Nunca queda un merge a medias.
- **Limpieza** (al arrancar `serve` y con `cleanup [--dry-run]`): borra worktrees y ramas de tareas `merged`,
  `rejected`, `discarded` o `done` y de planes `merged`, `rejected` o `done`. Conserva lo fallido, cancelado o
  aprobado. Las ramas `localharness/*` que no están en la base de datos solo se informan.
- **Nunca push.** Ningún código hace push; el push lo haces tú.
- (futuro, M6) rama de integración por proyecto y «rehacer sobre la rama actual» tras un conflicto.

## 7. Modelos locales (`llama.py`)

- Rutas, por orden: Ajustes → Modelos locales, `LOCALHARNESS_LLAMA_SERVER` / `LOCALHARNESS_MODEL_DIRS`, la
  configuración de Arena LLM (`%APPDATA%/ArenaLLM/agent.json`) y `llama-server` en el PATH.
- Lista los GGUF (sin `mmproj` ni partes 2..N) con tamaño y cuantización deducida del nombre.
- Arranque: `llama-server -m <gguf> --host 127.0.0.1 --port <p> -c <ctx> -ngl <ngl> --jinja`. Uno a la vez (una GPU),
  sin ventana, log en `data/llama-server.log`. Contexto, capas y argumentos extra por modelo en
  `llama.per_model` («⚙ Arranque de este modelo»). Al arrancar fija `local_base_url` a ese puerto.
- **Clave**: desde la GUI se lanza con `--api-key` aleatoria en cada arranque (sin ella cualquier web abierta podía
  usar la GPU por 127.0.0.1). Uno lanzado a mano con `llama serve` va sin clave.
- **Progreso**: estado `off | loading | ready | failed | external`. El % sale de los puntos de `load_tensors`
  (versiones antiguas), o de lo que tardó ese GGUF la vez más lenta (`data/llama-load-times.json`, con «faltan ~X s»),
  o barra indeterminada con la etapa. Se ven 1–2 líneas del log.
- **tok/s**: eventos `speed` en vivo (no se guardan) y la última velocidad en `/api/health` y `/api/llama`.
- El servidor lanzado desde la GUI se para al cerrar LocalHarness.

## 8. API REST + SSE (`api.py`)

Solo escucha en 127.0.0.1 y no tiene autenticación. Con `web/dist` compilada sirve también la GUI.

| Método y ruta | Qué hace |
|---|---|
| `GET /api/health` | versión, proveedores, tareas en marcha, último uso del plan, modelo local arrancado, última velocidad |
| `GET /api/projects` | lista proyectos |
| `POST /api/projects` | registra un repo (`init_git: true` hace `git init` + commit inicial si no es repo) |
| `PATCH /api/projects/{pid}` | cambia la carpeta de memoria |
| `GET /api/agents` | lista agentes con su `config` |
| `POST /api/agents` | crea un agente |
| `PATCH /api/agents/{aid}` | edita modelo, rol y claves de `config` (null/false/vacío = quitar) |
| `DELETE /api/agents/{aid}` | borra un agente sin historial (si no, 409) |
| `GET /api/maintenance` | informe de la última limpieza |
| `POST /api/maintenance/cleanup` | limpia ahora (`?dry_run=true` solo informa); 409 si hay algo en marcha |
| `GET /api/settings` | ajustes actuales y valores por defecto |
| `PUT /api/settings` | guarda ajustes (claves desconocidas = 422) |
| `POST /api/settings/reset` | vuelve a los valores por defecto |
| `GET /api/llama` | exe, carpetas, GGUF, estado, configuración, velocidad y tiempos de carga |
| `POST /api/llama/start` | arranca llama-server con un GGUF |
| `POST /api/llama/stop` | lo para |
| `POST /api/pick` | abre el selector nativo de carpeta/archivo en el PC (501 sin escritorio) |
| `GET /api/skills` | catálogo de skills |
| `GET /api/activity` | qué hace ahora cada tarea en marcha y las últimas terminadas con sus archivos |
| `GET /api/tasks` | lista tareas (`?project_id=`) |
| `POST /api/tasks` | crea una tarea y la arranca (`start`, `skills`) |
| `GET /api/tasks/{tid}` | detalle de una tarea |
| `GET /api/tasks/{tid}/events` | eventos guardados (`?after=` id) |
| `GET /api/tasks/{tid}/review` | stat, diff y rama destino |
| `POST /api/tasks/{tid}/start` | arranca una tarea `pending` |
| `POST /api/tasks/{tid}/cancel` | cancela una tarea en marcha (lo hecho queda en la rama) |
| `POST /api/tasks/{tid}/reply` | tu respuesta: el agente sigue en la misma rama |
| `POST /api/tasks/{tid}/approve` | aprueba una tarea suelta en `review` |
| `POST /api/tasks/{tid}/reject` | rechaza: borra rama y worktree |
| `POST /api/tasks/{tid}/merge` | integra una tarea aprobada (exige `confirm: true`) |
| `POST /api/tasks/{tid}/decide` | aprueba o rechaza un paso N2 de un plan y el plan sigue |
| `GET /api/plans` | lista planes |
| `GET /api/plans/{pid}` | plan con sus tareas |
| `POST /api/plans` | crea un plan y lanza al Director |
| `PUT /api/plans/{pid}` | edita los pasos de un plan que te espera |
| `POST /api/plans/{pid}/redo` | el Director rehace un paso con tu comentario (en segundo plano) |
| `POST /api/plans/{pid}/approve` | aprueba y ejecuta |
| `POST /api/plans/{pid}/reject` | rechaza: borra rama y worktree |
| `POST /api/plans/{pid}/merge` | integra la rama del plan (exige `confirm: true`) |
| `POST /api/plans/{pid}/cancel` | cancela un plan en marcha |
| `GET /api/inbox` | bandeja «pendiente de ti» |
| `GET /api/events` | SSE: `hello`, `task`, `task_event`, `plan`, `limit`; latido cada 15 s |

## 9. GUI (`web/src/views/`)

| Página | Ruta | Qué muestra |
|---|---|---|
| `HomeView` | `/inicio` | cifras rápidas, «Te toca a ti» con botones de decisión y «Ver diff», el equipo (libre o qué hace, tok/s, encargos al local), lo último que ha pasado (archivos tocados, veredicto del jefe) y planes |
| `ChatView` | `/chat`, `/chat/:id` | conversaciones; burbujas con markdown, herramientas plegadas, tarjetas «🦙» de encargos, preguntas al Director, «escribiendo…» con tok/s, tarjeta de cambios. Nueva: «Un agente» o «Equipo (Director)», vincular carpeta, skills por conversación |
| `InboxView` | `/bandeja` | decisiones N2 con nivel, tipo y motivos |
| `PlansView` | `/planes` | nueva petición al Director (proyecto, Director, jefe técnico) e historial |
| `PlanView` | `/planes/:id` | petición, nivel y motivos, subtareas con estado, quién aprobó y skills; aprobar, integrar, cancelar, rechazar, decidir pasos; editar un paso o pedir que se rehaga (objetivo 3, en desarrollo) |
| `TaskView` | `/tareas/:id` | detalle de ejecución: eventos, respuesta final, diff y aprobar/rechazar/integrar |
| `ModelsView` | `/modelos` | estado de llama-server con progreso y log, GGUF por carpeta, arranque por modelo, agentes locales, rutas |
| `SettingsView` | `/ajustes?s=…` | agentes, proyectos, aprobaciones, ejecución y mantenimiento, skills y memoria, apariencia |

`/tareas` redirige a `/chat` y `/proyectos` a Ajustes → Proyectos. La apariencia se guarda solo en el navegador.

## 10. Eventos

Todo proveedor emite los mismos eventos (`events.py`). Se guardan en la tabla `events` salvo `speed`.

| `kind` | Significado |
|---|---|
| `session` | arranque: id de sesión, modelo (en local, el arrancado), herramientas |
| `status` | cambio de estado de la tarea (`running`, `review`, `done`…), con nivel y motivos en los planes |
| `user` | tu mensaje en la conversación |
| `context` | memoria y skills inyectadas |
| `text` | texto del agente (en local, un párrafo) |
| `thinking` | razonamiento del modelo local (`reasoning_content`, últimos 2000 caracteres) |
| `tool` | uso de una herramienta y su entrada |
| `progress` | frase de `avisar_progreso` del agente local |
| `ask_director` / `director_answer` | pregunta del agente local al Director y su respuesta (con coste) |
| `delegate` / `delegate_summary` | un encargo de Claude al modelo local / resumen al final con tokens hechos en local |
| `speed` | tok/s, tokens y fase, cada ~1,5 s (efímero, no se guarda) |
| `usage` | coste, turnos y uso de tokens |
| `limit` | uso del plan de Claude: ventanas de 5 h y 7 días (la CLI avisa desde el 75 %) |
| `result` | respuesta final (y salida estructurada si la hay) |
| `warning` | aviso (modelo distinto al pedido, skills no encontradas, respuesta cortada…) |
| `error` | fallo |
| `raw` | línea de la CLI que no es JSON |
| `unknown` | evento de Codex que no se reconoce |

## 11. Configuración de un agente (`config`)

| Clave | Proveedores | Qué hace | Dónde se pone |
|---|---|---|---|
| `max_turns` | claude, local_agent | `--max-turns` / tope de vueltas del bucle (25 por defecto) | CLI, API, GUI |
| `max_budget_usd` | claude | `--max-budget-usd` | CLI (`--budget`), API, GUI |
| `read_only` | todos | Claude solo `Read,Glob,Grep`; Codex `--sandbox read-only`; local_agent sin `escribir_archivo`; delegación sin `local_write_file` | CLI, API, GUI |
| `tools` | claude | lista blanca que sustituye a la de por defecto | CLI, API (alta) |
| `skills` | todos | skills que el agente usa siempre | CLI (`--skill`), API, GUI |
| `description` | todos | en qué es bueno; el Director la lee al repartir | API, GUI |
| `subagents` | claude | añade la herramienta `Agent` | API, GUI |
| `delegate_local` | claude | MCP del modelo local (sección 3) | API, GUI |
| `binary` | claude, codex | ruta del ejecutable si no es el del PATH | CLI |
| `base_url` | local, local_agent | URL de llama-server; si falta, la de Ajustes | CLI, API, GUI |
| `temperature` | local, local_agent | temperatura (0,2) | API, GUI |
| `max_tokens` | local, local_agent | tokens de respuesta (4096) | API, GUI |
| `repo_context` | local | caracteres del repo en el prompt (24 000; 0 = nada) | API, GUI |
| `tool_mode` | local_agent | `native` o `json` | solo en la base de datos |
| `max_tool_chars` | local_agent | recorte de cada salida de herramienta (6000) | solo en la base de datos |
| `max_context_chars` | local_agent | tamaño a partir del que se recortan resultados viejos (60 000) | solo en la base de datos |
| `web` | local_agent | `buscar_web` y `leer_url` (activo) | solo en la base de datos |
| `commands` | local_agent | lista blanca de `ejecutar` (lista vacía = sin `ejecutar`) | solo en la base de datos |
| `command_timeout_s` | local_agent | tiempo máximo de cada orden (120 s) | solo en la base de datos |
| `timeout_s` | todos | timeout de la tarea; manda sobre el de la CLI y el de Ajustes | solo en la base de datos |

Notas: la GUI enseña `repo_context` también en agentes `local_agent`, pero ese proveedor lo ignora. Las claves
«solo en la base de datos» no tienen campo en la CLI, en la API (`AgentIn`/`AgentPatch`) ni en la GUI; hoy solo
las pone `sandbox` o una edición directa de la tabla `agents`. Ajustes globales (`settings.py`): `policy`, `plans`,
`task_timeout_min` (30), `local_base_url`, `context`, `llama` y `agent_defaults`.

## 12. Pruebas

```
.venv/Scripts/python -m unittest discover -s tests -t .      # Windows
.venv/bin/python -m unittest discover -s tests -t .          # Linux
```
Nunca llaman a la CLI real ni a la red: usan `tests/fakes/claude` y `tests/fakes/codex` (scripts Python que emiten
stream-json como los reales), servidores llama falsos (`httpx.MockTransport` o un HTTP local) y `http_get` falso
para la web. `tests/fixtures_reales/` guarda salidas reales de Claude para comprobar el parser.

| Archivo | Qué cubre |
|---|---|
| `test_core.py` | adaptadores Claude y Codex (comando y parseo, fixtures reales, `--tools`), shims de npm, worktree/diff/merge, UTF-8, restos, `node_modules`, quitar la API key, runner (metacaracteres, fallos), extremo a extremo |
| `test_cli.py` | ciclo `run` → `show` → `merge`; no integra sobre un repo con cambios |
| `test_api.py` | ciclo completo por API, rechazar, cancelar, planes, editar y rehacer pasos, validación, conversación, `init_git`, modelos, ajustes y actividad |
| `test_hierarchy.py` | niveles, numstat, `validate_plan`, el manual en el prompt, plan pequeño con jefe, plan grande, borrar = N2 y rechazar deshace, el revisor solo sube, sin revisor N1 → tú, plan que te espera, editar pasos, rehacer un paso |
| `test_context.py` | skills (con y sin frontmatter), `build_prompt`, memoria, misma tarea con y sin skill |
| `test_local.py` | streaming, contexto del repo, JSON, servidor caído, el Director no da trabajo a `local` |
| `test_local_agent.py` | herramientas, confinamiento, solo lectura, reintentos, bucles, texto sin herramientas, topes, modo JSON, lista blanca, `preguntar_director`, tarea en `review` con su diff, trabajador que pregunta al Director del plan |
| `test_delegate.py` | servidor MCP (protocolo, `local_ask`, `local_write_file`, confinamiento, fallos), flags de Claude, DuckDuckGo, `local_research`, Claude falso que delega de verdad, reanudar con delegación |
| `test_m6.py` | conflicto detectado sin tocar el repo, merge limpio, limpieza solo de lo cerrado |
| `test_session3.py` | subagentes, progreso de carga, configuración por modelo, pasos pendientes de un plan muerto, modelo real y tok/s, cabecera de clave, «se quedó pensando», campos de agente por API, skills por tarea |

## 13. Lo que viene

Resumen; el detalle está en `docs/OBJETIVOS.md` y `docs/DISENO-OFICINA.md`.
- **Manual + catálogo** en vez de agentes a mano: el Director decide el equipo con `manual/director.md` (v1 hecha)
  y un catálogo de roles, skills y servidores MCP **(futuro)**.
- **Plan editable** (objetivo 3, en curso): editar y rehacer pasos ya existen en el núcleo, la API y el detalle
  del plan; la GUI se está terminando (Inicio incluido).
- **Ver a los subagentes trabajando** (4): tarea, pensamiento en vivo, tok/s, tokens y coste **(futuro)**.
- **Catálogo de roles** (5: Explorador local, Programador, Revisor) y de skills con metadatos (6) **(futuro)**.
- **Subagentes en bucle** (7) con topes duros y parada a partir del 75 % de la ventana de 5 h **(futuro)**.
- **`local_agent`** (8): probar con Qwen real, aislar la red de `ejecutar`, `ask_human` **(futuro)**.
- **Atlas «Analizar proyecto»** (9) y **oficina 3D** del prototipo (10), después de la sesión de diseño (10a):
  misiones en pizarras, puestos por agente, bandeja, recursos y despachador con colas de Claude y GPU **(futuro)**.
