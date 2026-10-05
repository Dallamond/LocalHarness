# LocalHarness

Banco local de agentes: registras repos, creas tareas, un agente (Claude / Codex / modelo local)
trabaja en un git worktree aislado y tú revisas el diff antes de integrar. Nunca hace push solo.

Estado: M0 (Claude) y M1 hechos; sin GUI. Ver `docs/HOJA-DE-RUTA.md` y `docs/VIABILIDAD.md`.
En este PC `python` es el alias de la Store: usar `py -3.12`.

```
py -3.12 -m unittest discover -s tests -t .       # 21 pruebas con CLIs falsas (nunca llaman a la real)
py -3.12 -m localharness doctor                   # git, CLIs, login de suscripción
py -3.12 -m localharness project add demo D:/ruta/al/repo
py -3.12 -m localharness agent add sonnet-w --provider claude --model sonnet --max-turns 10 --budget 1
py -3.12 -m localharness run demo "arregla el bug de X" --agent sonnet-w
py -3.12 -m localharness show 1 --diff            # revisar
py -3.12 -m localharness merge 1                  # integrar (pide confirmación, nunca push)
```

- `localharness/cli.py`       órdenes de M1 (doctor, project, agent, run, tasks, show, merge, discard)
- `localharness/adapters/`   un adaptador por CLI: construye el comando y traduce su JSONL a eventos comunes
- `localharness/binaries.py` en Windows lanza el exe real del shim de npm (sin cmd.exe)
- `localharness/workspace.py` rama + worktree por tarea, diff, checkpoint, merge (solo con aprobación)
- `localharness/runner.py`    subproceso asíncrono, streaming línea a línea, timeout y cancelación
- `localharness/store.py`     SQLite (proyectos, agentes, tareas, eventos) con migraciones como Arena LLM
- `localharness/orchestrator.py` ciclo completo de una tarea → estado `review`
