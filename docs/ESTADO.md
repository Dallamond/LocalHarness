# Estado y traspaso — leer primero al retomar (también desde Claude Code en la web)

Última actualización: 07/10/2026 (resumen de estado para el chat nuevo; sesión 4: GUI de oficina + Catálogo). Hoja de ruta: `docs/HOJA-DE-RUTA.md`.

## ▶ SESIÓN 07/10/2026 — Pestaña de Modelos locales (rama `claude/youthful-edison-bi67hm`, sale de `main`)
- **Tu equipo**: detecta GPU (nvidia-smi: VRAM total/libre), RAM, CPU e hilos (`localharness/hardware.py`). Si falla,
  «Corregir» guarda VRAM/RAM/GPU a mano (`llama.hardware`). Ancho de banda por modelo de GPU → tok/s estimados.
- **Ficha de cada GGUF descargado** (`gguf.py` lee la cabecera sin cargar el modelo; se guarda en `data/model-info.json`):
  arquitectura, capas, contexto máximo, MoE, si la plantilla admite herramientas o razona. **Nota 0-100 para
  LocalHarness** (`catalog.rate_local`): herramientas 35 + cabe con contexto de agente 25 + capacidad 25 + velocidad
  15, con los motivos y los roles para los que sirve. **🧪 Probar capacidades** (modelo arrancado, coste 0):
  ¿devuelve `tool_calls` de verdad?, ¿JSON con esquema?, tok/s → la prueba real manda sobre la plantilla.
- **Diálogo de arranque**: contexto, caché KV (f16/q8_0/q4_0), capas en GPU, expertos MoE en CPU (`--n-cpu-moe`),
  flash attention, conversaciones a la vez, muestreo (temp, top_p, top_k, min_p, repetición), pensamiento
  (`--reasoning-budget`), hilos, lotes, mlock/mmap y argumentos extra. Preajustes (Recomendado para tu PC, Agente,
  Rápido, Ahorro de VRAM, Lo guardado), **barra de VRAM en vivo** (pesos / KV / cálculo) y la orden exacta.
  Arrancar solo esta vez, arrancar y guardar, o solo guardar (`llama.per_model`, claves = `llama.OPTION_FLAGS`).
- **Recomendados para tu equipo**: catálogo editable `localharness/model_catalog.json` (Qwen3-Coder-30B-A3B,
  gpt-oss-20b, Qwen3 4B/8B/14B/30B-A3B, Devstral, Mistral Small 3.2, Gemma 3, Qwen2.5-Coder) con nota de agente;
  «Consultar Hugging Face» trae los tamaños reales, elige la mejor cuantización que cabe y sus ajustes. Buscador de
  cualquier repo GGUF y **descargas** reanudables con progreso (a «Carpeta de descargas»; token HF opcional).
- ⚠ No probado contra Hugging Face real (el contenedor no tenía acceso) ni con llama-server real: **pendiente de
  Lucas en el PC del instituto**. Las estimaciones de memoria/velocidad son aproximadas (±10-20 %); los tok/s se
  calibraron con lo medido en la 3060 (Qwen2.5-Coder 7B Q8 ~32 tok/s). Qwen3.5 no está en el catálogo (no sé su
  repo exacto): añadirlo copiando una entrada o buscarlo con el buscador.

## ▶ PUNTO DE PARTIDA PARA EL CHAT NUEVO (07/10/2026)

Rama con todo lo último: `claude/gifted-carson-20grn9` (NO está aún en `main`). Instalar en otro PC: `docs/INSTALAR.md`.
Objetivo del chat nuevo (Lucas): que Claude y el modelo local trabajen JUNTOS y repartirse bien las tareas.

### Funciona (probado)
- Núcleo: proyectos (repos git), agentes, tareas en worktree aislado, diff, aprobar / descartar / integrar en tu rama
  (merge local, nunca push), conflictos detectados antes de integrar, limpieza de worktrees viejos. CLI y API.
- Agentes Claude con tu suscripción (`claude -p` aislado, topes de turnos y $, uso de 5 h / 7 días): probado real.
- Chat: conversar con un agente, contestarle, seguir en la misma rama; skills por conversación.
- Modelos locales: lista tus GGUF, arrancar/parar llama-server desde la GUI con barra de carga, tok/s en vivo,
  configuración por modelo; agentes locales que RESPONDEN (con el repo metido en el prompt).
- Delegación Claude → local (`local_ask`, `local_write_file` por MCP): probado real con Haiku + Qwen2.5-Coder-7B
  (0,048 $): Claude delegó solo, Qwen explicó archivos y escribió un test.
- Jerarquía (planes): Director → subtareas → jefe técnico → N0/N1/N2 → bandeja. Probado real con Haiku. Funciona,
  pero hoy aporta poco (ver abajo).
- GUI nueva: Oficina 3D (los agentes entran cuando trabajan), Misión, Bandeja, Recursos, Inspector, Timeline /
  Terminal / Diff, Catálogo (asignar skills, MCP, internet, modelo local; importar). Probada en Chromium con CLI falsa.

### No funciona / limitaciones conocidas
1. **Los agentes locales no son agentes**: no leen ni escriben archivos, no ejecutan nada, no navegan. Solo
   contestan en un chat (`can_write=False`). Es el problema principal.
2. **Claude delega poco**: aun con la casilla, suele hacerlo él (la guía se endureció en la sesión 4, sin probar real).
   Y `local_write_file` solo escribe un archivo entero: no hay bucle «el local trabaja → Claude revisa → corrige».
3. Por lo anterior **Planes y Pendiente de ti no tienen sentido aún** (fuera del menú; rutas vivas).
4. Una tarea por repo a la vez; aprobaciones solo en las fronteras de la tarea (no acción a acción).
5. Codex aparcado (no instalado). Rama de integración por proyecto (M6) pendiente.

### Hecho pero SIN verificar con la CLI real (gasta plan: pedir permiso a Lucas)
- «Puede navegar por internet» (WebSearch/WebFetch) y servidores MCP del Catálogo asignados a un agente Claude.
- La guía de delegación más firme (¿delega más ahora?).

### Propuesta para empezar el chat nuevo (decidir con Lucas)
1. Bucle de agente propio para los locales: herramientas confinadas al worktree (leer, listar, buscar, escribir,
   ejecutar comandos de una lista blanca como los tests) con tool calling de llama-server (Qwen3.5-9B lo hace nativo;
   los Qwen2.5-Coder escriben el JSON como texto → parsearlo). Alternativa: adaptar una CLI de agente existente
   (OpenCode, Aider, Qwen Code…) apuntando a llama-server.
2. Claude como jefe: parte el trabajo, lo encarga a ese agente local (herramienta MCP «local_agent» con la tarea
   entera, no un archivo), revisa diff + tests y devuelve notas hasta que esté bien; topes de vueltas/tiempo.
3. Medir con el sandbox: misma tarea solo-Claude vs Claude+local (coste, tiempo, calidad).
4. Con eso, recuperar Planes/Bandeja como el bucle trabajador → jefe → tú.

## Sesión 4 (06/10/2026, tarde)

### Feedback de Lucas tras probarlo todo (06/10/2026, tarde)
- «Sigue siendo imposible que Claude use el modelo local para resolverlo en vez de contestar él.» Los modelos locales
  responden bien pero **no tienen capacidades agénticas**: no modifican archivos de las carpetas ni navegan por internet.
- **Planes** y **Pendiente de ti** no tienen sentido de momento (no hay bucle de agentes, ni local ni de Claude).
- Orden de Lucas: primero **todo el aspecto nuevo + los arreglos fáciles** (hecho, abajo); después, otra pasada a
  **cómo funciona y cómo se reparten las tareas**: «Claude debe poder funcionar junto al modelo local para que todo
  tenga sentido». Ese es el trabajo de la sesión siguiente (ver «Próximo: el reparto» abajo).

### Sesión 4 — hecho (85 pruebas en verde, GUI compilada y probada en Chromium con la CLI falsa)
- **Oficina** (`/oficina`, sustituye al Inicio; `/` e `/inicio` redirigen): `OfficeView.vue` + `office/office3d.ts`
  (three.js por npm, se carga aparte) + `office/OfficeDock.vue`. Sin gamificación (sin XP, logros, sonidos ni cámara cine).
  - Puestos solo para quien tiene que ver con el trabajo (feedback de Lucas): trabajando, esperando tu decisión, que
    trabajó en las últimas 2 h (`PRESENCE_MS`) o que llamas tú (abajo «Fuera de la oficina» o Catálogo → «En la
    oficina»). Entran creciendo y conservan su sitio; el director, al centro. El rack del modelo local solo está con
    llama-server encendido. Máx. 9 puestos; el tuyo al fondo con la baliza que parpadea si algo espera
    tu decisión, el rack del **modelo local** (LED = memoria de cada GPU, lámpara = llama-server listo/cargando) y dos
    pizarras: la misión y los worktrees. Accesorio del muñeco por rol (director antena, jefe casco verde, trabajador
    casco de obra, consultas gafas); color por rol. Paquetes volando: tú → agente al arrancar, agente → tú al terminar,
    agente → rack en cada encargo al modelo local. Clic en un puesto = inspector + cámara.
  - Izquierda: **Misión** (selector de tareas sueltas y planes, «Seguir la actual», «＋ Nueva» con proyecto + agente +
    petición → Ejecutar; pasos reales: encargo, trabajo, encargos al modelo local, revisar, integrar; para planes, las
    subtareas) y **Bandeja de aprobaciones** (= `/api/inbox` con los mismos botones que tenía el Inicio + «Ver»).
  - Derecha: **Recursos** (`GET /api/resources`: GPU por `nvidia-smi`, worktrees abiertos; modelo local, ventanas 5 h
    y 7 días de Claude, tok/s con gráfica, coste 7 días) e **Inspector** (modelo real, qué hace, rama, tareas y coste,
    skills, herramientas, «Asignar» en el catálogo, «Instrucción directa»: sigue su conversación abierta o crea tarea).
  - Abajo: **Timeline / Terminal / Diff** con los eventos reales de la misión y `/api/tasks/{id}/review`.
- **Catálogo** (botón en la barra superior, `CatalogOverlay.vue`): Agentes (asignar skills, `local`, internet y
  servidores MCP con casillas que guardan al momento; borrar; «En la oficina»), Skills (`/api/skills`; las importadas
  se borran) y Servidores MCP (`local` de serie + los importados). **Importar**: pegar/soltar JSON `mcpServers`,
  `SKILL.md` o agentes (.md con `model`/`role`, o JSON con `agents`).
- Backend del catálogo:
  - Ajuste `mcp_servers` (se guarda entero, validado: stdio `command/args/env` o remoto `url`; «local» reservado;
    «Restablecer» no lo borra). Agente Claude con `config.mcps` → `orchestrator._mcp_setup` escribe un `--mcp-config`
    con esos servidores (+ `local` si delega) y los aprueba con la regla de servidor `mcp__<nombre>`.
  - `config.web` («Puede navegar por internet» en Ajustes y Catálogo) → añade `WebSearch` y `WebFetch` a `--tools`.
    ⚠ Sin verificar con la CLI real (gasta plan): que `WebSearch` funcione con la suscripción en `-p`.
  - Skills importadas en `data/skills/<nombre>/SKILL.md` (fuera de git): `POST /api/skills`, `DELETE /api/skills/{n}`
    (solo importadas; las de serie no se pisan).
- Estética nueva en todas las páginas: paleta del prototipo (piedra cálida, índigo), Plus Jakarta Sans, Font Awesome
  (npm), barra superior en vez de lateral, claro/oscuro. Menú: Oficina · Chat · Modelos locales · Ajustes.
  **Planes y Pendiente de ti fuera del menú** (las rutas siguen para los enlaces de planes del chat).
- Arreglos fáciles: `pip install -e .` fallaba (varios paquetes en la raíz: ahora `packages.find` solo `localharness*`);
  abrir `/chat/<id>` directamente (o desde la bandeja) rompía la página (`review` usada antes de declararse); guía de
  delegación más firme («OBLIGATORIA cuando encaje», empezar siempre por un encargo al modelo local salvo cambios de
  1–2 líneas, no leer archivos tú para entenderlos).

### Próximo: el reparto Claude ↔ modelo local (decidir con Lucas antes de tocar)
El problema de fondo: un agente local solo «piensa en un chat» y Claude, aunque tenga `local_ask`/`local_write_file`,
tiende a hacerlo todo él. Ideas a llevar a la conversación (de la tarea 8 de abajo):
1. **Bucle de agente propio para los locales** con *tool calling* de llama-server (solo Qwen3.5-9B devolvió
   `tool_calls` nativos; para los Qwen2.5-Coder, parsear el JSON del texto): leer/listar/buscar/escribir en su
   worktree y ejecutar comandos de una lista blanca (tests). O reutilizar una CLI de agente con endpoint OpenAI local.
2. **Claude como jefe, no como trabajador**: que Claude parta el trabajo y lo encargue a ese agente local autónomo
   (no a `local_write_file` de un solo archivo), revise el diff y los tests, y devuelva notas hasta que esté bien.
3. Con eso, Planes y la bandeja vuelven a tener sentido (el bucle trabajador → jefe técnico → tú).

## Sesión anterior (06/10/2026, mediodía)

### Decisiones de Lucas de hoy
- **GUI final = su prototipo** `docs/prototipos/localharness-gui-prototipo-v2_1.html` (ábrelo en el navegador): oficina
  low-poly en three.js con un puesto por agente, cabecera con misión y Ejecutar, izquierda **Misión** + **Bandeja de
  aprobaciones**, derecha **Recursos** (GPU, ventana de 5 h de Claude, tok/s, worktrees) + **Inspector** del agente,
  abajo **Timeline / Terminal / Diff**, y **Catálogo** (Agentes · Skills · Servidores MCP, con importar JSON
  `mcpServers`, `SKILL.md` y agentes). v2 es la versión anterior.
- La oficina **sustituye al Inicio**; Chat, Planes, Modelos y Ajustes siguen como páginas.
- **Nada de gamificación** (fuera XP, niveles, logros, sonidos y cámara cine del prototipo).
- Ir **agente a agente**: crear uno, comprobar que todo funciona de punta a punta y pasar al siguiente.
  Primero **Atlas** (Claude Director que delega en Qwen); luego Sentinel (jefe técnico), Forge (programador), Scout.
- Lucas autorizó UNA ejecución real de verificación (hecha, ver abajo). Para más, preguntar.

### Flujo de trabajo que quiere Lucas (visión)
«Lo lógico es que se adapte a cada proyecto: lo analice, cree agentes específicos, sepa qué modelos locales elegir y
qué skills usar y qué hace falta, y lo divida todo en tareas que yo pueda ir comprobando bien.»
Propuesta: la primera tarea de Atlas es **Analizar proyecto** → devuelve una propuesta estructurada (`--json-schema`):
agentes a crear (rol, Claude o local, qué GGUF de los suyos según tamaño/VRAM de la 3060 de 12 GB, skills y MCP de
cada uno), qué falta (herramientas, tests, dependencias) y el trabajo partido en tareas pequeñas verificables. Lucas
aprueba/quita cada pieza en la GUI y entonces se crean agentes y tareas (encaja con planes, catálogo y bandeja).
La lectura gruesa del repo, delegada en Qwen para no gastar plan.

### Prueba real de hoy (Haiku, 0,035 $, sandbox temporal, Qwen2.5-Coder-7B arrancado con clave)
- Subagentes: con `--tools ...,Agent` el evento `init` lista **`Task`** → la CLI 2.1.287 acepta `Agent` como alias y
  la herramienta existe. ✅ (punto 10 resuelto)
- **Delegación: ✅ ARREGLADA (06/10/2026, tarde).** Causa verificada leyendo el evento `init` (cortando el proceso antes de
  llamar al modelo, coste 0): `--safe-mode` desactiva también los servidores de `--mcp-config`. Ahora, SOLO cuando hay
  delegación, el adaptador usa `--setting-sources "" --disable-slash-commands --strict-mcp-config` y el entorno
  `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` (verificado: sin ella Claude leía el CLAUDE.md del vault y contestaba en español).
  Contexto medido: ~11,6k tokens (4,6k con `--safe-mode`; los 245k de antes eran MCP/plugins del usuario). Sin
  delegación se mantiene `--safe-mode`. Las herramientas MCP basta con ponerlas en `--allowedTools`.
- **Prueba real tras el arreglo (Haiku, 0,048 $):** Claude delegó SOLO, sin pedírselo en la petición: `local_ask` para
  explicar los 3 .py (Qwen los leyó), `local_write_file` para `tests/test_resta.py` (lo escribió Qwen) y un `Read` para
  revisarlo. Ojo: en una tarea TAN pequeña cuesta más que sin delegar (0,035 $), porque el contexto base pasa de 4,6k
  a 11,6k tokens. El ahorro llega con archivos grandes y mucho código generado. Idea pendiente: medirlo con una tarea
  mediana y, si compensa, recortar contexto (p. ej. `--disallowedTools Task` si no hacen falta subagentes).

### Orden de trabajo propuesto
1. ~~Arreglar la carga del MCP~~ hecho. Medir el ahorro real con una tarea mediana (pedir permiso).
2. Esqueleto de la oficina en Vue (three.js por npm) con agentes REALES como puestos y datos reales en paneles
   (bandeja = `/api/inbox`, timeline/terminal = eventos, diff = `/api/tasks/{id}/review`, recursos = `/api/llama`,
   `/api/health` límite 5 h/7 d y tok/s, worktrees = `/api/maintenance`, inspector = agente + respuesta).
3. Catálogo real: agentes (CRUD existente), skills (`/api/skills` + importar SKILL.md a `skills/`), registro de
   servidores MCP en ajustes asignables por agente (el `local` de Qwen de serie) → `--mcp-config` por agente.
4. Atlas «Analizar proyecto» (propuesta → aprobar → crear agentes y tareas). Después Sentinel, Forge (tarea 8), Scout.

### Para trabajar desde otro PC (clase)
```
git clone https://github.com/Dallamond/LocalHarness.git && cd LocalHarness
python -m venv .venv && .venv/Scripts/python -m pip install -e .[server]     # Linux: .venv/bin/python
.venv/Scripts/python -m unittest discover -s tests -t .                       # 79 pruebas, NUNCA llaman a Claude real
cd web && npm install && npm run build && cd .. && .venv/Scripts/python -m localharness serve   # :8095
```
Sin GPU ni llama-server, los agentes locales no responden (todo lo demás sí). Sin `claude` logueado, no lanzar
tareas reales de Claude: las pruebas usan la CLI falsa `tests/fakes/claude`. La base de datos (`data/`) no se sube:
el estado está en este documento.

## Dónde estamos
| Hito | Estado |
|---|---|
| M0 Claude | ✅ verificado con la CLI real (`tests/fixtures_reales/`) |
| M0 Codex | ⏸ aparcado por decisión de Lucas (no instalado) |
| M1 CLI | ✅ |
| M2 API + GUI | ✅ probado con CLI falsa (también en navegador) |
| M3 Jerarquía | ✅ Director + jefe técnico + N0/N1/N2 + bandeja; CLI y API. Probado real con Haiku (0,087 $) |
| M4 Modelos locales | 🔄 proveedor `local` probado real (Qwen2.5-Coder 7B, Qwen3.5 4B/9B, Coder 14B); progreso, tok/s, config por modelo |
| GUI de M3 | ✅ Pendiente de ti, Planes, detalle de plan; probada en navegador con agentes locales |
| M5 Skills y memoria | ✅ núcleo, CLI, pruebas y GUI (skills por conversación, skills del Director en el plan) |
| M6 Flujo Git | 🔄 conflictos de merge seguros + limpieza de huérfanos. Falta rama de integración por proyecto |
| Pruebas de Lucas | ⏳ con `sandbox` + `docs/PROBAR.md`; esperar su feedback |

## Decisiones de Lucas (05/10/2026)
- **Gastar lo mínimo del plan Pro de Claude** (iba por el 82 % semanal). Probar con CLIs falsas; ejecuciones reales
  solo con Sonnet y topes (`--max-turns`, `--max-budget-usd`). Tiene ~100 € de créditos de Claude en la nube para
  cuando se agote el límite (pendiente aclarar si son créditos de API o uso extra).
- **Estética:** la «blueprint» se sustituyó (05/10/2026) por un estilo cálido y redondeado (Figtree, tema claro/oscuro,
  barra lateral) porque Lucas no quería un aspecto «cuadrado e IA». Sigue siendo provisional: el destino es una
  pequeña oficina simulada (low-poly o 2D, por decidir).
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

## M5 — skills y memoria (context.py)
- Skills = carpetas con `SKILL.md` (frontmatter `name`/`description`). Catálogo: `skills/` del repo (tests-primero,
  cambios-minimos, revision-de-diff) + `LOCALHARNESS_SKILL_DIRS` (p. ej. `D:\Lukaton1\.claude\skills\superpowers\skills`).
- Se inyectan como texto antes de la tarea: skills del agente (`config.skills`, `agent add --skill`), de la tarea
  (`run --skill`, columna `tasks.skills`) y las que elige el Director por subtarea (campo `skills` del plan; nombres
  inventados se descartan). Memoria = `.md` de `projects.memory_dir` (`project memory <nombre> [ruta]`, por defecto
  `data/memory/<proyecto>`), fuera del worktree → solo lectura. Evento `context` registra qué se inyectó.

## GUI (05/10/2026, sesión 2)
- **Inicio** (`/inicio`, `HomeView.vue`): cifras rápidas, «Te toca a ti», el equipo (cada agente: libre o qué hace
  ahora, a partir de su último evento `text`/`tool`), «Lo último que ha pasado» (archivos tocados y veredicto del jefe
  técnico) y planes. Datos: `GET /api/activity` (`current` = último evento de cada tarea en marcha, `recent` = últimas
  terminadas con `files` del numstat) + SSE.
- **Ajustes** (`/ajustes?s=…`, `SettingsView.vue`): agentes (crear, editar modelo/rol/límites/skills/URL local, borrar
  si no tienen historial), proyectos (alta y carpeta de memoria), aprobaciones (límites y patrones de policy), ejecución
  (timeout por tarea, URL del llama-server por defecto), skills y memoria (límites de caracteres, carpetas extra,
  catálogo), valores de agentes nuevos y apariencia (tema/densidad/tamaño, solo en el navegador).
- Ajustes del servidor: `settings.py` + tabla `settings` (migración 3). `GET/PUT /api/settings`, `POST /api/settings/reset`,
  `GET /api/skills`, `PATCH/DELETE /api/agents/{id}`, `PATCH /api/projects/{id}`. La CLI también los aplica.

## Entorno de pruebas
`python -m localharness sandbox [--reset]` crea `~/LocalHarness-sandbox` (tienda con fallos a propósito) y los agentes
qwen-director, qwen-jefe (local), haiku-director, haiku-jefe, sonnet-trabajador (Claude con topes). Guía: `docs/PROBAR.md`.

## Pruebas reales hechas (05/10/2026)
- M3 con Claude Haiku (Director, 2 trabajadores, jefe): plan correcto, ambas subtareas aprobadas por el jefe, 0,087 $.
  Destapó un fallo ya corregido: la salida de git se leía en cp1252 y el revisor veía tildes rotas.
- M4 con Qwen2.5-Coder 7B Q8 en la 3060 (`llama serve qwen2.5-coder-7b`; tarda ~4 min en cargar del disco):
  consulta de solo lectura correcta en 28 s; plan con Director y jefe locales en 14 s; el jefe local detectó que
  el trabajador (falso) no hizo lo pedido y escaló a N2. Todo coste 0.

## Sesión 3 (06/10/2026) — QUÉ SE HIZO Y QUÉ QUEDA (EMPEZAR POR AQUÍ)
Lucas pidió seguir implementando mientras él investiga con NotebookLM cómo crear agentes (tarea 8). Hecho, con
pruebas (71 en verde) y GUI compilada; nada probado aún por Lucas en el navegador (lista en `docs/PROBAR.md` §4).

**Hecho**
1. **Subagentes en Claude** — `config.subagents` (casilla «Puede crear subagentes» en Ajustes → Agentes, solo
   claude) añade `Agent` a `--tools`/`--allowedTools` vía `RunSpec.extra_tools`. Desactivado por defecto.
   ⚠ SIN VERIFICAR con la CLI real que la herramienta se llama `Agent` (antes `Task`): pedir permiso a Lucas para
   una ejecución con Haiku y topes (`claude -p --tools Agent,Read ...` y mirar `tools` del evento `init`).
2. **Barra de progreso al cargar un modelo** — `LlamaManager.status()` → `progress {pct, stage, source, eta_s}`.
   Hallazgo: el llama-server b11379 (verbosidad 3) YA NO imprime los puntos de progreso. Fuentes, por orden: puntos
   tras `load_tensors` (versiones antiguas), lo que tardó ese GGUF la última vez (`data/llama-load-times.json`; se
   guarda la carga MÁS LENTA, la de en frío) o barra indeterminada con la etapa (leyendo del disco / contexto…).
3. **1–2 líneas del log** siempre visibles en la tarjeta de estado (`log_lines`, sin las de solo puntos).
4. **Tokens por segundo** — evento `speed` cada 1,5 s (`SPEED_EVERY_S`) con tps, tokens y fase pensando/escribiendo;
   NO se guarda en la BD (`orchestrator.EPHEMERAL`). Se ve en la burbuja «escribiendo…» del chat, en la tarjeta del
   agente del Inicio y la última velocidad en Modelos locales (`runner.last_speed`, también en `/api/health`).
   Real: Qwen3.5-4B ~73 tok/s en la 3060.
   Hallazgo: un modelo que razona puede gastar TODOS los tokens pensando y devolver respuesta vacía (pasó con
   Qwen3.5-4B y 400 tokens; es lo de DeepSeek). Ahora eso es `failed` con un mensaje claro (subir «Tokens de respuesta»).
5. **Configuración por modelo** — `llama.per_model[ruta] = {ctx, ngl, extra}` («⚙ Arranque de este modelo» en cada
   tarjeta; `settings.llama_launch`). En Ajustes → Agentes locales: temperatura, tokens de respuesta, contexto del repo.
6. **Decidir desde el Inicio** — botones en «Te toca a ti»: tarea por revisar → Aprobar e integrar / Descartar
   (aprobada → Integrar); plan → Aprobar / Rechazar; integrar plan → Integrar / Rechazar; subtarea N2 → Aprobar y
   seguir / Rechazar; y «Ver diff». Las subtareas `pending` de planes que acaban mal pasan a `cancelled`
   (`hierarchy.close_pending`, y al arrancar en `store.mark_interrupted`).
9. **Modelo real en agentes locales** — el evento `session` lleva el modelo ARRANCADO (de `/v1/models`, sin ruta ni
   `.gguf`) y `requested`; aviso si el agente pide otro; ya no se manda `model` al servidor. «+ Crear agente local»
   crea agentes por rol sin modelo (`local-jefe`, `local-director`, `local-consultas`). Chat, Inicio y Modelos
   muestran «usa: <modelo arrancado>»; los agentes antiguos con otro modelo avisan y ofrecen «Arrancar <ese>».

**Además (de «Pendiente después»)**
- M5 GUI: skills por conversación al abrir un chat (`POST /api/tasks` acepta `skills`; `task_out` las decodifica) y
  las skills elegidas por el Director visibles en cada subtarea del plan.
- M6: `Workspace.merge` detecta conflictos ANTES con `git merge-tree --write-tree` (git ≥ 2.38; aquí 2.52) y, si aun
  así falla, aborta y vuelve a tu rama: nunca deja el repo a medio merge (`MergeConflict` con los archivos).
  Limpieza (`maintenance.py`): al arrancar el servidor y con `python -m localharness cleanup [--dry-run]` borra
  worktrees/ramas de tareas integradas/rechazadas/descartadas/`done` y planes integrados/rechazados/`done`; conserva
  fallidas/canceladas/aprobadas e informa de las ramas desconocidas (nunca las borra). Ajustes → Ejecución →
  Mantenimiento. En los datos de Lucas (simulación): borraría task-1, 2, 4 y 5 (`done`), conserva task-3 (aprobada).
- llama-server lanzado desde la GUI con `--api-key` aleatoria por arranque (`llama.API_KEY`): cierra el CORS abierto
  (cualquier web podía usar la GPU por 127.0.0.1). Real: sin clave 401, con clave responde, la clave no sale en el log.
  Uno lanzado a mano (`llama serve`) sigue sin clave.
- Pruebas sin ruido de asyncio (`tests/__init__.py`).

**Prueba real de modelos locales como jefe técnico + sonda de herramientas (06/10/2026, coste 0, 3060)**
Mismo diff con un fallo claro (quita `* cantidad` y cambia `/100`) y otro correcto; y una petición con `tools`.
| Modelo | Carga | Diff con fallo | Diff correcto | tok/s | `tool_calls` nativos |
|---|---|---|---|---|---|
| Qwen2.5-Coder 7B Q8 | 64 s | request_changes (motivo vago) · 6 s | approve · 2 s | ~32 | ❌ escribe el JSON como texto |
| Qwen3.5 9B Q4 | 157 s | request_changes, cita los dos fallos · 43 s | approve · 29 s | ~43 | ✅ `read_file {"path":"README.md"}` |
| Qwen2.5-Coder 14B Q4 | 71 s | request_changes, cita el fallo · 6 s | approve · 3 s | ~25 | ❌ escribe el JSON como texto |
Conclusiones: los tres aciertan el veredicto; Qwen3.5-9B razona mejor pero es ~7× más lento (piensa). Para la
tarea 8 (agentes locales autónomos): con el llama-server actual y `--jinja`, **solo Qwen3.5-9B devuelve `tool_calls`
de verdad**; los Qwen2.5-Coder responden la llamada como texto JSON (se podría parsear como alternativa).
Script: rehacer con `LlamaManager` + `reviewer_prompt` + `REVIEW_SCHEMA` y `tools` en /v1/chat/completions.

**Claude delega en el modelo local (06/10/2026, tras el feedback «no se comunican, todo es un chat»)**
- `localharness/mcp_local.py`: servidor MCP stdio propio (JSON-RPC a mano, sin dependencias) con `local_ask`
  (el servidor lee los archivos del worktree y Qwen responde: Claude no gasta tokens leyéndolos) y `local_write_file`
  (Qwen escribe el archivo entero; confinado al worktree, nunca `.git`). Solo lectura → solo `local_ask`.
- Agente Claude con `config.delegate_local` («Puede delegar en el modelo local» en Ajustes): el orquestador crea
  un `mcp.json` temporal (lleva la clave de llama-server; se borra al acabar), pasa `--mcp-config` (con
  `--strict-mcp-config` solo carga ese), auto-aprueba `mcp__local__*`, sube `MCP_TOOL_TIMEOUT` y añade al prompt la
  guía de cuándo delegar. El servidor se lanza POR RUTA (desde el worktree `-m localharness...` no se encuentra).
- Eventos `delegate` (en vivo, leyendo `encargos.jsonl`) y `delegate_summary` (tokens hechos en local) → tarjetas
  verdes «🦙 Modelo local» en el chat; el Inicio dice «Encargando al modelo local: …».
- Real con Qwen2.5-Coder-7B (coste 0): `local_ask` encontró los dos fallos de calc.py en 2,7 s; `local_write_file`
  escribió test_calc.py correcto en 3 s. La CLI falsa lanza el servidor MCP de verdad en `tests/test_delegate.py`.
- ⚠ SIN VERIFICAR con la CLI real: que `--safe-mode` no bloquee los servidores de `--mcp-config` y que Claude use las
  herramientas por iniciativa propia. Si `--safe-mode` los bloquea: quitarlo solo cuando hay delegación y aislar con
  `--setting-sources ""` + `--strict-mcp-config`. Una ejecución con Haiku verifica esto y el nombre `Agent` a la vez.

**Queda (necesita a Lucas)**
7. **Repasar roles y skills** («creo que se puede optimizar mucho; tendremos que ver cómo lo acabamos
   configurando»). Decidir con Lucas antes de tocar: qué roles existen (Director, jefe técnico, trabajador,
   consultas…), qué skills lleva cada uno por defecto, si el rol fija herramientas y límites (p. ej. jefe = solo
   lectura) y cómo se crean desde Modelos locales (hoy: nombre del modelo + rol, descripción automática).

8. **INVESTIGAR: modelos locales como agentes autónomos.** Hoy un agente local solo «piensa en un chat»: recibe el
   repo en el prompt, no lee ni escribe archivos ni ejecuta nada (`can_write=False`). Lucas quiere que trabajen solos
   en su propio entorno (worktree + terminal/pruebas) hasta que el jefe técnico vea la tarea completa y los pare.
   Líneas a investigar (comprobar antes de decidir; nada verificado aún):
   - **Bucle de agente propio en LocalHarness** usando *tool calling* de llama-server (API compatible con OpenAI;
     con `--jinja` los modelos con plantilla de herramientas, p. ej. Qwen2.5-Coder/Qwen3, devuelven `tool_calls`).
     Herramientas mínimas confinadas al worktree: leer, listar/buscar, editar/escribir, ejecutar un comando con
     lista blanca y tiempo límite (tests, linters). Medir qué tal lo hacen de verdad los modelos de 7–14B.
   - **Reutilizar una CLI de agente que acepte un endpoint OpenAI local** en vez de escribir el bucle: candidatas a
     evaluar Codex CLI (proveedor local / `--oss`), OpenCode, Aider, Qwen Code, Goose, OpenHands. Sería otro
     adaptador como `claude.py` (JSONL → eventos). Criterios: Windows, salida en streaming parseable, límites de
     turnos, que funcione con la 3060 (12 GB).
   - **Entorno de pruebas aislado**: el worktree ya aísla los archivos; falta aislar los comandos (lista blanca,
     sin red, quizá contenedor o la sandbox de la propia CLI). Nunca push.
   - **Quién decide que ha terminado**: bucle trabajador → jefe técnico revisa el diff y los tests → «sigue con
     esto» (vuelve al trabajador con las notas) o «completado» (para). Topes duros: iteraciones, tiempo, tokens.
     Encaja con `POST /api/tasks/{id}/reply` (la respuesta del jefe sería el siguiente mensaje) y con los niveles
     N0/N1/N2 actuales.
   - Resultado esperado: un documento corto con la opción recomendada, una prueba real con Qwen en el sandbox
     (`python -m localharness sandbox`) y el coste/tiempo medido.

10. ~~Verificar `Agent`~~ hecho: la CLI lo acepta y lo lista como `Task`.

## Sesión 2 — feedback de Lucas y lo que se hizo
Feedback tras probar la GUI: «la respuesta final se pone en un md que no puedo contestar». Pide:
1. **Chat para mandar tareas** (como un chat): vincular la carpeta desde ahí, ver/describir los agentes y
   **responder a las preguntas** del agente (sobre todo Claude). Mañana lo prueba con agentes locales.
2. **Menú gráfico de modelos locales**: elegir la carpeta de modelos, detección automática de los GGUF y un botón
   «Arrancar» por modelo que lance llama-server por detrás y deje los agentes conectados a él.

**Backend HECHO (con pruebas, 51 en verde):**
- Conversación en tareas sueltas: `POST /api/tasks/{id}/reply {message}`. Sigue en el mismo worktree/rama, el diff
  cuenta desde la base original y el coste se acumula. Claude reanuda su sesión (`--resume session_id`); el
  proveedor local recibe toda la conversación en el prompt (`orchestrator._conversation` + `transcript`). Tu
  mensaje queda como evento `user`; cada respuesta del agente es un evento `result` (y `text` por párrafo).
  Si el worktree ya no existe (tarea `done` limpiada) se crea otro. Cerrada si merged/rejected/discarded (409).
- Vincular carpeta: `POST /api/projects` acepta `init_git: true` (git init + commit inicial, solo si se pide)
  y quita comillas de la ruta pegada.
- Agentes con `description` (en `config`, alta y PATCH): el Director la lee para repartir subtareas.
- Modelos locales: ajustes `llama` {server, model_dirs, port, ctx, ngl} (vacíos = env/Arena). `GET /api/llama`
  (exe, carpetas, modelos con tamaño y cuantización, estado off/loading/ready/failed/external + cola del log),
  `POST /api/llama/start {path, ctx?, ngl?}` (un servidor a la vez, sin ventana; fija `local_base_url` a su
  puerto), `POST /api/llama/stop`. Muere con el servidor. `llama.LlamaManager`, log en `data/llama-server.log`.
- `POST /api/pick {kind: folder|file}`: abre el selector NATIVO de Windows (tkinter) en el PC y devuelve la ruta;
  501 si no hay escritorio (en la web/Linux): entonces la GUI debe dejar escribir la ruta.

**GUI HECHA (compila; falta que Lucas la pruebe en el navegador):**
- **Chat** (`ChatView.vue`, `/chat` y `/chat/:id`; `/tareas` redirige aquí, `/tareas/:id` queda para el diff):
  conversaciones a la izquierda; burbujas con markdown (`Markdown.vue`: marked + DOMPurify); herramientas
  plegadas en una línea gris; notas de estado; «escribiendo…» mientras trabaja; tarjeta de cambios con
  Aprobar/Integrar/Rechazar. Conversación nueva: modo «Un agente» (tarjetas de agentes con su descripción) o
  «Equipo (Director)» (lanza un plan), «Vincular carpeta» con «Elegir…» (selector nativo) y «inicializar git».
  Enter envía, Mayús+Enter salto de línea; botón Parar mientras trabaja.
- **Modelos locales** (`ModelsView.vue`, `/modelos`): estado del llama-server (punto de color, tiempo, log,
  Parar), tarjetas por GGUF agrupadas por carpeta (tamaño, cuantización, Arrancar/«Cambiar a este»), crear agente
  local con rol (jefe/director/consultas) y descripción automática, carpetas y exe con «Elegir…», puerto, contexto y
  capas en GPU. Sondea cada 2 s mientras carga.
- Ajustes → Agentes: campo Descripción (alta y edición) y se muestra en la lista.
- Ojo: un agente local usa el modelo que esté ARRANCADO (llama-server sirve uno); su `model` es solo el nombre.

**Lista de prueba para Lucas:**
1. Modelos locales → Elegir carpeta… (se abre la ventana de Windows) → aparecen tus GGUF → Arrancar Qwen →
   pasa de «cargando» a «listo» → «+ Crear agente» con rol jefe.
2. Chat → Nueva conversación → Vincular carpeta (Elegir…) → elige el agente local → escribe una pregunta → la
   respuesta sale en burbuja con formato → contesta algo y debe responder teniendo en cuenta lo anterior.
3. Igual con un agente Claude (Sonnet con topes) que pida algo ambiguo: te pregunta, contestas, sigue en la misma
   rama; al terminar sale la tarjeta de cambios.

## Pendiente (después de lo anterior)
1. Recoger el feedback de Lucas de `docs/PROBAR.md` y arreglar lo que salga.
2. M6 (resto): rama de integración por proyecto; tras un conflicto, botón «rehacer sobre la rama actual» (rebase de
   la rama de la tarea o pedírselo al agente).
3. M4: comparar revisor local vs Claude con el mismo diff (gasta plan: pedir permiso).
4. Estética: la oficina simulada cuando Lucas decida el estilo (de momento, el estilo cálido de la sesión 2).

## Hallazgos técnicos clave (no repetir)
- La CLI hija va aislada: `--safe-mode --strict-mcp-config` (sin eso, 245k tokens por «ok»). `--bare` prohíbe OAuth.
- `--tools` es el límite duro de herramientas. Prompt por stdin. En Windows se lanza el `.exe` real del shim npm.
- `rate_limit_event` → evento `limit` con uso de 5 h / 7 días.
- La CLI tiene `--json-schema` para salida estructurada (útil para Director/jefe técnico).
