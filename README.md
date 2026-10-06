# LocalHarness

Banco local de agentes de programación. Registras repos, pides algo y un agente (Claude por la CLI oficial con
tu suscripción, o un modelo local servido por llama-server) trabaja en un **git worktree aislado** con su propia
rama. Tú revisas el diff antes de integrar. Para peticiones grandes, un **Director** hace un plan, los
trabajadores lo ejecutan paso a paso, un **jefe técnico** revisa lo de riesgo medio y lo importante te llega a ti.
Nunca hace push: integrar pide tu confirmación y el push es tuyo.

**Al retomar, leer `docs/OBJETIVOS.md` (rumbo nuevo) y `docs/ESTADO.md`.** El comportamiento del Director está
en `manual/director.md`. Guía de funciones e implementación: [`docs/GUIA.md`](docs/GUIA.md).

## Estado

| Hito | Estado |
|---|---|
| M0 Verificación con la CLI real | ✅ Claude · ⏸ Codex aparcado (no instalado) |
| M1 Núcleo por CLI | ✅ |
| M2 API + SSE + GUI | ✅ probado con CLI falsa |
| M3 Jerarquía (Director, jefe técnico, N0/N1/N2, bandeja) | ✅ CLI, API y GUI |
| M4 Modelos locales (`local`, `local_agent`) | 🔄 `local` probado real; `local_agent` v1 sin probar con Qwen real |
| M5 Skills y memoria | ✅ |
| M6 Flujo git (conflictos, limpieza) | 🔄 falta rama de integración por proyecto |
| Delegación de Claude en el modelo local (MCP propio) | ✅ verificada con Haiku real |

Próximo (ver `docs/OBJETIVOS.md`): plan editable en el Inicio, ver a los subagentes trabajando, catálogo de roles
y skills, oficina 3D del prototipo (`docs/prototipos/`) y el agente Atlas.

## Instalación y arranque

En este PC `python` es el alias de la Store: usar `py -3.12`.

```
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -e .[server]   # una vez
.venv/Scripts/python -m unittest discover -s tests -t .   # 101 pruebas con CLIs falsas (nunca llaman a la real)
py -3.12 -m localharness doctor                   # git, CLIs, login de suscripción
py -3.12 -m localharness project add demo D:/ruta/al/repo
py -3.12 -m localharness agent add sonnet-w --provider claude --model sonnet --max-turns 10 --budget 1
py -3.12 -m localharness run demo "arregla el bug de X" --agent sonnet-w
py -3.12 -m localharness show 1 --diff            # revisar
py -3.12 -m localharness merge 1                  # integrar (pide confirmación, nunca push)
```

GUI (M2):
```
cd web && npm install && npm run build && cd ..   # una vez, y tras cambiar la web
.venv/Scripts/python -m localharness serve         # http://127.0.0.1:8095
```
Desarrollo de la web con recarga: `cd web && npm run dev` (http://127.0.0.1:5174, /api va al 8095).

En Linux el intérprete del venv es `.venv/bin/python`. Sin `claude` logueado no se lanzan tareas reales de
Claude; sin llama-server los agentes locales no responden (todo lo demás funciona).

## Uso rápido

**Por CLI** (`lh` = `.venv/Scripts/python -m localharness`):

| Orden | Qué hace |
|---|---|
| `lh sandbox [--reset]` | Repo de pruebas con fallos a propósito y agentes ya creados (`docs/PROBAR.md`) |
| `lh plan new <proyecto> "<petición>" --director X [--reviewer Y]` | Director → plan → trabajadores → jefe técnico |
| `lh plan inbox` · `plan decide <tarea> --approve\|--reject` | Lo que espera tu decisión |
| `lh plan approve\|merge\|reject\|show <plan>` · `plan list` | Gestionar un plan |
| `lh tasks` · `discard <id>` | Listar tareas sueltas · descartar una (borra rama y worktree) |
| `lh skills` · `project memory <proyecto> [ruta]` | Catálogo de skills · carpeta de memoria del proyecto |
| `lh llama models\|serve <modelo>\|status` | Modelos GGUF y llama-server a mano |
| `lh cleanup [--dry-run]` | Borra worktrees y ramas de lo ya cerrado |

**Por la GUI** (http://127.0.0.1:8095):
- **Inicio**: cifras, «Te toca a ti» con botones de decisión, el equipo y qué hace cada agente, lo último que pasó.
- **Chat**: conversaciones con un agente o con el equipo (Director); vincular carpeta; responder al agente.
- **Pendiente de ti**: decisiones N2. **Planes**: nueva petición al Director e historial; detalle de cada plan.
- **Modelos locales**: arrancar/parar llama-server con un GGUF, progreso de carga, tok/s, agentes locales.
- **Ajustes**: agentes, proyectos, aprobaciones, ejecución y mantenimiento, skills y memoria, apariencia.

## Mapa del código

- `localharness/cli.py`        órdenes (doctor, project, agent, run, tasks, show, merge, discard, plan, llama, sandbox, cleanup, skills, serve)
- `localharness/api.py`        FastAPI + SSE: proyectos, agentes, tareas, planes, bandeja, ajustes, modelos locales, eventos
- `localharness/orchestrator.py` ciclo de una tarea: worktree → agente → checkpoint → `review`/`done`; delegación MCP
- `localharness/hierarchy.py`  M3: Director → plan JSON → trabajadores en serie → jefe técnico → tú; bandeja
- `localharness/policy.py`     niveles N0/N1/N2 con reglas deterministas sobre el diff
- `localharness/adapters/`     un adaptador por proveedor (comando + traducción a eventos comunes):
  - `claude.py`  `claude -p` aislado (`--safe-mode` o, con delegación, `--setting-sources ""`), topes y herramientas
  - `codex.py`   `codex exec --json` (aparcado, sin verificar con la CLI real)
  - `local.py`   un mensaje a llama-server con el contexto del repo en el prompt; no escribe
  - `local_agent.py` bucle de agente con herramientas confinadas al worktree (leer, buscar, escribir, ejecutar…)
- `localharness/mcp_local.py`  servidor MCP stdio propio: Claude encarga a Qwen `local_ask`, `local_write_file`, `local_research`
- `localharness/context.py`    M5: skills (`SKILL.md`) y memoria del proyecto inyectadas en el prompt
- `localharness/llama.py`      lanzar llama-server (con `--api-key`), listar GGUF, progreso de carga
- `localharness/workspace.py`  rama + worktree por tarea o plan, diff, checkpoint, merge con detección de conflictos
- `localharness/maintenance.py` M6: limpieza de worktrees y ramas de lo cerrado
- `localharness/actions.py`    aprobar / integrar / descartar una tarea suelta (CLI y API)
- `localharness/runner.py`     subproceso asíncrono, streaming línea a línea, timeout y cancelación
- `localharness/store.py`      SQLite (proyectos, agentes, tareas, eventos, planes, ajustes) con migraciones
- `localharness/settings.py`   ajustes editables desde la GUI (tabla `settings`)
- `localharness/sandbox.py`    repo de pruebas y agentes de ejemplo
- `localharness/binaries.py`   en Windows lanza el exe real del shim de npm (sin cmd.exe)
- `localharness/hub.py`        difusión de eventos a los clientes SSE
- `manual/director.md`         el «algoritmo» del Director, editable sin tocar código
- `skills/`                    skills propias: `tests-primero`, `cambios-minimos`, `revision-de-diff`
- `web/`                       Vue 3 + Vite (Inicio, Chat, Pendiente de ti, Planes, Modelos locales, Ajustes)
- `tests/`                     pruebas con CLIs falsas (`tests/fakes/`) y fixtures reales de Claude

## Documentación

| Documento | Para qué |
|---|---|
| [`docs/GUIA.md`](docs/GUIA.md) | Funciones e implementación: conceptos, proveedores, jerarquía, git, API, eventos, configuración |
| [`docs/OBJETIVOS.md`](docs/OBJETIVOS.md) | Rumbo nuevo: manual + catálogo, objetivos en orden |
| [`docs/DISENO-OFICINA.md`](docs/DISENO-OFICINA.md) | Diseño de la oficina y de cómo se comunican los agentes (borrador) |
| [`docs/ESTADO.md`](docs/ESTADO.md) | Estado y traspaso entre sesiones: leer primero al retomar |
| [`docs/HOJA-DE-RUTA.md`](docs/HOJA-DE-RUTA.md) | Decisiones cerradas, cumplimiento con la suscripción, hitos M0–M6 |
| [`docs/PROBAR.md`](docs/PROBAR.md) | Pruebas manuales paso a paso con el sandbox |
| [`docs/VIABILIDAD.md`](docs/VIABILIDAD.md) | Estudio de viabilidad inicial |
