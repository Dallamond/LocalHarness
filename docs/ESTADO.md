# Estado y traspaso — leer primero al retomar (también desde Claude Code en la web)

Última actualización: 05/10/2026. Hoja de ruta: `docs/HOJA-DE-RUTA.md`.

## Dónde estamos
| Hito | Estado |
|---|---|
| M0 Claude | ✅ verificado con la CLI real (`tests/fixtures_reales/`) |
| M0 Codex | ⏸ aparcado por decisión de Lucas (no instalado) |
| M1 CLI | ✅ |
| M2 API + GUI | ✅ probado con CLI falsa (también en navegador) |
| M3 Jerarquía | ✅ Director + jefe técnico + N0/N1/N2 + bandeja; CLI y API. Probado real con Haiku (0,087 $) |
| M4 Modelos locales | 🔄 proveedor `local` probado real con Qwen2.5-Coder 7B Q8 (Director y jefe, coste 0) |
| GUI de M3 | ✅ Pendiente de ti, Planes, detalle de plan; probada en navegador con agentes locales |

## Decisiones de Lucas (05/10/2026)
- **Gastar lo mínimo del plan Pro de Claude** (iba por el 82 % semanal). Probar con CLIs falsas; ejecuciones reales
  solo con Sonnet y topes (`--max-turns`, `--max-budget-usd`). Tiene ~100 € de créditos de Claude en la nube para
  cuando se agote el límite (pendiente aclarar si son créditos de API o uso extra).
- **La estética «blueprint» es provisional.** En el futuro la GUI será una pequeña oficina simulada (low-poly o 2D,
  por decidir). Prioridad ahora: que todo funcione. No invertir en estilos.
- Pruebas de navegador: normalmente se las pide a Lucas con una lista de pasos; en su ausencia, las hace Claude.
- Codex aparcado. Repo en GitHub: `Dallamond/LocalHarness`, rama `main`. Nunca push desde los agentes.

## Cómo trabajar en el repo
```
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -e .[server]     # Windows (python = alias de la Store)
python3 -m venv .venv && .venv/bin/python -m pip install -e .[server]          # Linux / web
<python> -m unittest discover -s tests -t .      # NUNCA llaman a la CLI real (binario falso fijado)
cd web && npm install && npm run build           # GUI; `<python> -m localharness serve` → :8095
```
Trampas conocidas:
- En Windows los scripts de edición con heredoc + `\n` dentro de cadenas Python se rompen: usar Edit/Write.
- `Path.write_text` en Windows escribe CRLF: pasar `newline="\n"`.
- En la web (Linux) no hay `claude` logueado: no intentar ejecuciones reales allí.

## M3 — cómo funciona (hierarchy.py)
- Un plan = una rama `localharness/plan-N` y un worktree. Subtareas EN SERIE, cada una con su commit
  (`base_commit..head_commit` = su diff). Tareas con `kind`: director | worker | reviewer.
- Nivel de cada subtarea = máx(riesgo declarado por el Director, reglas de policy.py sobre el diff, revisor).
  N1 → lo aprueba el jefe técnico (si hay); N2 → el plan se para (`paused`) y aparece en `/api/inbox`.
- Plan con > 3 subtareas o riesgo alto → `awaiting_you` antes de ejecutar. Plan terminado → `ready`;
  integrar la rama del plan siempre lo decides tú (`plan merge`). Rechazar una subtarea deshace SU commit.
- CLI: `plan new <proyecto> "<petición>" --director X --reviewer Y`, `plan inbox`, `plan decide <tarea> --approve`,
  `plan approve|merge|reject|show <plan>`.

## M4 — modelos locales
- `python -m localharness llama models` (lee `%APPDATA%/ArenaLLM/agent.json`), `llama serve <parte del nombre>`,
  `llama status`. Agente: `agent add qwen --provider local --role jefe` (config `base_url`, por defecto :8080).
- Un modelo local NO tiene herramientas: recibe el contexto del repo en el prompt (`repo_context` caracteres) y
  no se le asignan subtareas de escritura (`can_write=False`). Útil como Director o jefe técnico gratis.

## Pruebas reales hechas (05/10/2026)
- M3 con Claude Haiku (Director, 2 trabajadores, jefe): plan correcto, ambas subtareas aprobadas por el jefe, 0,087 $.
  Destapó un fallo ya corregido: la salida de git se leía en cp1252 y el revisor veía tildes rotas.
- M4 con Qwen2.5-Coder 7B Q8 en la 3060 (`llama serve qwen2.5-coder-7b`; tarda ~4 min en cargar del disco):
  consulta de solo lectura correcta en 28 s; plan con Director y jefe locales en 14 s; el jefe local detectó que
  el trabajador (falso) no hizo lo pedido y escaló a N2. Todo coste 0.

## Pendiente inmediato
1. Plan cuyas subtareas no cambian nada: debería terminar `done`, no `ready` (no hay nada que integrar).
   En el detalle de plan, ocultar «Ver diff» si la subtarea no tiene cambios.
2. M4: medir calidad del revisor local frente a Claude con el mismo diff (criterio de aceptación de M4) y probar
   Qwen3.5-9B / Qwen-2.5-Coder-14B. Reparto 3060/M40 cuando llegue la tarjeta.
3. Las tareas sueltas antiguas sin cambios que quedaron en `review` siguen en la bandeja: descartarlas o migrarlas.
4. llama-server avisa de CORS abierto: valorar `--api-key` (solo escucha en 127.0.0.1).
5. M5 (skills y memoria Markdown inyectadas) y M6 (rama de integración, limpieza de worktrees huérfanos).
6. Estética: sustituir la «blueprint» por la oficina simulada cuando Lucas decida el estilo.

## Hallazgos técnicos clave (no repetir)
- La CLI hija va aislada: `--safe-mode --strict-mcp-config` (sin eso, 245k tokens por «ok»). `--bare` prohíbe OAuth.
- `--tools` es el límite duro de herramientas. Prompt por stdin. En Windows se lanza el `.exe` real del shim npm.
- `rate_limit_event` → evento `limit` con uso de 5 h / 7 días.
- La CLI tiene `--json-schema` para salida estructurada (útil para Director/jefe técnico).
