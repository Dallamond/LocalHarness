# Viabilidad y reciclaje — 05/10/2026

## Veredicto
Viable como MVP acotado. El riesgo no es técnico sino de alcance: ya existen orquestadores maduros
(Agent Orchestrator 12,8k★ Apache-2.0; Vibe Kanban Apache-2.0; parallel-code MIT). El sentido de
construir el propio es lo que ellos NO cubren: modelos locales en tus GPUs, memoria Markdown por
proyecto, tu UI y el contenido para vídeos. Por eso: núcleo pequeño propio + piezas prestadas.

## Qué demuestra ya el prototipo (8 pruebas, CLIs FALSAS)
Adaptadores Claude/Codex → eventos comunes; worktree+rama por tarea; el agente no toca `main`;
diff incluye archivos nuevos; merge solo explícito; fallo por código de salida / binario ausente;
estado y eventos en SQLite; coste y session_id guardados.

## Qué NO está demostrado (hacer primero en tu PC)
1. Formato real de `claude -p --output-format stream-json --verbose` y `codex exec --json`:
   los parsers se escribieron desde la documentación. En el entorno de pruebas `claude` es un stub.
   → Guardar una salida real de cada CLI como fixture y adaptar los parsers.
2. Windows: binarios instalados con npm son `.cmd`; `create_subprocess_exec` puede no resolverlos.
   Resolver con `shutil.which` y probar. Decidir dónde corre el harness (Windows o nodo Proxmox/Linux)
   porque ahí deben estar los repos y las CLI autenticadas.
3. Autenticación en modo automático (`claude setup-token`, `CODEX_API_KEY`) y condiciones de uso de
   cada plan para ejecuciones no interactivas: comprobarlo antes de automatizar.
4. Modelos locales: llama-server no es un agente con herramientas. Para tareas acotadas (resumir,
   clasificar, revisar) basta `stream_chat` de Arena. Para implementar hace falta un agente real
   (p. ej. Aider/OpenCode apuntando al endpoint OpenAI-compatible de llama-server) o tu pasarela
   OmniRoute — a verificar.

## Reciclaje de tus repos
| Pieza | Origen | Uso |
|---|---|---|
| EventHub + SSE (`hub.py`, 37 líneas) | Arena LLM | copiar tal cual: eventos de tarea en vivo |
| Migraciones SQLite (`db.py`) | Arena LLM | ya replicado en `store.py` |
| `stream_chat` (TTFT, t/s, usage) | Arena LLM `runs/llm.py` | proveedor `local` para tareas acotadas |
| Ciclo de runs + `mark_interrupted_runs` | Arena LLM `runs/manager.py` | reanudar/limpiar tareas colgadas al reiniciar |
| `launch.py`, `fit.py`, agente de hardware | Arena LLM | lanzar y repartir llama-server por GPU |
| Componentes Vue (BlueprintCard, StatusChip, SideNav, TopBar, ResponsesMatrix, LineChart) | Arena LLM `web/` | misma estética «blueprint»; ResponsesMatrix sirve para comparar agentes en la misma tarea |
| Catálogo de skills (`skills-src/*/SKILL.md`, 21) y `.claude/skills` | Dashboard homelab / vault | ya están en formato SKILL.md: el banco de skills existe |
| Perfiles de agente en `.claude/agents/*.md` | dopehitsv3 | formato de partida para el catálogo de agentes |
| Fastify + SQLite + React, despliegue LXC | Hub personal | solo si se prefiere TypeScript; mezclar dos stacks no compensa |

Recomendación de stack: Python (FastAPI + SQLite + Vue), igual que Arena, para reutilizar sin traducir.

## Repos externos para estudiar (no forkear)
| Repo | Licencia | Qué aprovechar |
|---|---|---|
| ComposioHQ/agent-orchestrator | Apache-2.0 | aislamiento por worker, ciclo de sesión, estado derivado, retorno de CI al agente |
| johannesjo/parallel-code | MIT | worktrees (symlink de node_modules), visor de diff, merge selectivo |
| majiayu000/harness | MIT | adaptadores Claude/Codex, revisión cruzada, política de permisos (50★, joven) |
| Vibe Kanban | Apache-2.0 | tablero + descomposición de tareas por MCP |
| Aider repo map | Apache-2.0 | mapa compacto de símbolos del repo para el contexto |
| OpenHands | MIT (núcleo) | separación historial de eventos / gestión de contexto |
Evitar copiar código de Claude Squad (AGPL-3.0). Comprobar la licencia de cada repo antes de copiar.

## Orden recomendado
1. Fixtures reales de ambas CLI y ajuste de parsers (medio día).
2. API FastAPI mínima + SSE (reutiliza hub.py): proyectos, agentes, tareas, ejecutar, ver diff, aprobar.
3. Vista Tareas/Ejecución en Vue con componentes de Arena.
4. Memoria: selector de .md por proyecto inyectado como `--append-system-prompt` (Claude) / prefijo (Codex).
5. Proveedor `local` (stream_chat) y primera tarea acotada con tu Qwen.
6. Segundo agente jefe y modo planificador/revisor.

---
# Actualización: lectura del código real de otros orquestadores (05/10/2026)

Repos leídos (clonados con `--depth 1` en `C:\Users\Lucas\_referencias`): majiayu000/harness (MIT),
johannesjo/parallel-code (MIT), BloopAI/vibe-kanban (Apache-2.0), ComposioHQ/agent-orchestrator
(Apache-2.0). emdash (carpeta con licencia propia «General Action») NO se ha leído a fondo.
Solo se han mirado ficheros clave; no es una auditoría completa.

## Dos familias de diseño
1. **`-p` + JSONL** (majiayu000/harness): subproceso, salida estructurada, sin TUI. Es lo que usa mi MVP.
2. **Protocolo bidireccional / PTY** (parallel-code y vibe-kanban hablan stream-json con
   `control_request`/permisos interactivos; agent-orchestrator mete las TUI reales en un
   ConPTY). Da aprobaciones en vivo, pero es bastante más complejo.
Decisión: MVP con `-p`; aprobaciones en vivo como fase posterior.

## Errores míos que el código ajeno ha destapado (ya corregidos y con prueba)
- **Permisos:** con `acceptEdits` y sin nadie delante, cualquier Bash queda denegado o colgado.
  harness usa `--permission-mode bypassPermissions` + lista blanca de herramientas. Ahora el
  adaptador hace eso (lectura: Read/Glob/Grep; escritura: + Edit/Write; Bash solo si se concede).
- **El prompt va justo tras `-p`** (harness documenta que al final da «Input must be provided»).
- **Fallos con código de salida 0:** Claude informa de errores en el evento `result`
  (`is_error` o subtype `error_*`, con lista `errors`). Mi parser solo miraba `success`; ahora cubre ambos.
- **Codex:** items en snake_case y camelCase; hay `warning`, `turn.failed` e items de tipo `error`;
  los tipos desconocidos deben exponerse (antes los descartaba); el caché va dentro de `input_tokens`.
  Añadido `-c approval_policy="never"`.
- **Worktrees:** creación concurrente corrompe metadatos (vibe usa un lock global); restos de intentos
  fallidos bloquean `worktree add` (ahora se limpia ruta y rama huérfanas); un symlink a `node_modules`
  NO lo ignora un `.gitignore` con `node_modules/` → se añade a `info/exclude` (lección de parallel-code).
- **Windows:** el binario se resuelve con `shutil.which` (shims `.cmd`). Pendiente probarlo en tu PC.

## Contradicción por resolver con una ejecución real
La CLI oficial dice que `--allowedTools` solo auto-aprueba y que para limitar herramientas se usa `--tools`;
harness afirma que `--allowedTools` da límite duro desde la 2.1.70. El adaptador pasa ambos. Hay que
comprobar en tu PC cuál se aplica realmente.

## Qué reutilizar y de dónde (todo por revisar antes de copiar)
| Necesidad | Mirar | Licencia |
|---|---|---|
| Parsers Claude/Codex y tests con salidas reales | harness `crates/harness-agents/src/{claude_stream_json,codex_exec_parser}*.rs` | MIT |
| Fixture determinista del protocolo de Claude | parallel-code `electron/chat/fixtures/claude-process.mjs` | MIT |
| Ciclo de vida de worktrees robusto | vibe-kanban `crates/worktree-manager/src/worktree_manager.rs` | Apache-2.0 |
| Limpieza, node_modules, excludes, permisos de archivos | parallel-code `electron/ipc/{worktree-cleanup,worktree-node-modules,git-exclude}.ts` | MIT |
| Lanzar TUIs en ConPTY (Windows) | agent-orchestrator `backend/internal/adapters/runtime/conpty/` | Apache-2.0 |

Los fixtures reales de parallel-code y los tests de harness sirven para verificar mis parsers sin gastar tokens.
