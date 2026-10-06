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
Paradas: cola vacía, tope de la misión (tiempo, gasto, pasos), ventana de Claude, o tú (botón Parar en el
puesto o en la pizarra). Al principio, en bucle continuo solo agentes locales.

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
