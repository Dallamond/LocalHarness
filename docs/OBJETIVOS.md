# LocalHarness — objetivos (rumbo nuevo, 06/10/2026)

Idea central de Lucas: en vez de crear agentes a mano al entrar en un proyecto, **Claude actúa con un manual
(su «algoritmo») y un catálogo** de roles, modelos, skills y servidores MCP, y con eso decide qué equipo hace
falta y lo invoca. Se empieza con **pocas skills y pocos roles**; cuando funcione, se hacen más y más complejos.

## Objetivos (en orden)

| # | Objetivo | Estado |
|---|---|---|
| 1 | **Manual del Director**: el ciclo que sigue Claude (clasificar → entender el proyecto → elegir equipo → planificar con criterio de aceptación → ejecutar/revisar → cerrar) en un archivo editable, `manual/director.md` | ✅ v1 (se inyecta en el prompt del Director) |
| 2 | **Búsqueda web para el modelo local**: `local_research` en el MCP local (DuckDuckGo HTML, sin clave: lo más sencillo para ver si funciona). Qwen busca, lee páginas y devuelve respuesta con fuentes | ✅ hecho con pruebas falsas; falta probarlo de verdad en el PC de Lucas |
| 3 | **Plan editable en el Inicio**: un subagente (Director) piensa el plan; aparece en el menú inicial con sus pasos y Lucas puede **aprobarlo entero**, **editar un paso a mano** o **pedir que se rehaga una parte** (con su comentario) | ⏳ |
| 4 | **Ver a los subagentes trabajando**: en qué tarea está cada uno, su pensamiento (texto/razonamiento en vivo), tok/s, tokens y coste | ⏳ (hay piezas: tok/s en chat, actividad en Inicio) |
| 5 | **Catálogo de roles** (empezar con 3: Explorador local, Programador, Revisor): el plan dice `role` y LocalHarness crea el agente para la tarea; los agentes manuales siguen valiendo | ⏳ |
| 6 | **Catálogo de skills con metadatos** (roles a los que aplican, cuándo usarlas) y de **servidores MCP** asignables por rol | ⏳ |
| 7 | **Subagentes en bucle, siempre trabajando**: cola de tareas por agente; cuando uno acaba, coge la siguiente del plan o de la cola, con topes duros (turnos, tiempo, gasto, ventana de 5 h) y parada por el jefe técnico o por Lucas | ⏳ |
| 8 | **Modelos locales con herramientas** (bucle de agente propio con tool calling, confinado al worktree; hoy solo Qwen3.5-9B devuelve `tool_calls`) que use las mismas herramientas MCP que Claude | 🔄 v1 hecha: proveedor `local_agent` (bucle propio: leer, listar, buscar, escribir, buscar_web, leer_url, avisar_progreso, terminar; modo `json` de reserva). Falta: `ejecutar` con lista blanca, `preguntar_director`, probarlo con Qwen real |
| 9 | **Atlas «Analizar proyecto»**: perfil del repo + propuesta de equipo y tareas que Lucas aprueba pieza a pieza | ⏳ |
| 10 | **Oficina 3D** del prototipo `docs/prototipos/localharness-gui-prototipo-v2_1.html` mostrando el equipo y los objetivos 3 y 4. Va DESPUÉS del modelo nuevo de organización (manual + catálogo + roles) | ⏳ |
| 10a | **Antes de programar la oficina: sesión de diseño con Lucas** — todas las funciones, cómo funciona todo y cómo se representa cada cosa de forma gráfica, sencilla y entendible. Resultado: `docs/DISENO-OFICINA.md` aprobado por Lucas | 🔄 empezada |

## Notas de diseño
- **Búsqueda**: si DuckDuckGo HTML falla mucho (bloqueos, cambios de HTML), alternativas: SearXNG en local con
  Docker (sin clave) o una API con cuota gratuita (Brave, Tavily; comprobar condiciones). `LH_WEB=0` la apaga.
- **Bucle de subagentes (7)**: el riesgo es gastar el plan de Claude sin darse cuenta. Por eso, en bucle continuo
  solo agentes locales al principio; Claude, con tope por ventana de 5 h y parada automática a partir del 75 %.
- **Plan editable (3)**: el plan ya se guarda como JSON (`plans.plan`) y hay estado `awaiting_you`. Falta:
  editar subtareas antes de aprobar (API `PUT /api/plans/{id}` con validación `validate_plan`) y «rehacer este
  paso» (relanzar al Director con el plan actual + el comentario, solo sobre ese paso).
- **Ver el pensamiento (4)**: Claude emite `text` y, si lo hay, `thinking` en su JSONL; llama-server devuelve
  `reasoning_content`. Mostrarlo en vivo por SSE igual que el tok/s (evento efímero, sin guardar todo).
