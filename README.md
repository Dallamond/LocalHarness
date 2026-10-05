# LocalHarness

Banco local de agentes: registras repos, creas tareas, un agente (Claude / Codex / modelo local)
trabaja en un git worktree aislado y tú revisas el diff antes de integrar. Nunca hace push solo.

Estado: M0 (Claude), M1 y M2 hechos (CLI + API + GUI web). Ver `docs/HOJA-DE-RUTA.md` y `docs/VIABILIDAD.md`.
En este PC `python` es el alias de la Store: usar `py -3.12`.

```
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -e .[server]   # una vez
.venv/Scripts/python -m unittest discover -s tests -t .   # 25 pruebas con CLIs falsas (nunca llaman a la real)
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

- `localharness/api.py`       FastAPI + SSE: proyectos, agentes, tareas, eventos, diff, aprobar/rechazar/integrar/cancelar
- `web/`                      Vue 3 + Vite, estética blueprint de Arena LLM (Tareas, Ejecución, Proyectos y agentes)
- `localharness/cli.py`       órdenes de M1 (doctor, project, agent, run, tasks, show, merge, discard)
- `localharness/adapters/`   un adaptador por CLI: construye el comando y traduce su JSONL a eventos comunes
- `localharness/binaries.py` en Windows lanza el exe real del shim de npm (sin cmd.exe)
- `localharness/workspace.py` rama + worktree por tarea, diff, checkpoint, merge (solo con aprobación)
- `localharness/runner.py`    subproceso asíncrono, streaming línea a línea, timeout y cancelación
- `localharness/store.py`     SQLite (proyectos, agentes, tareas, eventos) con migraciones como Arena LLM
- `localharness/orchestrator.py` ciclo completo de una tarea → estado `review`
