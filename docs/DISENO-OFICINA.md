# Diseño: cómo funciona todo y cómo se ve (borrador, 06/10/2026)

Documento de trabajo del objetivo 10a. Se rellena en conversación con Lucas; nada se programa hasta que lo
apruebe. ✅ = decidido por Lucas · 💡 = propuesta de Claude, pendiente · ❓ = pregunta abierta.

## 0. Decisiones de Lucas
- ✅ Al abrir sin misiones: la **oficina vacía** y un **resumen** (últimas tareas hechas y resumen del periodo:
  X tareas, X proyectos, X horas dedicadas…).
- ✅ El plan de cada misión está en una **pizarra en la pared**; al hacer clic se amplía y muestra qué agente
  lleva cada paso, en qué estado está el proyecto y qué pasos faltan.
- ✅ **Pensamiento profundo** activable y desactivable a mano, y además según la tarea y la importancia del agente.
- ✅ Puede haber **varias misiones activas a la vez en el mismo proyecto**.
- ✅ **Límite de tiempo por tarea** (por paso), además de los topes que ya hay.
- ✅ **Bucle continuo** también cuando se seleccione o cuando la misión lo requiera (no solo agentes locales).
- ✅ Si dos misiones coinciden en archivos, **una espera a la otra** (sin preguntar).
- ✅ Prioridad de Lucas: **cómo tienen funciones de agente los modelos locales** (internet, archivos) y **cómo se
  comunican con el Director** → sección 4b.
- ✅ (anteriores) Sin gamificación. Chat, Planes, Modelos y Ajustes siguen como páginas. Empezar con pocos roles y skills.

## 1. Conceptos (el vocabulario de todo lo demás)
| Concepto | Qué es | Hoy en el código |
|---|---|---|
| Proyecto | Un repo registrado | `projects` |
| **Misión** | Lo que pides con una frase. Tiene un plan, una rama y un worktree propios | `plans` (se renombra en la GUI) |
| **Paso** | Una subtarea del plan, con agente, riesgo, criterio de aceptación y estado | `tasks` con `plan_id` |
| **Rol** | Plantilla de agente (Explorador, Programador, Revisor…): modelo, herramientas, skills, MCP, pensamiento | 💡 nuevo (`roles/`) |
| **Agente** | Un rol trabajando en un paso concreto. Es lo que se ve como persona en un puesto | `agents` (hoy fijos) |
| **Encargo** | Trabajo que un agente pasa al modelo local (pensar, escribir, investigar) | eventos `delegate` |
| **Decisión** | Algo que espera tu respuesta: plan, paso de riesgo alto, integrar, pregunta de un agente | bandeja `/api/inbox` |

## 2. Ciclo de vida
**Misión:** `pensando plan` → `esperando tu aprobación` → `en marcha` ⇄ `pausada (te necesita)` → `lista para
integrar` → `integrada` · (o `cancelada` / `fallida` / `interrumpida`).

**Paso:** `en cola` → `trabajando` → `comprobando` (tests del criterio de aceptación) → `en revisión` (jefe
técnico) → `hecho` · si el revisor pide cambios: vuelve a `trabajando` con sus notas (💡 máximo 2 vueltas;
a la tercera, decisión tuya) · si es de riesgo alto: `te necesita`.

💡 **Interrumpida**: si se cierra LocalHarness con misiones en marcha, al volver quedan así con un botón
«Reanudar» que repite el paso que estaba a medias (el worktree conserva lo ya hecho). Hoy se cierran como huérfanas.

## 3. Procesos: quién ejecuta qué
```
Navegador (oficina) ──SSE/REST── Servidor LocalHarness (único dueño del estado, SQLite)
                                   ├─ Despachador: decide qué paso arranca y cuándo (colas + límites)
                                   ├─ Ejecutor por paso: lanza `claude -p` (un proceso por paso, en su worktree)
                                   │     └─ MCP local (un proceso por paso) ──► Cola de la GPU ──► llama-server
                                   └─ Ejecutor local: agentes locales ─────────► Cola de la GPU ──► llama-server
```
💡 Reglas del Despachador:
- **Claude**: como mucho N procesos a la vez (💡 2, editable). Si la ventana de 5 h pasa del 75 %, no arranca
  pasos nuevos de Claude y avisa; los que están en marcha terminan.
- **GPU (llama-server)**: un solo modelo cargado y una cola única para todos (agentes locales y encargos de
  Claude). Prioridad: encargo de un Claude que está esperando > paso de agente local > trabajo de fondo.
  Cambiar de modelo solo cuando la cola del actual está vacía (cargar cuesta minutos).
- **Orden**: los pasos de una misión van en orden; misiones distintas avanzan a la vez si hay hueco.
- **Varias misiones en un proyecto**: cada una en su rama y worktree. 💡 Si dos planes van a tocar el mismo
  archivo, se avisa en la pizarra y el segundo espera a que el primero se integre (se detecta antes con
  `merge-tree`, ya existe en M6).

## 4. Cómo se comunican los modelos
Nunca hablan directamente entre ellos: **todo pasa por LocalHarness**, que lo guarda y lo muestra (así se puede
ver, parar y repetir). Canales:
1. **Director → paso**: el `prompt` autocontenido del paso + criterio de aceptación + skills.
2. **Paso → sistema**: resultado final estructurado (💡 JSON: qué hizo, cómo lo comprobó, dudas, siguiente sugerido).
3. **Claude → modelo local**: encargos por MCP (`local_ask`, `local_write_file`, `local_research`).
4. **Revisor → trabajador**: notas de `request_changes`, que vuelven al mismo trabajador (reanuda su sesión).
5. 💡 **Diario de la misión**: cada paso terminado añade al diario un resumen corto de lo que hizo; los pasos
   siguientes lo reciben en su prompt. Es la memoria compartida de la misión (no la del proyecto).
6. 💡 **Agente → tú**: herramienta MCP `ask_human(pregunta, opciones)`: el paso se pausa y la pregunta va a
   la bandeja; tu respuesta vuelve al agente. Evita que adivine cuando algo es ambiguo.

## 4b. Modelos locales como agentes (internet + hablar con el Director)
💡 **Bucle de agente propio en LocalHarness** (Python, sin dependencias), en vez de una CLI externa: controlamos
eventos, tok/s, límites y Windows, y reutiliza el código de `mcp_local.py` (lectura confinada, DuckDuckGo).
```
LocalHarness ──(prompt del paso + herramientas)──► llama-server (Qwen)
     ▲                                                  │ responde con tool_calls
     └──── resultado de la herramienta ◄── ejecuta LocalHarness (confinado al worktree)
                 … repite hasta `terminar` o un tope (turnos, tiempo, tokens)
```
Herramientas v1 (pocas a propósito: los modelos pequeños fallan más cuantas más hay):
| Grupo | Herramientas | Límites |
|---|---|---|
| Archivos | `leer`, `listar`, `buscar`, `escribir`, `editar` | solo dentro del worktree, nunca `.git` |
| Comandos | `ejecutar` | lista blanca por proyecto (tests, linter), tiempo máximo, sin red |
| Internet | `buscar_web`, `leer_url` | DuckDuckGo; texto recortado por página |
| Equipo | `preguntar_director`, `avisar_progreso`, `terminar` | ver abajo |

**Hablar con el Director.** El Director no está «siempre encendido» (cada llamada a Claude es un proceso), así que:
- `preguntar_director(pregunta)`: el agente local se pausa; LocalHarness reanuda la sesión del Director
  (`--resume`, que ya conoce el plan) con la pregunta y el diario de la misión; la respuesta vuelve al agente
  como resultado de la herramienta. Gasta plan → 💡 máximo 3 preguntas por paso; después va a tu bandeja.
- Si el Director no puede responder, la pregunta pasa a ti (`ask_human`).
- `avisar_progreso(texto)`: frase corta para el bocadillo y el diario, sin gastar nada.
- `terminar(resumen, cómo_lo_comprobé)`: cierra el paso → comprobación (tests) → revisor (jefe técnico).
- Del Director/revisor al agente: el revisor puede devolver el paso con notas («sigue con esto»): el bucle
  continúa con la misma conversación + las notas, hasta «completado» o el tope de vueltas.

**Fiabilidad con modelos de 7–14B** (el riesgo real; hoy solo Qwen3.5-9B devuelve `tool_calls`):
- Validar cada llamada (nombre y argumentos); si viene mal, se le devuelve el error y reintenta (💡 máx. 2).
- Plan B si el modelo no hace `tool_calls`: forzar la salida con JSON de esquema fijo (`response_format` /
  gramática de llama-server; por verificar) con la forma `{"herramienta": ..., "argumentos": ...}`.
- Contexto corto (12 GB de VRAM): recortar las salidas de herramientas y resumir los turnos viejos.
- Detectar bucles (misma llamada 3 veces seguidas) → parar y avisar.
- Cada herramienta es un evento como los de Claude: la oficina lo muestra igual para todos.
- 💡 Más adelante: que el bucle sea **cliente MCP**, para dar a los agentes locales cualquier servidor MCP del catálogo.

## 5. Pensamiento profundo
💡 Tres niveles: **apagado · normal · profundo**.
- Por defecto según el rol: Director = profundo, Revisor = normal, Programador = normal, Explorador local = apagado.
- El Director puede marcar un paso como importante en el plan → profundo para ese paso.
- Tú lo cambias a mano: por misión (en la pizarra) o por agente (en el Inspector), incluso con el paso en marcha
  (se aplica en el siguiente turno o reintento).
- Automático: si un paso falla o el revisor pide cambios, el reintento sube un nivel.
- Coste visible: el Inspector dice cuántos tokens se fueron en pensar.
- ❓ Por verificar en la CLI real: cómo se activa en `claude -p` (variable de entorno o flag) y en Qwen3
  (`enable_thinking` en la plantilla de llama-server). Hoy el adaptador local ya distingue «pensando» de «escribiendo».

## 6. Subagentes en bucle
💡 Cada rol tiene una **cola**. Al terminar un paso, el agente coge el siguiente de su cola (de cualquier misión).
Se activa por misión o por rol cuando lo eliges, o lo pide el plan. Paradas: cola vacía, **límite de tiempo
del paso**, tope de la misión (tiempo, gasto, pasos), ventana de Claude (75 %), o tú (botón Parar en el puesto
o en la pizarra).

## 7. Cómo se ve
| Elemento | Representación |
|---|---|
| Oficina sin misiones | Puestos vacíos y tranquilos + panel de resumen: últimas tareas y resumen del periodo |
| Misión | Una **pizarra** en la pared por misión activa, con su color. Clic = se amplía: pasos, agente de cada uno, estado, lo que falta, coste y botones (aprobar, editar paso, rehacer paso, pausar) |
| Agente | Persona en un puesto con el color de su misión. Bocadillo con una frase de lo que hace ahora |
| Estado | Trabajando (anima), esperando cola (quieto), te necesita (mano levantada), error (rojo), hecho (check) |
| Pensamiento | 💡 Bocadillo = frase corta; Inspector (clic en el puesto) = pensamiento completo en vivo, tok/s, tokens, coste |
| Encargo al local | Línea animada entre el puesto de Claude y el del modelo local mientras dura |
| Bandeja | Lista a la izquierda + mano levantada en el puesto afectado |
| Recursos | Columna derecha: GPU, ventana de 5 h y 7 días, tok/s, worktrees |

## 8. Métricas del resumen
💡 Tareas y misiones terminadas, proyectos tocados, **horas de agente** (suma de lo que duró cada paso) y
**horas de reloj** (tiempo con al menos un agente trabajando), coste de Claude, tokens hechos en local (ahorro),
y pasos aprobados a la primera frente a los que necesitaron cambios. Periodo elegible: semana, mes.

## 9. Preguntas abiertas
Ver la conversación; se pasan aquí cuando se respondan.
