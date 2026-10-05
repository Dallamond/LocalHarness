# LocalHarness — hoja de ruta (v0.2, 05/10/2026)

Prototipo básico, repo propio e independiente (no se mezcla con Arena LLM ni con ningún otro repo tuyo).
Corre en tu PC principal (Windows, RTX 3060 y pronto Tesla M40). Se mejora por iteraciones.

## 0. Estado (05/10/2026)
| Hito | Estado |
|---|---|
| M0 Claude | ✅ Verificado con la CLI real (ver `tests/fixtures_reales/informe.json`) |
| M0 Codex | ⏳ Codex no está instalado en el PC |
| M1 | ✅ CLI `py -3.12 -m localharness …`; tarea real terminó en `review` y `main` intacto hasta `merge` |
| M2–M6 | Pendientes |

Hallazgos de M0 que cambian el diseño:
- **Aislamiento obligatorio.** Sin aislar, la CLI hija hereda tus MCP (Canva, Vercel…), plugins, hooks y CLAUDE.md:
  245k tokens de contexto para responder «ok» (≈1,96 $ equivalentes de tu plan). Con `--safe-mode --strict-mcp-config`
  bajan a ~4,6k (144× menos). `--bare` no vale: prohíbe el login de suscripción. Consecuencia para M5: el contexto
  (memoria, skills, CLAUDE.md del proyecto) lo inyecta LocalHarness explícitamente, nunca se hereda.
- **`--tools` es el límite duro** de herramientas (riesgo §6 resuelto).
- **Windows:** `claude.CMD` de npm pasa por cmd.exe y rompe prompts con `& | % ^ "`. Se lanza directamente el
  `claude.exe` al que apunta el shim y el prompt va por **stdin** (sin límite de 32k de la línea de órdenes).
- **Contador de uso gratis:** cada ejecución emite `rate_limit_event` con la utilización de las ventanas de 5 h y
  7 días. Se guarda como evento `limit`; el CLI avisa a partir del 75 %.

## 1. Decisiones cerradas

| Tema | Decisión |
|---|---|
| Nombre | LocalHarness (paquete `localharness`) |
| Dónde corre | PC principal; accesible por LAN más adelante |
| Repo | Independiente. Se pueden copiar piezas sueltas de Arena (p. ej. `hub.py`), no enlazarlo |
| Stack | Python (FastAPI + SQLite) y Vue; estética «blueprint» cuando toque la GUI |
| Claude | Binario oficial `claude -p` con tu **suscripción** (login propio), nunca por API de pago |
| Alcance | Prototipo con funciones básicas; no paralelo masivo, no memoria autoescrita |
| Git | Los agentes nunca hacen push. El push lo haces tú (terminal o botón con tu confirmación) |
| Mando | Jerárquico: tú apruebas lo importante; jefes técnicos y planificadores deciden el resto |

## 2. Cumplimiento con la suscripción (restricciones de diseño)

Según la documentación de Claude Code, el login OAuth de suscripción es para uso ordinario de la herramienta
oficial; los desarrolladores que construyan productos deben usar API key, y no se permite recoger, guardar
ni intermediar credenciales de Claude.ai. Reglas que cumple el código:
1. Solo se lanza el binario `claude` **sin modificar**, ya logueado por ti. LocalHarness no lee, copia ni guarda tokens.
2. Nada de Agent SDK con credenciales de suscripción.
3. Se quita `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` del entorno de la CLI hija: en `-p` una API key presente se usa
   siempre y cobraría por tokens. Comprobación previa con `claude auth status` (debe decir `claude.ai`).
4. Un solo usuario (tú). Concurrencia baja por defecto (1–2 agentes de Claude a la vez).
5. Los límites de un plan de 20 € se agotan rápido con automatización: topes por tarea (`--max-turns`,
   `--max-budget-usd`), contador de uso y reparto de trabajo hacia Codex y modelos locales.
Codex con login de ChatGPT usa `~/.codex/auth.json`: se trata como una contraseña y no se toca.
Esto no es asesoría legal: las condiciones cambian; revísalas tú antes de automatizar más.
Fuentes: code.claude.com/docs/en/legal-and-compliance y /authentication; The Register (20/02/2026).

## 3. Modelo jerárquico

```
Tú ──aprueba── planes grandes, riesgo alto, merge a main, push
 └─ Director (planificador jefe)      read-only; convierte tu petición en un plan JSON
     └─ Jefes técnicos (por proyecto)  revisan diffs y aprueban lo de riesgo bajo/medio
         └─ Trabajadores              ejecutan en su worktree: Claude / Codex / modelo local
```
Un agente es una configuración (proveedor, modelo, rol, límites, herramientas), no código nuevo.
Sugerencia inicial: Director y jefes técnicos con Claude (poca salida, mucha calidad); trabajadores con Codex
o modelo local según la tarea; exploración, resumen y clasificación siempre en local.

### Niveles de aprobación
| Nivel | Quién decide | Cuándo |
|---|---|---|
| N0 automático | nadie | tareas de solo lectura; cambios pequeños en rutas permitidas y con tests en verde |
| N1 jefe técnico | agente jefe (queda registrado) | diff dentro de umbral, sin archivos sensibles, sin dependencias nuevas |
| N2 tú | tú | plan de una tarea grande; borrar archivos; dependencias; migraciones; config/CI/.env/secretos; diff sobre umbral (propuesta: >8 archivos o >300 líneas, editable); integrar en la rama principal; cualquier push |
El nivel final es el **máximo** entre el riesgo declarado por el planificador y el calculado por reglas
deterministas sobre el diff. Un LLM puede subir el nivel, nunca bajarlo.

### Límite honesto del MVP
Con `claude -p` y `codex exec` las aprobaciones ocurren en las fronteras de la tarea (plan → ejecución → diff),
no acción a acción. Para frenar una acción concreta durante la ejecución hace falta el protocolo bidireccional
que usan parallel-code y vibe-kanban (fase posterior). Mitigación del MVP: lista blanca de herramientas, sin
Bash por defecto, trabajo siempre en worktree y nunca push desde el agente.

## 4. Hitos (cada uno con criterio de aceptación comprobable)

**M0 — Verificación con CLI reales (primero).** `python scripts/spike.py` en tu PC.
Aceptación: login `claude.ai`; fixtures reales de Claude y Codex guardados; los parsers producen `session`, `text`,
`result`/`usage`; sabemos si `--tools Read` impide escribir; los binarios de npm se resuelven en Windows.

**M1 — Núcleo por línea de comandos.** `localharness run <proyecto> "<petición>" --agent X` → worktree → agente →
`review` con diff y coste. Ya existe el 80 % (14 pruebas). Falta ajustar parsers con los fixtures reales y el CLI.
Aceptación: una tarea real sobre un repo de prueba termina en `review` y no toca `main`.

**M2 — API + GUI mínima.** FastAPI + SSE (eventos en vivo), vistas Proyectos, Tareas y Ejecución, visor de diff,
botones Aprobar / Rechazar / Integrar. Aceptación: ciclo completo desde el navegador.

**M3 — Jerarquía y aprobaciones.** Director con plan JSON validado por esquema; jefes técnicos que revisan diffs;
política de riesgo N0/N1/N2 con reglas deterministas y bandeja «pendiente de ti». Aceptación: una petición grande
se divide, lo menor lo aprueba el jefe y lo importante te aparece a ti; todo queda en el registro.

**M4 — Modelos locales.** Proveedor `local` sobre llama-server (cliente de streaming tipo Arena) para tareas acotadas
(exploración, resumen, clasificación, revisión). Medir calidad antes de darles implementación. Reparto 3060/M40
cuando llegue la tarjeta. Aceptación: una tarea acotada resuelta por Qwen local y comparada con la de Claude.

**M5 — Skills y memoria.** Skills en formato `SKILL.md`; memoria Markdown por proyecto, solo lectura para el agente;
selección por tarea e inyección como texto de prompt (igual en todos los proveedores). Aceptación: la misma tarea
con y sin skill produce resultados distintos y el registro dice qué se inyectó.

**M6 — Flujo Git completo.** Rama de integración por proyecto (los jefes integran ahí), paso a `main` y push solo con
tu confirmación, checkpoints, limpieza de worktrees huérfanos, manejo de conflictos (parar y avisarte).

## 5. Fuera del MVP
Agentes en paralelo masivo, aprobaciones acción a acción, memoria que se reescribe sola, push automático,
acceso remoto, agente local con herramientas para implementar (Aider/OpenCode contra llama-server), sandbox Docker.

## 6. Riesgos abiertos
- Parser de Codex escrito desde documentación y código ajeno (Codex sin instalar). El de Claude ya está verificado.
- ~~`--tools` frente a `--allowedTools`~~: resuelto, `--tools` es el límite duro.
- Límites del plan de 20 €: pueden hacer inviable usar Claude en todos los roles; por eso Codex/local.
- Windows: procesos hijos probados con `claude.exe`; ConPTY sin probar (solo hace falta para aprobaciones en vivo).
- Conflictos de merge entre tareas sobre los mismos archivos: por ahora, una tarea por repo a la vez.

## 7. Pendiente de decidir (no bloquea M0–M2)
1. Qué proveedor es Director por defecto (propuesta: Claude con pocos turnos).
2. Umbral exacto de «grande» para N2 (propuesta en la tabla).
3. Si el Director puede crear agentes nuevos o solo elegir entre los que registras tú (propuesta: solo elegir).
4. Ficheros considerados sensibles por proyecto (propuesta: `.env*`, `*.pem`, `migrations/`, `.github/`, lockfiles).
