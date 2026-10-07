# Paperclip: cómo funciona y qué nos llevamos

Análisis de https://github.com/paperclipai/paperclip (06/10/2026, clon `--depth 1`). Es Node + Postgres + React,
~8.500 archivos, licencia MIT. No hay que copiarlo entero: el 80 % es gobernanza, nube, recuperación de fallos y
casos raros acumulados. El núcleo son cinco ideas pequeñas, y esas sí encajan en LocalHarness.

## 1. El modelo: una empresa de agentes

| Pieza | Qué es | Dónde |
|---|---|---|
| **Agente** | Fila en BD: `name`, `role`, `title`, `reports_to` (su jefe → organigrama), `adapter_type` + `adapter_config` (Claude, Codex, OpenCode, Hermes, proceso, HTTP…), `permissions`, presupuesto mensual, `status` (`idle/running/paused/error/terminated`). | `doc/SPEC-implementation.md` §7.2 |
| **Tarea (issue)** | La unidad de trabajo **y de comunicación**. `parent_id` (subtareas), `assignee_agent_id` (UN dueño), `status` (`backlog→todo→in_progress→in_review→done/blocked/cancelled`), `work_mode` (`standard`, `ask` = solo responder, `planning` = solo plan), bloqueos `blockedByIssueIds`, documentos (`plan`…) y comentarios. | §7.6, §8.2 |
| **Comentario** | Mensaje en el hilo de una tarea. Lo escriben humanos o agentes. | §7.7 |
| **Heartbeat run** | Una ejecución corta de un agente: arranca la CLI, trabaja, sale. Guarda estado, tokens, coste, log. | §7.8, `docs/agents-runtime.md` |
| **Aprobación** | Contratar un agente, aprobar la estrategia del CEO, etc. Las decide el «board» (tú). | §12 |

## 2. Cómo se comunican los agentes

**Nunca se hablan directamente.** Todo pasa por el tablero de tareas:

1. **Delegar = crear una subtarea** asignada a otro agente (`POST /issues` con `parentId`, `assigneeAgentId`).
   Si el jefe tiene que esperar, pone su tarea en `blocked` con `blockedByIssueIds: [hija]`.
2. **Responder = comentar** en la tarea o cambiar su estado (`done`, `in_review`, `blocked`).
3. **El servidor despierta al que toca** (cola de *wakes*, `server/src/modules/wake-queue/`). Motivos más usados:
   `issue_assigned` (te han asignado algo), `issue_commented` (comentan en tu tarea),
   `issue_blockers_resolved` (todas las tareas que te bloqueaban están `done`),
   `issue_children_completed` (acabaron tus subtareas), `execution_review_requested` /
   `execution_changes_requested` (revisión), `heartbeat_timer` (programado).
4. **Al despertar**, el adaptador mete en el prompt un bloque «Paperclip Wake Payload»: resumen de la tarea, motivo
   y los comentarios nuevos (`packages/adapter-utils/src/server-utils.ts`). Si la CLI tiene sesión guardada, la
   reanuda y solo manda el delta («Paperclip Resume Delta»).
5. **El agente actúa sobre el tablero con herramientas**: una API REST con un token por ejecución
   (`PAPERCLIP_API_KEY`, `PAPERCLIP_RUN_ID`, `PAPERCLIP_TASK_ID`, `PAPERCLIP_WAKE_REASON` en el entorno) o el
   **servidor MCP** `@paperclipai/mcp-server` (`paperclipCreateIssue`, `paperclipUpdateIssue`,
   `paperclipCheckoutIssue`, `paperclipAddComment`, `paperclipAskUserQuestions`, `paperclipRequestConfirmation`…).
6. **El comportamiento está en una skill**, no en código: `skills/paperclip/SKILL.md` es el «procedimiento del
   heartbeat» que lee cada agente: identidad → bandeja → elegir tarea → *checkout* → leer contexto → trabajar →
   dejar estado claro → delegar si hace falta.

Detalles que evitan el caos:
- **Checkout atómico**: antes de trabajar, `POST /issues/{id}/checkout` hace un `UPDATE … WHERE status IN (…) AND
  (assignee IS NULL OR assignee = yo)`. Si otro la tiene: `409`, y la regla es «nunca reintentes un 409».
- **Coalescer wakes**: si el agente ya está corriendo en esa tarea, el wake nuevo se une a la ejecución o espera
  detrás (`wake-queue/domain/policy.ts`). Nunca dos ejecuciones del mismo agente en la misma tarea.
- **Nada de esperar en bucle**: «usa subtareas y bloqueos, no hagas polling». El agente sale y el servidor lo
  vuelve a despertar cuando cambie algo.
- **Toda tarea viva tiene un camino**: si está `in_progress` tiene que haber una ejecución, un wake en cola, un
  bloqueo con dueño o una pregunta pendiente. Si no, aparece como «el agente necesita atención».
- **Preguntas al humano son objetos, no prosa**: `ask_user_questions` / `request_confirmation` guardados en la
  tarea + estado `in_review`. Cuando respondes, se despierta al agente (`continuationPolicy: wake_assignee`).

## 3. Cómo se crean los agentes

- Desde la UI (tú, «board») o **por otro agente** con la skill `skills/paperclip-create-agent`: mira qué
  adaptadores hay, copia la configuración de agentes parecidos, redacta rol + `reportsTo` + skills + adaptador y
  pide una **aprobación `hire_agent`**. Solo si la apruebas se crea la fila.
- Las instrucciones del agente son un `AGENTS.md` corto (identidad y responsabilidad). Las reglas de coordinación
  las pone la skill común; el «cómo se trabaja» lo ponen las skills del repo.
- Heartbeat por temporizador **apagado por defecto**: los agentes despiertan por asignación o comentario.
- Plantillas de equipos (`packages/teams-catalog`) para crear CEO/CTO/ingenieros de golpe.

## 4. Adaptadores

Interfaz mínima (`docs/adapters/creating-an-adapter.md`): `execute(ctx) → {exitCode, usage, costUsd,
sessionParams, …}` + `testEnvironment()` + un parser de la salida para la UI. Igual que nuestros
`localharness/adapters/*.py`. Diferencias útiles:
- `sessionParams` devuelto por la ejecución se guarda y se pasa en el siguiente wake → continuidad de sesión.
- `context_mode`: `thin` (solo IDs, el agente pide el resto por API) o `fat` (todo en el prompt). Para modelos
  locales pequeños, `fat` ahorra llamadas a herramientas.
- Para modelos locales usan **CLIs de agente ya hechas** (`opencode_local`, `hermes_local`, `pi_local`) apuntando a
  un endpoint OpenAI local, no un bucle propio.
- Regla «no-remote-git»: el worktree local es lo único que persiste entre ejecuciones; ningún adaptador hace push.
  (Ya lo cumplimos.)

## 5. Comparación con LocalHarness

| | LocalHarness hoy | Paperclip |
|---|---|---|
| Quién decide el reparto | El Director genera **un plan JSON de una vez** (`hierarchy.py`) | Cada agente crea subtareas cuando las necesita |
| Ejecución | Subtareas **en serie** en un worktree, script fijo Director → trabajadores → jefe técnico | Por eventos: cada cambio en el tablero despierta a quien toca |
| Comunicación | Prompts que arma el orquestador; el agente no puede hablar con otro | Tareas + comentarios + estados, vía API/MCP |
| Jerarquía | Roles implícitos en el código | `reports_to` en BD → organigrama real |
| Preguntas a ti | Niveles N0/N1/N2 + `reply` | Interacciones tipadas + `in_review` + wake al responder |
| Herramientas del agente hacia el sistema | `mcp_local.py` (solo `local_ask`, `local_write_file`) | MCP con ~40 herramientas de tablero |

Lo bueno: **ya tenemos las piezas base** (SQLite con tareas y eventos, worktrees, adaptadores, un servidor MCP propio,
`POST /tasks/{id}/reply`, niveles de riesgo). Falta pasar del «guion fijo» al «tablero + wakes».

## 6. Propuesta para LocalHarness (por fases)

**Fase A — tablero (BD, sin cambiar la GUI aún)**
- `agents`: añadir `reports_to`, `role`, `title`, `status`.
- `tasks`: añadir `parent_id`, `assignee_agent_id`, estados `todo/in_progress/in_review/blocked/done/cancelled`,
  `blocked_by` (tabla `task_blockers`), `work_mode` (`standard/ask/planning`), `checkout_run_id`.
- Tabla `comments` (autor agente o humano). Los eventos actuales siguen siendo el log de cada ejecución.

**Fase B — wakes**
- Tabla `wakes` (agente, tarea, motivo, payload, estado) y un bucle en el servidor que las consume: una ejecución
  por agente a la vez, coalescer si ya está corriendo en esa tarea.
- Disparadores: asignar → `assigned`; comentar → `commented`; hija `done` → `children_completed` al padre;
  bloqueos resueltos → `blockers_resolved`; tu respuesta → `answered`.
- Topes duros (como pidió Lucas en la tarea 8): wakes por tarea, tiempo y tokens; al pasarse, `blocked` y a ti.

**Fase C — herramientas de tablero en nuestro MCP** (`mcp_local.py` → `mcp_board.py`)
- `get_task`, `list_my_tasks`, `create_subtask(title, prompt, assignee, blocks_me)`, `comment`,
  `set_status(done|in_review|blocked, note)`, `ask_user(question)`. Token por ejecución como ya hacemos con la
  clave de llama-server. Claude y Codex las usan por `--mcp-config`; los modelos locales, por el bucle de
  herramientas de la tarea 8 (mismas definiciones en formato OpenAI `tools`).

**Fase D — skill y prompt de despertar**
- `skills/harness/SKILL.md` corto (en español) con el procedimiento: leer el wake → trabajar → dejar estado →
  delegar con subtareas, nunca esperar en bucle.
- Prompt de despertar = tarea + motivo + comentarios nuevos (estilo «Wake Payload»), en modo `fat` para modelos
  locales.

**Fase E — el Director deja de planificar todo de golpe**: pasa a ser un agente más arriba del organigrama que
recibe la petición, crea subtareas y despierta cuando acaban. El jefe técnico es el revisor de cada subtarea
(`in_review` → aprobar o pedir cambios). El plan JSON actual puede quedarse como «primer movimiento» del Director.

Lo que **no** copiaríamos: multiempresa, Postgres, presupuestos en céntimos, SSO, la maquinaria de recuperación de
la §8.2 (cientos de reglas), plugins, nube. Para un banco local con SQLite sobra.

## 7. Hardware previsto (M40 24 GB + 3060 12 GB + 32 GB RAM)

- 36 GB de VRAM entre las dos: llama-server reparte con `--tensor-split` (p. ej. `24,12`) o `-sm layer`.
- La M40 es Maxwell (CUDA 5.2): sin tensor cores, FP16 lento; usar un build de llama.cpp con CUDA 12.x (CUDA 13
  ya no soporta Maxwell) y compilar con `CMAKE_CUDA_ARCHITECTURES="52;86"`. La velocidad la marcará la M40.
- Candidatos para agente con herramientas: Qwen3.6-35B-A3B Q4 (~20 GB, MoE: va bien incluso con expertos en RAM
  usando `--n-cpu-moe`) o Qwen3.6-27B Q4 (~16 GB). Contexto 64k con `-ctk q8_0 -ctv q8_0`.
- Ajustes → Modelos locales necesitará campos para `tensor-split` y `n-cpu-moe` por modelo (hoy van en `extra`).
