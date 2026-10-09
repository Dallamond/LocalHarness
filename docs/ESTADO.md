# Estado y traspaso — leer primero al retomar (también desde Claude Code en la web)

Última actualización: 09/10/2026, noche (banco de pruebas: resultados y qué sigue; oficina y GUI nuevas). Hoja de ruta: `docs/HOJA-DE-RUTA.md`.


## ▶ 09/10/2026 noche — Banco de pruebas: el cuello de botella es el JEFE LOCAL, no los modelos
**Dónde lo dejamos (23:00).** El banco (`banco/`, página `http://127.0.0.1:8095/banco`, resultados en `data/banco/`)
está corriendo `qwen9b-qwen4b` en Cuentas claras guiada (empezó 22:46; Qwen3.5-9B en la 3060 + Qwen3.5-4B en la 1060).
Al retomar: abrir `/banco` o pedir «analiza el banco» y compararlo parche a parche.

**Resultados — Cuentas claras, modalidad guiada (18 parches, examen oculto de 29 tests):**

| Contendiente | Quién dirige | Obreros | Integrados | Nota final | Tiempo | Coste |
|---|---|---|---|---|---|---|
| `claude-dirige` | Claude Sonnet, modo coordinador (NO escribe código) | gpt-oss-20b + Qwen3.5-4B | **18/18** | **96,6 %** | 39 min | 2,87 $ nominales (plan) |
| `gptoss-qwen4b` | Jefe local (`boss.py`) | gpt-oss-20b + Qwen3.5-4B | 5/18 | 20,7 % | 129 min | 0 $ |
| `gptoss-solo` | Jefe local | gpt-oss-20b (+ el 4B se coló, ver abajo) | 2/11, parada | 17,2 % | 86 min | 0 $ |
| `qwen9b-qwen4b` | Jefe local | Qwen3.5-9B + Qwen3.5-4B | en marcha | — | — | 0 $ |

Curva de Claude: 20,7 → 31 → 37,9 → 44,8 → 55,2 → 62,1 → 69 → 79,3 → 82,8 → 89,7 (p10) → 96,6 (p12, ya no sube), 0
reintentos. Curva del jefe local: 0 en los parches 1–4, 13,8 en el 5, 20,7 desde el 10.
**Conclusión:** con los MISMOS modelos obreros, cambiar solo quién dirige pasa de 20,7 % a 96,6 %. Hay que mejorar el
orquestador local antes que cambiar de modelos.

**Qué hace mal el jefe local (de `data/banco/cuentas-claras-guiada/gptoss-qwen4b-*/resultado.json`):**
1. **Cascada:** los parches 1–4 (dinero, fechas, movimientos, filtros, resumen = la base) se descartan y el autopiloto
   sigue; casi todo lo de después muere en la guardia de módulos con `Cannot find module fechas.js/html.js`. Integra
   solo lo que no depende de nada (CSV, HTML/CSS, vistas sueltas).
2. **Exportaciones duplicadas** (`Duplicate export of 'formatear'`): añade la función en vez de sustituirla, o dos
   bloques escriben el mismo archivo (hipótesis: falta mirarlo en los encargos).
3. **La revisión contradice a los tests** («los tests esperan otra cosa») y bloquea; `npm test` sigue fallando tras 3
   rondas de arreglo.
4. **Reintento sin memoria:** el reintento empieza de cero, sin el diff anterior ni el motivo del rechazo.

**Cambios propuestos al jefe local, en orden (medir cada uno en el banco contra el 20,7 %):**
(1) no avanzar si se cae un parche del que dependen los siguientes: reintentarlo con el error concreto, o parar;
(2) reintento con memoria (diff anterior + motivo); (3) un archivo = un bloque y sustituir funciones, no añadir;
(4) en guiada los tests son la especificación: si `npm test` pasa, la revisión solo bloquea por algo comprobable;
(5) escalar el arreglo: tras 2 rondas fallidas, reescribir el archivo entero desde la especificación;
(6) mirar cómo planifica Claude (eventos de la ejecución `claude-dirige`: tareas desde la #200) y copiarle lo que funciona.

**Fallo del banco por arreglar:** `gptoss-solo` NO es válido. El banco apaga el servidor `rapido`, pero
`llama.autostart_on_task` (Ajustes, encendido por defecto) lo vuelve a arrancar con cada tarea (46 encargos del 4B).
Arreglo: que `banco.Ejecucion.correr` desactive ese ajuste mientras corre un contendiente con algún servidor a `null`
y lo restaure al acabar; después repetir `gptoss-solo`.

**Montado esta sesión para el banco:** agente «Jefe Claude (banco)» (id 15: Sonnet, `coordinator` + `delegate_local`,
solo Read/Glob/Grep + herramientas `mcp__local__*`, 40 turnos, 1 $/tarea) y contendiente
`banco/contendientes/claude-dirige.json` (tope 25 $; Lucas autorizó el gasto). El «Jefe de obra» antiguo (id 13) no
sirve para el banco: sus instrucciones son las del proyecto del poema.

**Prueba del juego (Supersalto / «mario», autopiloto de la tarde, antes del banco):** examen oculto de 35 tests:
proyecto `mario` (tras la lista de reparar) **37,1 %**; `mario-gptoss-qwen4b` (40 parches con el jefe local mejorado)
se quedó en el parche ~5 con **11,4 %** (la CLI `banco lista` interrumpió su tarea #168; se paró). Notas en
`data/examenes/`. Supersalto en el banco aún no se ha corrido (no tiene `referencia/`). `mario-chatgptoss-qwen4b` es un
intento fallido: se puede borrar. `examenes/puntuar.mjs` (sin versionar) era un puente para esa prueba: borrar.

**GUI (todo en `web/`, compilado en `web/dist`):** quitado el aire «IA» (sin degradados ni brillos, acento azul sobrio
#2f62b0, radios 10/7 px, bordes finos); barra fija arriba a todo lo ancho con logo plano; Analíticas con la paleta
validada (Claude naranja, local azul) y arreglo del tema oscuro del gráfico. Oficina (`office3d.ts` + `OfficeView.vue`):
sala más pequeña (19×14), una torre de servidores por modelo local encendido (LEDs = VRAM de su GPU, placa con el
modelo), PC con GPU y dos pantallas por mesa, pantalla de GPUs en la pared, los muñecos libres pasean (café, impresora,
agua, sofá, ventana, estanterías; A* sobre rejilla de 0,5 m) y vuelven al recibir trabajo, modo cine tras 20 s sin
tocar, androides con el mismo chasis y casco/pieza ciborg por tipo, icono único por agente (`agentIcon` en `api.ts`,
también en el avatar del chat). Misión y Aprobaciones pasaron a pestañas abajo, junto a Timeline/Modelos (menús en
L); fuera la barra «Nuevo agente / Fuera de la oficina» (los agentes se traen desde el Catálogo); worktrees: solo los
vivos, máx. 6. Sin probar en navegador todavía: Lucas lo revisa.

**Siguiente (por orden):** analizar `qwen9b-qwen4b`; arreglar el autoarranque y repetir `gptoss-solo`; cambios (1)–(2)
del jefe local y medirlos; pestaña Banco dentro de la GUI (hoy `/banco` es `banco/visor.html` suelto); `Banco.bat` a CRLF.

## ▶ 09/10/2026 — Modo 100 % local con «Supersalto»: qué pasó, qué se cambió y qué sigue
**Dónde lo dejamos (18:00):** corre la prueba base de la comparativa (`scripts\prueba-mario.ps1 -Nombre
gptoss-qwen4b -Seguir`: gpt-oss-20b en la 3060 + Qwen3.5-4B en la 1060, proyecto `mario-gptoss-qwen4b`, ya con las
mejoras de abajo cargadas). Otra sesión de Claude está montando a la vez el banco de pruebas de modelos en `banco/`
(movió ahí el examen oculto: `banco/pruebas/supersalto/examen`, `banco/puntuar.mjs`). Siguiente: la misma prueba
con Qwen3.6-35B-A3B en la 3060 (mejor UD-Q3_K_XL o Q4_K_XL con `n_cpu_moe` que IQ2) + Qwen3.5-4B en Q8_0 en la 1060.
Queda suelto un primer intento fallido: carpeta `D:\LocalHarness-proyectos\mario-chatgptoss-qwen4b`, su proyecto en
LocalHarness y `autopilot/mario-chatgptoss-qwen4b.md` (se pueden borrar).

**Qué pasó.** Mañana: «plataformas» (Saltarín) con parches poco definidos → se cayeron el 2 y el 4 y arrastraron a
los demás; el nivel inventado no tenía suelo. Proyecto nuevo **«mario»** (`D:\LocalHarness-proyectos\mario`, ENCARGO.md
+ `docs/nivel-1.txt`/`nivel-2.txt` diseñados a mano) con `autopilot/mario.md`: 40 parches de dos módulos
independientes con firmas y casos de test exactos. **39 de 40 «integrados» y el juego no arrancaba** (main.js vacío,
render.js con marcas `=======`, tamano.js convertido en JSON, jugador.js con otras funciones). De los 1.030 encargos
(tabla `events`, kind `delegate`, tareas 101–152):
- 33 de 52 planes sin los tests que pedía la tarea → `npm test` verde sin probar nada; con tests, 14 de 19 fallaban
  a la primera y las rondas de arreglo se iban a 9–12 archivos, creaban duplicados (`mapa.mjs`, `gameState.mjs`) y
  amañaban código bueno para cumplir tests inventados.
- **22 de los 39 integrados tenían la revisión local en contra**, con fallos reales: el revisor acierta, pero no
  frenaba nada.
- Ediciones: gpt-oss 245, 24 % fallidas (bucles, «se quedó pensando», BUSCAR que no encaja); Qwen 124, 11 %.
  Reescrituras enteras: 100 % bien. Las marcas de render.js venían de un bloque del Qwen con dos `=======` que
  `edits.py` aceptaba.
- El campo `skills` iba vacío en los 769 encargos: el jefe local no usaba skills.
Tarde: barrera `tests/modulos.test.mjs` + `Jugar.bat` (servidor local; los módulos ES no cargan con doble clic) en el
proyecto y lista `autopilot/mario-reparar.md` (12 parches): se integraron 10, pero sin quitar los módulos de
PENDIENTES (la barrera los saltaba) y con el código viejo; el examen oculto da **37,1 %** al proyecto.

**Qué se cambió** (278 pruebas en verde; primera prueba real en marcha):
- `boss.py`: guardias deterministas tras cada ronda (`gates`: marcas de edición, módulos JS que no cargan —también
  los que importan algo roto—, JSON en vez de código, Python que no compila) que cuentan como tests que fallan;
  **revisión que bloquea** (2 rondas de corrección; si sigue en contra o quedan guardias → `rejected`: el informe
  empieza por `REJECTED`, el adaptador devuelve `failed` y el autopiloto lo anota como «descartado (revisión)» sin
  contarlo como caída); los tests que nombra la tarea y el plan olvida → bloque `spec` escrito desde la tarea, A LA
  VEZ que el código (`tests_after_code` no los hace esperar); `edit` de archivo < 4000 caracteres → reescritura;
  rondas de arreglo con `scope` (lo tocado + lo que nombra el error + lo que nombra la tarea), sin duplicados ni .md
  sueltos; el arreglo prohíbe cambiar valores esperados; skills por etapa.
- `edits.py`: un bloque con otro separador dentro se rechaza (`MARKER`) y el modelo lo repite.
- Skills nuevas `skills/modulos-es` y `skills/tests-de-especificacion`.
- Examen oculto (35 casos de la especificación que los modelos no ven) y comparativa `Prueba-mario.bat` /
  `scripts/prueba-mario.ps1` (copia limpia en el Parche 000 b97d35c, alta por la API, `autopilot/mario-base.md` con
  39 parches, nota al final; `-Seguir` para retomar; espera a que LocalHarness conteste).
- Ojo: **cualquier comando de la CLI** (`python -m localharness project add…`) marca como `interrupted` las tareas en
  marcha (`cli._store` → `mark_interrupted`); con un autopiloto corriendo, usar la API. Así se perdió la task-98.

**Siguientes pasos para el orquestador** (por orden):
1. Medir la prueba base contra la de esta mañana (nota del examen, integrados, «descartado (revisión)», rondas,
   % de GPU) y ajustar `REVIEW_ROUNDS`/guardias si rechaza de más o de menos.
2. Que la CLI no marque `interrupted` si el servidor contesta en :8095.
3. Guardia de contrato: comprobar que cada módulo exporta los nombres que da la tarea (hoy lo mira la revisión, que
   es un modelo y puede fallar).
4. Examen por parche: correr los casos del parche al integrarlo, no solo al final.
5. Repartir el «pensar» y encadenar parches: el Qwen revisa los parches pequeños o prepara el siguiente mientras el
   fuerte planifica (hoy planificar y revisar van siempre al fuerte, y una GPU espera a la otra entre parches).
6. `--continuo` solo con guardias y examen (hoy no propone nada útil).
7. Tercera GPU (M40 de 24 GB, en camino): el reparto por cola y `suggest_servers` admiten hoy dos servidores.

## ▶ EMPEZAR AQUÍ — TODO ESTÁ EN `main` (07/10/2026)
Decisión de Lucas: **se trabaja siempre en `main`**. Se integraron en `main` las ramas `claude/gifted-carson-20grn9`
(oficina 3D + Catálogo), `claude/hopeful-euler-p8m838` (agente local con herramientas, roles, pensamiento, plan
editable), `claude/cool-dirac-vmw6s0` (análisis de Paperclip) y `claude/youthful-edison-bi67hm` (Modelos locales +
rediseño de la oficina). Las secciones de abajo son el historial de cada una; donde digan «rama X», ya está en `main`.

### Autopiloto del 08/10/2026 y lo que se cambió con sus datos (08/10, mañana)
- **El autopiloto se quedó «parado» en el parche 1**: no paró, se congeló en un `print` porque la consola tenía la
  edición rápida (QuickEdit) y un clic en la ventana bloquea el proceso. Ahora la desactiva al empezar. Además relee
  la lista antes de cada parche (se puede alargar en marcha), adopta la tarea viva si se reinicia y cuenta como
  integrada/descartada la que decidas tú a mano. Lista de `poeta` ampliada a 48 parches, tope nominal 15 $.
- **Análisis de los 7 primeros parches** (7/7 integrados, 1,32 $, 81 encargos locales, 0 líneas de Claude): el 4B
  de la 1060 va a ~25 tok/s y el 14B de la 3060 a 27–31 (el «rápido» no es más rápido); 47 % del tiempo en el primer
  plan, 25 % en `local_agent` atascado (1 de 6 bien), 12 % en rondas de arreglo, 15 % Claude. 5 de 7 primeras rondas
  fallaron por tests que adivinaban el marcado (iban en paralelo con el HTML). En el parche 005 Claude mandó 12 de 13
  bloques al rápido y el fuerte estuvo 5 min parado.
- **Cambios en `mcp_local`** (commit c32a22c): reparto por cola (`claim`/`release`: el modelo con menos encargos en
  curso; `server` y papel desempatan), tests después de su código (`tests_after_code`), arreglo automático sin Claude
  (`auto_fix`, `AUTO_FIX_ROUNDS = 2`), `local_agent` desaconsejado para arreglos, checks con
  `PYTHONDONTWRITEBYTECODE`. Informe del autopiloto con tiempo generando real (tokens ÷ tok/s). 220 pruebas.
- **README nuevo** con capturas reales (`docs/capturas/`, Chrome headless contra la GUI abierta durante el autopiloto).
- **Ideas para gastar menos Claude** (sin hacer): planificar por tandas (un Claude para 4–5 parches), revisión
  periódica del diff de la tanda, `MAPA.md` del proyecto mantenido por el modelo local, bloques de edición
  (buscar/reemplazar) en vez de reescribir archivos enteros (styles.css se reescribe entero en cada parche),
  probar Qwen2.5-Coder-7B en la 1060, y medir con la Comparativa si Qwen-14B planifica bien los parches de plantilla.
- Bug visto en las capturas: Modelos locales → «Velocidad de la última respuesta … hace 20714 días» (fecha 0).

### ▶ MAÑANA 08/10/2026, 7:00 — Lucas lanza el autopiloto antes de irse a clase (6 h) — leer primero
1. Reiniciar LocalHarness (`LocalHarness.bat`) y Ctrl+F5: así carga todo lo de abajo (Job Object, MCP arreglado…).
2. Modelos locales: si sale el aviso de llama-server sueltos → «Apagarlos». Arrancar **Qwen-2.5-Coder-14B Q4_K_M
   en Fuerte (CUDA0, 3060)** y **Qwen3.5-4B en Rápido (CUDA1, 1060)**; mejor el Rápido con `parallel: 2`.
3. Opcional: un parche a mano en «poeta» con «Jefe de obra» para ver que va.
4. Doble clic en `Autopiloto.bat` (lista `autopilot/poeta.md`, 18 parches; máx. 6 h, 5 $, 30 min por parche).
5. Al volver: `data/autopilot/poeta-informe.md` + pedir a Claude Code que analice las tareas «Autopiloto N/18»
   (eventos `delegate`, `worker_live` no se guarda; pensamientos en `delegate.data.thinking`) con el script de
   volcado de eventos por tarea (id, kind, text, data).

### Prueba real con dos GPU y lo que salió (07/10/2026, 20:30)
- **Tarea 17 (Dynamic Island)**: los dos modelos trabajaron (Qwen-2.5-Coder-14B «principal» escribió tests,
  Llama-3.1-8B «rapido» hizo una revisión que Claude descartó por inventar líneas), pero **uno detrás de otro**: el
  `local_ask` empezó justo cuando acabó el `local_write_file`. Causa: Claude Code solo lanza a la vez herramientas MCP
  con `readOnlyHint`. Arreglo: `local_ask`, `local_research` y `run_checks` lo llevan; la guía multi-modelo dice
  que para que los dos ESCRIBAN a la vez hay que usar `local_execute_plan` con `after`.
- «Aprobé y no se pusieron a trabajar»: el botón de la revisión es aprobar **los cambios** (integrar), no más
  trabajo; para seguir, «Pedir cambios» o un mensaje nuevo en la misma tarea.
- **Un avatar por modelo** en la oficina: puesto `w<tarea>~<servidor>` («Local · Fuerte», «Local · Rápido», un color
  cada uno), con sus encargos (la llamada de Claude se empareja con la entrada del log por herramienta + encargo/
  archivo), su directo y sus paquetes. `live.json` lleva `servers: {id: …}` y el orquestador emite un
  `worker_live` por modelo. El directo se escribe también al EMPEZAR cada encargo (antes no se veía nada mientras
  el modelo leía el prompt).
- **tok/s del monitor de recursos**: solo se actualizaba con agentes locales; con Claude delegando nunca. Ahora el
  directo lleva `tps` (trozos/s mientras escribe; al final, el de llama-server) y `worker_live`/`delegate` cuentan.
- **Sandbox nuevo** `C:\Users\Lucas\LocalHarness-poeta` (proyecto «poeta», solo `ENCARGO.md` + `package.json`):
  web estática que crece por parches, cada uno con su entrada de blog poética (código → fuerte, poema → rápido).
  Agente #13 «Jefe de obra» (Sonnet, coordinador, 30 turnos, 1 $).
- **Tareas 19 y 20 (sandbox, agente «Organizador»)**: el agente tenía «Solo lectura» marcado → ni Claude (Haiku)
  ni el modelo local podían escribir (sin `local_write_file`/`local_execute_plan`), y Haiku se pasó ~20 encargos
  pidiendo al modelo local que escribiera «con PowerShell/git/Python». Además, `local_ask` sin `files` → Llama-8B
  se inventó un proyecto React/Express entero y Haiku lo presentó como informe. Arreglos: la guía de solo lectura
  prohíbe esos rodeos; `local_ask` avisa (descripción + prompt de sistema `NO_FILES`) de que sin `files` no ve el
  repo ni recuerda encargos; el asistente de agentes avisa de «Solo lectura» + delegar.
- **Tarea 21 (poeta, Jefe de obra)**: Sonnet coordinó muy bien (un plan con `after`, revisa y reencarga solo lo
  que falla). Los dos modelos trabajaron a la vez de verdad. Fuerte = Devstral-Small **IQ2_M** (2 bits): test con
  errores de sintaxis a la primera, `parseInt('001')`; rápido = Qwen3.5-4B sin pensar: rápido y correcto (poema
  flojito). **`local_agent` se colgaba**: `snapshot()` hacía `git status` sin `stdin=DEVNULL` desde un hilo
  mientras el principal lee stdin → en Windows se bloquea. Arreglado. Sin explicar: en el primer intento los
  modelos no arrancaron solos y `ensure_for_task` no avisó de nada.
- **llama-server sueltos al cerrar la ventana**: cerrar la consola mata Python de golpe y el `lifespan` no llega a
  pararlos. Ahora cada llama-server entra en un Job Object de Windows con KILL_ON_JOB_CLOSE (`llama._die_with_us`;
  probado en el PC de Lucas: muere el padre → Windows mata al hijo). Además, Modelos locales → «Apagar todos los
  modelos» (`POST /api/llama/stop-all`, `LlamaPool.kill_everything`) y aviso de los sueltos (`GET /api/llama` →
  `strays`, con `llama.running_servers()` por psutil o tasklist).
- **Oficina**: el engranaje de «Modelo local» en la misión giraba orbitando (el `<i>` se estiraba a la fila de la
  rejilla); ahora caja cuadrada. «Tokens/s (local)» SUMA los modelos que escriben a la vez (`live.localWork`, uno
  por servidor, desde `worker_live`). Pestaña nueva **Modelos** en el panel de abajo (`OfficeDock`): una tarjeta por
  modelo local con qué tiene cargado, encargo en curso (tarea, tipo), tok/s, tokens, tiempo, y lo que piensa y
  escribe en directo; libre → su último encargo.
- **Autopiloto** (`localharness/autopilot.py`, `python -m localharness autopilot`, `Autopiloto.bat`): con
  LocalHarness abierto, hace sola una lista de parches (`autopilot/poeta.md`, 18 escritos por Claude Code, sin
  gastar plan) en «poeta» con «Jefe de obra»: re-arranca modelos caídos, tope por parche (cancela), tests en el
  worktree → aprueba + integra; si fallan, UNA respuesta con la salida y si no, descarta; para por horas, $ o 3
  fallos seguidos; no deja suspender Windows; estado JSON para retomar; informe `data/autopilot/poeta-informe.md`
  (por parche y por modelo: encargos, tokens, minutos, % de GPU ocupada). 7 pruebas con API falsa + comprobado
  contra la API real sin lanzar nada.
- **Tareas 22–23 (poeta)**: fuerte = Qwen-2.5-Coder-14B (≈28 tok/s), rápido = Qwen3.5-4B (≈25,6). Claude no escribe
  ni una línea (0 Edit/Write) pero dicta el diseño: ~2k tokens de instrucciones exactas por parche; salida de Claude
  5,6k–7,4k tokens frente a 6,2k–10,3k locales; 0,18 $ por parche. Cola por servidor (`-np 1`): un CHANGELOG de 100
  tokens esperó 115 s detrás de un CSS de 3.000. `local_agent` con Qwen-Coder-14B repite lecturas y no acaba.
- 213 pruebas (venv), ruff limpio, web compila. **Pendiente**: reiniciar LocalHarness y probar el sandbox poeta.

### DÓNDE LO DEJAMOS (07/10/2026, noche)
- **Todo en `main` y en GitHub** (último trabajo: dos GPU + las 4 mejoras de abajo). 201 pruebas, ruff limpio, web compila.
- **PC de Lucas**: RTX 3060 12 GB (llama.cpp `CUDA0`) + GTX 1060 6 GB (`CUDA1`; en nvidia-smi el orden es el
  contrario). llama.cpp en `D:\dev-tools\llama.cpp\b11379`, modelos en `D:\ollama\models` (Qwen3.5-9B y
  Qwen3.5-4B Q4_K_M). Sandbox creado en `C:\Users\Lucas\LocalHarness-sandbox` (proyecto «sandbox»).
- **Última prueba de Lucas**: «el segundo modelo también va a la 3060». Diagnóstico: seguía abierto el
  LocalHarness ANTERIOR a los cambios (arrancado 18:33; el llama-server sin `-dev` ni `-lv 4`; base de datos en
  esquema 5, la nueva migra a 6; `llama.servers` sin configurar). Con un solo servidor, arrancar otro modelo
  sustituye al anterior. **Solución**: cerrar LocalHarness del todo, abrir `LocalHarness.bat`, Ctrl+F5, Modelos
  locales → «Usar las 2 GPU» y arrancar con «Arrancar en Fuerte / Rápido».
- **Ojo**: la 1060 tenía 3,1 GB ocupados sin modelo (¿monitores conectados a ella?): el 4B va justo; bajar
  contexto o caché q8_0, o conectar los monitores a la 3060.
- **Pendiente de probar (Lucas)**, en orden: dos servidores en la GUI (dos paneles, CUDA0/CUDA1) → arranque
  automático de modelos al lanzar tarea → prompt guiado con un agente coordinador (plantilla programador +
  Haiku + «Jefe del modelo local») que pide `local_execute_plan` con `after` → prompt natural («arregla todos
  los fallos y añade tests») para ver si Claude reparte solo → Comparativa en el sandbox con haiku.
- **Siguiente (yo)**, según lo que salga: reforzar la guía del coordinador si Claude no usa `after` ni reparte;
  ver a los dos trabajadores en directo en la oficina (hoy un `live.json` por tarea); decidir el modelo de la 1060
  con los números de la Comparativa.
- `web/package-lock.json` sale modificado tras `npm install` en Windows (`"dev": true` → `devOptional`): ruido de
  la versión de npm, no se sube.

### Mejoras para aprovechar las dos GPU (07/10/2026, noche) — Lucas las prueba a la vuelta
1. **Pensamiento por servidor** (`llama.servers[].thinking`: normal | apagado | profundo → `chat_template_kwargs`
   en cada encargo). Medido con Qwen3.5-4B: apagado 0,4 s / 3 tokens frente a 8,9 s / 216 (`reasoning_budget: 0`
   por petición NO funciona en b11379). «Usar las 2 GPU» deja el rápido apagado. Columna en Servidores locales.
2. **Arrancar solos los modelos** (`local_servers.ensure_for_task`, ajuste `llama.autostart_on_task`, por defecto
   sí): una tarea que delega/coordina, o un agente local, arranca los servidores apagados con su último modelo y
   espera (máx. 3 min) con avisos en el Timeline. `local_servers.py` sale de `api.py`; `llama.POOL` = el de la API.
3. **Plan en paralelo**: bloques de `local_execute_plan` con `after` (ids de bloques anteriores). Si alguno lo
   lleva, los independientes van a la vez (hilos, cada uno al servidor de su tipo) y los que dependen de uno
   fallido no se hacen; sin `after`, en orden como siempre. Prueba real: 4 bloques (3 a la vez + tests que
   esperan a calc.py) en 7,5 s frente a ~13 s en serie; 8 tests pasan.
4. **Comparativa** (`/comparativa`, `compare.py`, tabla `comparisons`, `/api/compare`): misma petición con «Solo
   Claude», «Claude + 1 modelo local» (`config.local_servers = ["principal"]`) y «Claude + todos»; una tras otra
   como tareas normales (agentes `comparativa-N-variante`, ocultos en la oficina) y se mide: tokens de Claude
   (entrada nueva + salida; caché leída aparte), coste nominal, tiempo, encargos y tokens locales por servidor,
   archivos ±, y la orden de tests en cada worktree. Marca la mejor celda y el % de plan ahorrado frente a solo
   Claude. Probado con la CLI falsa; **una de verdad gasta plan** (la lanza Lucas, en el sandbox).
- Sin hacer de la lista: ver a los dos trabajadores en directo en la oficina (hoy un `live.json` por tarea).
- 201 pruebas.

### Dos GPU, dos modelos (07/10/2026, tarde — en el PC de Lucas: RTX 3060 12 GB + GTX 1060 6 GB)
Objetivo de Lucas: que todo el sistema vea normal tener dos modelos locales y dos GPU, para probar el reparto de
trabajo entre ellos y Claude.
- **Servidores locales** (`llama.servers` en Ajustes; `settings.local_servers`): `[{id, name, port, device, role}]`,
  el «principal» siempre (su puerto = `llama.port`), máx. 4. `role`: `general` | `fuerte` (escribe código, `local_agent`)
  | `rapido` (preguntas, resúmenes, investigar). `device` = `-dev` de llama.cpp (`CUDA0`, `CUDA1`, `CUDA0,CUDA1`).
- **Numeración de GPU**: `llama.list_devices()` usa `llama-server --list-devices`. En este PC **CUDA0 = RTX 3060 y
  CUDA1 = GTX 1060**, al revés que nvidia-smi (índice 0 = la 1060). La GUI siempre dice nombre + CUDAn.
- **`LlamaPool`** (api: `app.state.llama`): un `LlamaManager` por servidor, con su log (`llama-server-<id>.log`),
  su `--api-key` (`llama.KEYS[puerto]`, `key_for_url`) y su autoarranque (`llama.last` del principal,
  `llama.last_by_server` del resto). Arranque con `-lv 4`: desde ~b11000 llama.cpp no escribe en qué GPU carga
  nada con la verbosidad normal (sin eso, «Dónde está cargado» y la barra de carga se quedaban vacíos).
- **API**: `start` (`server` en el cuerpo), `stop`/`probe`/`usage` (`?server=`), `estimate` (`server`: memoria de las
  GPU de ese servidor, `hardware.device_budget`), `GET /api/llama` (`servers`, `devices`, `suggested_servers`),
  `GET /api/llama/devices`, `/api/health` → `locals`. Opciones nuevas de arranque: `device`, `split_mode`,
  `tensor_split`, `main_gpu`. Un agente local puede fijarse a un servidor (`config.server`).
- **Delegación** (`mcp_local`, `LH_LOCAL_SERVERS`): cada encargo va al modelo de su papel; Claude puede elegir con
  `server` (también por bloque en `local_execute_plan`); si el elegido no contesta, el siguiente; **cada `tools/call`
  va en su hilo**, así que si Claude pide dos cosas a la vez los dos modelos trabajan en paralelo. La guía de
  delegación lista los modelos cuando hay más de uno. El log de encargos apunta `server`.
- **GUI**: Modelos locales → un panel por servidor (estado, GPU, Parar, 🧪, log), tarjeta «Servidores locales»
  (editar; «Usar las 2 GPU» propone fuerte en la grande y rápido en la otra), «Arrancar en …» sobre Tus modelos,
  el diálogo de arranque dice dónde arranca y deja cambiar/juntar GPU; Consumo en vivo con un bloque por proceso;
  oficina, chat, catálogo y asistente de agentes muestran los dos modelos.
- **Probado de verdad** (sin Claude): LocalHarness arrancó Qwen3.5-9B en CUDA0 y Qwen3.5-4B en CUDA1 (listos en 9 s),
  dos encargos a la vez fueron cada uno a su modelo (el 9B escribió un archivo a 51 tok/s), y con el rápido apagado la
  pregunta pasó sola al fuerte. 194 pruebas.
- **Pendiente / siguiente**: probar desde la GUI (reiniciar LocalHarness); una tarea real con Claude coordinando a los
  dos; medir si compensa (¿4B como rápido o mejor otro modelo en la 1060?); que `local_execute_plan` haga en paralelo
  los bloques independientes; el directo (`live.json`) es uno por tarea aunque trabajen dos modelos (gana el último).

### Lista de Lucas (08/10/2026, mediodía) — analíticas, consumo, agentes a medida, Trabajo, directo del modelo local
- **Integrar sin identidad de git** (fallaba en el PC del instituto: «Committer identity unknown»): el merge usa tu
  identidad si git la tiene y, si no, `LocalHarness <localharness@local>` (`workspace.identity`). No toca tu config.
- **401 «Invalid API Key» tras reiniciar LocalHarness**: la `--api-key` del llama-server que arrancamos se guarda en
  `data/llama-server.key` y se reutiliza al volver a abrir (si sigue encendido). Un 401 se explica y para el plan.
- **Analíticas** (`/analiticas`, `localharness/analytics.py`, `GET /api/analytics?days=`): peticiones (tareas +
  respuestas tuyas), tokens de Claude (con caché) y del modelo local (agentes locales + encargos), coste, encargos por
  tipo y por modelo GGUF, uso por agente, tokens por día (barras apiladas, tabla alternativa). Paleta validada con el
  validador de dataviz (claro #5b5bf0/#0891b2, oscuro #7a7af4/#0a9fc0).
- **Consumo** (`localharness/usage.py`, dependencia nueva `psutil` en `[server]`; sin ella, CPU/RAM aproximadas):
  CPU (total y por núcleo) y RAM en Recursos de la oficina; en Modelos locales, «Consumo en vivo» con el proceso de
  llama-server (RAM, CPU, VRAM por `nvidia-smi --query-compute-apps`) y **dónde está cargado el modelo** (capas en GPU
  y MB por dispositivo, leído del log de llama-server: `GET /api/llama/usage`).
- **Rack de CPD** en la oficina: armario 42U con puerta de cristal, switch (LEDs de red), servidor GPU con ventiladores
  y LEDs de VRAM, servidores con LEDs de CPU, cabina de RAM, SAI y suelo técnico. Los LEDs siguen el uso real.
- **Paneles redimensionables** en la oficina: asas entre columnas y sobre el panel de abajo (doble clic = por defecto;
  se guarda en el navegador).
- **Agentes a medida** (`localharness/designer.py`): ya no se crean solos los agentes de `roles/*.md` (ajuste
  `roles_autosync`, por defecto False; los que había se borran si no tienen historial o quedan fuera de servicio).
  En «Nueva misión», «✨ Agente a medida» → Claude Haiku (JSON validado) propone proveedor/modelo, coordinador,
  skills (del agente y de su modelo local), MCP, internet, pensamiento y motivo; puedes quitar cosas y «Crear agente
  y ejecutar» (`POST /api/agents/design` y `/api/agents/generated`, `config.generated`). Sin Claude: reglas. Un plan
  sin trabajadores diseña uno. En la oficina, un agente a medida está mientras su tarea siga abierta.
- **Trabajo** (`/trabajo`, sustituye a «Pendiente de ti»): en curso en vivo (con lo que hace el modelo local), lo que
  espera tu decisión y lo reciente; revisión con riesgo, encargo, respuesta, archivos con +/− y diff coloreado por
  archivo, y Aprobar e integrar / Solo aprobar / Descartar / Pedir cambios (sigue en la misma rama).
- **Modelo local en directo**: el servidor MCP pide a llama-server en streaming y escribe `live.json` (LH_LIVE) ~1/s;
  el orquestador lo emite como `worker_live` (efímero). La oficina enfoca al trabajador local al entrar, muestra
  «trabajando · N skills», el bocadillo con lo que piensa/escribe y, en su inspector, «En directo» y «Pensando ahora».
  El Chat enseña en cada encargo «Cómo lo pensó», su respuesta y lo que le pidió Claude, y una caja en directo. La
  Misión resume el encargo (y por qué el agente es así) y lista los encargos al modelo local con su estado.
- Probado: 179 pruebas + recorrido completo en Chromium con una CLI de Claude falsa en el PATH y un llama-server falso
  que razona en streaming. **Pendiente**: probarlo en el PC de Lucas con Qwen real (sobre todo el streaming y
  «dónde está cargado» con una GPU NVIDIA).

### Trabajador local en la oficina (08/10/2026) — Claude lo equipa; tú lo ves y lo corriges
Petición de Lucas: que Claude piense primero qué skills y herramientas necesita el modelo local, y que al encargarle
algo aparezca un muñeco del trabajador local con su pensamiento, su propio chat y sus skills (añadir/quitar).
- **`local_prepare`** (MCP, primera herramienta de la lista): Claude elige skills (de las instaladas + biblioteca;
  la lista va en la descripción de la herramienta) y herramientas del agente local (`WORKER_TOOLS`), con el motivo.
  Se guarda en `worker.json` de la carpeta de la delegación (LH_WORKER); el catálogo, en `skills.json` (LH_SKILLS).
  El servidor relee el estado en CADA encargo: las skills van al prompt de sistema (ask/write/plan) o al de la
  tarea (`local_agent`, que además solo recibe las herramientas elegidas: `LocalAgentAdapter(only_tools=…)`).
  Las guías del coordinador y de delegar tienen un paso 0 «equipa al trabajador local».
- **Chat y pensamiento**: cada encargo apunta `request`, `answer`, `thinking` (reasoning_content) y `skills` en el
  log → eventos `delegate`; el pensamiento de `local_agent` sale como `worker_thinking`. Cambios de equipo →
  evento `worker` (quién: Claude / tú / el agente). `local_prepare` no cuenta como encargo.
- **API**: `GET /api/tasks/{id}/worker` (lo que lleva, si está activo, skills disponibles, herramientas) y
  `PUT` (cambiarlo mientras trabaja: `orchestrator.set_worker`, registro `ACTIVE_WORKERS`; 409 si ya no trabaja).
  `config.local_skills` del agente = skills con las que arranca su trabajador («Usar siempre estas skills»).
- **Oficina**: puesto `w<tarea>` de tipo `local` (robot azul con visor y chip, línea discontinua a su Claude:
  `StationSpec.boss`). Entra cuando Claude le encarga algo; paquetes Claude → trabajador → rack y de vuelta.
  Inspector `office/LocalWorkerPanel.vue`: pestañas Chat / Piensa / Skills (quitar ×, añadir, herramientas).
- Probado: 169 pruebas + capturas en Chromium con un llama-server falso. Una de las tareas de la demo la hizo por
  error la CLI real de Claude del contenedor (el rol se resincronizó al reiniciar y perdió el binario falso): equipó
  sola al trabajador (`cambios-minimos`, `manejo-de-errores`) y los cambios de skills hechos desde la GUI a mitad
  de tarea se aplicaron. **Pendiente**: probarlo en el PC de Lucas con Qwen de verdad.

### Revisión completa y delegación unificada (07/10/2026, noche) — LEER `docs/REVISION.md`
- **Delegación**: el modo coordinador de abajo y el «modo jefe» de otra sesión se unificaron en `coordinator`.
  Además: herramienta **`local_agent`** (encarga una tarea entera al agente local con herramientas en el mismo
  worktree; devuelve resumen + archivos cambiados; sus pasos salen en vivo como `progress`), **`run_checks`**
  (tests de la lista blanca `LH_COMMANDS`/`CHECK_COMMANDS`, sin modelo), las guías (coordinador / delegar / solo
  lectura) van en **`--append-system-prompt`** (`RunSpec.system_append`), aviso «Claude no le encargó nada».
  Coordinador sin llama-server → aviso y **Claude trabaja solo esa vez** (antes: tarea que no podía hacer nada).
  Asistente: «Trabaja con el modelo local» + «Jefe del modelo local (solo coordina)» / «Con ayuda». Rol
  `programador` y plantillas programador/frontend en modo coordinador.
- **`localharness probar-delegacion`**: prueba gratis (sin Claude) la mitad local contra tu llama-server.
- **Seguridad**: la API solo atiende a Host/Origin locales (antes una web cualquiera podía añadir un «MCP» que
  ejecuta un programa). `serve --host 0.0.0.0` lo desactiva y avisa.
- **Calidad**: `ruff` (config en `pyproject.toml`) limpio, **CI** en `.github/workflows/ci.yml` (Linux + Windows,
  Python 3.10/3.12, web). 165 pruebas.
- **Pendiente**: prueba real en el PC de Lucas (pasos en `docs/REVISION.md` §3 P1).

### Modo coordinador (07/10/2026, noche) — Claude planifica, el modelo local genera
Problema (Lucas): con «Puede delegar», Claude seguía resolviendo la tarea él (Glob → Read ×4 → Edit ×4) y no
encargaba nada. La guía de delegación sola no basta: mientras tenga Edit/Write, lo hace él.
- Config nueva del agente `coordinator` («Solo coordina» en Ajustes; rol `roles/coordinador.md`, Sonnet). Implica
  `delegate_local`. Claude se lanza con **solo Read/Glob/Grep** + las herramientas del modelo local: no puede escribir
  ni ejecutar, así que el trabajo lo tiene que hacer el modelo local.
- Herramienta MCP nueva **`local_execute_plan`** (`mcp_local.py`): Claude manda TODOS los bloques en una llamada
  (`write` con `path` / `ask`), el modelo local los hace en orden (cada bloque lee sus `files`, también lo escrito
  por bloques anteriores), y el servidor ejecuta `check` (tests, lista blanca `CHECK_COMMANDS`, sin shell). Devuelve
  un informe por bloque. Un bloque que falla no para el resto; sin llama-server se para y lo dice.
- Guía `COORDINATOR_GUIDE` (orchestrator): separar en bloques → explorar lo justo (`local_ask` para diagnosticar,
  no Read) → escribir el plan → `local_execute_plan` entero → leer informe y repetir solo lo fallido (máx. 2
  rondas) → presentar. Con `LH_COORDINATOR=1` los errores dicen «díselo al usuario» en vez de «hazlo tú».
- Aviso al empezar si el llama-server no contesta (`/health`). Los delegadores normales también ven `local_execute_plan`.
- **Pendiente: prueba real** en el PC de Lucas (sandbox: agente `coordinador` + «arregla todos los errores del repo»).
  Siguiente paso posible: que el coordinador **arranque él el último modelo** si está apagado (hoy solo avisa).

### Lo último (07/10/2026, noche) — Catálogo ampliado y asistente de agentes
- **Biblioteca** (`biblioteca/`, `localharness/library.py`): 27 skills en español con categoría (`biblioteca/skills`),
  19 servidores MCP preparados (`biblioteca/mcp.json`: fetch, DuckDuckGo, Brave, Context7, DeepWiki, Microsoft Learn,
  Hugging Face, GitHub, Git, Playwright, Chrome DevTools, sistema de archivos, SQLite, MarkItDown, memoria,
  pensamiento secuencial, Serena, hora, everything) y 11 plantillas de agente (`biblioteca/agentes.json`).
  Instalar una skill = copiarla a `data/skills`; un MCP con `params` (token, carpeta) pide los datos al añadirlo.
- **Skills de GitHub**: `POST /api/library/github {url}` acepta `usuario/repo`, `…/tree/rama/carpeta`, un `blob` de un
  SKILL.md o `raw.githubusercontent`. Para repos/carpetas usa la API de GitHub (60 consultas/h sin token; con
  `GITHUB_TOKEN` en el entorno, más). Solo se importa el SKILL.md (con `source:` en el frontmatter). Probado real
  con un archivo de `anthropics/skills`; el listado de un repo entero no (la API estaba bloqueada en el contenedor).
- **Catálogo** (`CatalogOverlay.vue`): Skills → Biblioteca / Instaladas / Desde GitHub; MCP → Preparados / Añadidos;
  filtro por categoría; panel de vista previa (SKILL.md renderizado, configuración con claves tapadas) desde el que se
  instala y se asigna a agentes. Avisa si falta `npx`/`uvx` en el PC.
- **Asistente de agentes** (`AgentWizard.vue`, `ui.wizard`/`openWizard()`): plantilla por rol → cerebro (Claude
  Haiku/Sonnet/Opus, o modelo local «con herramientas»/«solo responde» con tus GGUF ordenados por la nota de
  `catalog.rate_local` para el rol de la plantilla y el mejor marcado «recomendado») → skills y MCP (lo que venga de la
  biblioteca se instala al guardar; los MCP con clave hay que configurarlos en el Catálogo) → nombre, descripción,
  instrucciones y límites. Vista previa en vivo con avisos. Al crear lleva al agente a la oficina. **Editar** con el
  mismo asistente desde el Catálogo, el inspector de la oficina y Ajustes (el formulario viejo queda como «Avanzado»).
  API: `instructions` y `template` al crear; el PATCH acepta `provider`, `name` e `instructions`.
- Windows: los MCP con `npx` se lanzan como `cmd /c npx …` (`orchestrator.win_shim`), que es lo que pide la CLI de Claude.
- ⚠ Sin probar con la CLI real: que los MCP preparados arranquen bien en el PC de Lucas (necesitan Node/uv).

### Antes (07/10/2026, tarde)
- **Oficina rediseñada** (`web/src/office/office3d.ts`): muñecos androide (color del agente, accesorio por rol: corona
  director, casco trabajador, cascos con micro jefe técnico, gafas consultas, corbata tú), puestos de madera con
  cajonera, monitor con código animado, flexo y silla con ruedas, sala tipo Habbo (tarima, papel pintado, estanterías,
  reloj de verdad, corcho, ventanas con cortinas, sofá, fuente). Vista casi isométrica; los muñecos de espaldas.
- **Mover puestos**: arrastrar con el ratón (botón «Mover»/«Bloqueado» arriba), «Girar» en el inspector, «⟲» vuelve a
  lo de por defecto. Se guarda en el ajuste `office_layout` ({"you"|"a<id>"|"rack": [x, z, giro]}).
- **Quitar de la oficina** (inspector): `config.off = true` → fuera de servicio, no sale en la oficina y el Director no
  le encarga nada (`hierarchy._workers`); si estaba trabajando, ofrece cancelar su tarea. Se vuelve a llamar desde
  «Fuera de la oficina» (abajo).
- Pensamiento en vivo del agente en el inspector. Descargas de Hugging Face preguntan la carpeta.
- Conflictos de la integración resueltos: `web` de un agente = internet (Claude: WebSearch/WebFetch, apagado por
  defecto; agente local: buscar_web/leer_url, encendido); la delegación MCP suma `local_research` a los servidores
  del Catálogo; el Inicio lo sustituyó la Oficina.

- **Arranque fácil** (07/10, tarde): `LocalHarness.bat` (prepara la primera vez y arranca), `Actualizar.bat`,
  `Crear acceso directo.bat` (icono `scripts/localharness.ico` en escritorio y menú Inicio), `scripts/preparar.bat`;
  `localharness start` (servidor + navegador; si ya está en marcha solo abre la pestaña); ajuste
  `llama.autostart` + `llama.last` → al abrir arranca el último modelo con sus ajustes (`api.autostart_llama`).
- **Fase 2 propuesta (sin hacer)**: instalador `.exe` con asistente (Inno Setup) que lleve Python embebido y la web ya
  compilada (sin pedir Git/Python/Node), descargue llama.cpp según la GPU (CUDA/Vulkan/CPU), cree accesos directos,
  y «Buscar actualizaciones» en Ajustes (versiones publicadas en GitHub Releases por una Action al etiquetar).

### Siguiente (lista de Lucas)
1. ✅ Catálogo con muchas más skills y MCP (biblioteca, GitHub, categorías, vista previa). Hecho el 07/10 noche.
2. ✅ Asistente de agentes (plantillas, modelo local recomendado, skills/MCP, vista previa, editar). Hecho el 07/10 noche.
3. Probar la oficina nueva y los modelos locales en el PC del instituto (Lucas lo está haciendo) y ajustar.
4. Pendiente de antes: Atlas «Analizar proyecto», Claude como jefe del agente local autónomo (ver secciones de abajo).

## Sesión 07/10/2026 (mañana) — Pestaña de Modelos locales
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

## Punto de partida de la rama de la oficina (07/10/2026, mañana) — ya integrada en `main`

Instalar en otro PC: `docs/INSTALAR.md`.
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

## ▶ Rama `claude/hopeful-euler-p8m838` (06/10/2026, noche) — integrada el 07/10 en `claude/youthful-edison-bi67hm`

Última actualización: 07/10/2026, noche (dos GPU, dos modelos y Comparativa; ver «DÓNDE LO DEJAMOS»). Hoja de ruta: `docs/HOJA-DE-RUTA.md`.

### Lo que quedaba pendiente en esa rama

Rama de trabajo: `claude/hopeful-euler-p8m838` (sin fusionar en `main`; Lucas la prueba en local y decide el PR).
Rumbo y lista de objetivos: **`docs/OBJETIVOS.md`**. Diseño acordado (cómo funciona todo y cómo se verá):
**`docs/DISENO-OFICINA.md`**. Guía completa de funciones, API, eventos y config: **`docs/GUIA.md`**.

### 1. Lo primero: recoger el resultado de las pruebas de Lucas en su PC
Instalar: `git checkout claude/hopeful-euler-p8m838 && git pull`, `pip install -e .[server]`,
`cd web && npm install && npm run build`, `python -m localharness serve`. Lista de comprobación:
- [ ] **Plan editable**: Planes → nuevo plan (Director de Claude, p. ej. Haiku) → editar un paso, «Pedir al
      Director que lo rehaga», «Aprobar todo y ejecutar».
- [ ] **Agente local con herramientas** (`qwen-agente` del sandbox, o el rol `programador-local`/`explorador`) con
      **Qwen3.5-9B**: que use herramientas (leer, buscar_web, escribir, ejecutar tests). Si no: Ajustes → agente →
      Modo de herramientas = json.
- [ ] **Búsqueda web delegada**: agente de Claude con «Puede delegar en el modelo local» + pregunta que necesite
      internet → en el chat «🦙 Modelo local investigó en la web…». (DuckDuckGo HTML: si bloquea, plan B SearXNG.)
- [ ] **Pensamiento**: conversación con «profundo» (¿la CLI acepta `--effort`?) y Qwen3 con «apagado» (¿deja de razonar?).
- [ ] **Ver pensar**: Inicio → tarjeta del agente con «💭 pensando ahora» mientras Qwen razona.
- [ ] **Roles**: Ajustes → Agentes muestra explorador, programador-local, programador y revisor («rol · roles/x.md»).

### 2. Qué se hizo en esta sesión (todo con pruebas: 111, CLIs y llama-server falsos)
| Objetivo | Qué hay | Dónde |
|---|---|---|
| 1 Manual del Director | el «algoritmo» del Director en un archivo editable, inyectado en su prompt | `manual/director.md`, `hierarchy.director_manual` |
| 2 Búsqueda web | `local_research` en el MCP local: Qwen busca (DuckDuckGo), lee páginas y responde con fuentes | `mcp_local.py` |
| 3 Plan editable | `plans.always_review` (por defecto sí); editar/quitar/reordenar pasos, rehacer uno con el Director (reanuda su sesión), aprobar todo | `hierarchy.edit_plan/redo_step`, `PUT /api/plans/{id}`, `POST /api/plans/{id}/redo`, `PlanView.vue` |
| 4 Ver a los subagentes | eventos `thinking` (Claude y locales) y `thinking_live` (efímero); 💭 en la tarjeta del Inicio, plegado en el chat | `adapters/claude.py`, `adapters/local.py`, `HomeView.vue` |
| 5 Roles | `roles/*.md` → agentes sincronizados al arrancar y al planificar (`config.from_role`; el archivo manda) | `roles.py`, `roles/`, `GET /api/roles` |
| 8 Agente local | proveedor `local_agent`: bucle propio con leer, listar, buscar, escribir, ejecutar (lista blanca, sin shell), buscar_web, leer_url, preguntar_director (dentro de un plan, máx. 3), avisar_progreso, terminar; modo `json` de reserva; config desde Ajustes | `adapters/local_agent.py` |
| §5 Pensamiento | apagado/normal/profundo por agente, rol, paso y conversación. Claude `--effort low/high` (+`MAX_THINKING_TOKENS=0`), locales `enable_thinking` | `adapters/*`, `tasks.thinking` |
| Docs | README reescrito, `docs/GUIA.md` nueva (subagente), incoherencias corregidas | |

Avisos: `ejecutar` NO aísla la red; `--effort` y `enable_thinking` están verificados en documentación, no en el PC.
Las pruebas apagan los roles con `LOCALHARNESS_ROLES_DIR=""` (`tests/__init__.py`).

### 3. Qué toca después (en orden propuesto)
1. Arreglar lo que salga de la lista de comprobación de arriba.
2. **Bucle continuo** (objetivo 7): cola por rol; al terminar, el agente coge la siguiente tarea; topes de tiempo,
   gasto y ventana de 5 h; botón Parar. Diseño en DISENO-OFICINA §6.
3. **Límite de tiempo por paso en la GUI** (la API ya acepta `timeout_s` por agente; falta por paso/conversación).
4. Pendientes del diseño: diario de la misión, `ask_human`, interrumpida → Reanudar, varias misiones por proyecto
   (hoy: una tarea/plan por repo a la vez), métricas del resumen mensual.
5. **Atlas «Analizar proyecto»** (objetivo 9) y después la **oficina 3D** (objetivo 10), ya con todo lo anterior.

### Detalle de lo hecho (notas técnicas)
Lucas cambia el enfoque: Claude con un **manual** (`manual/director.md`, editable) y un **catálogo** decide el equipo,
en vez de crear agentes a mano. Hecho hoy: manual v1 inyectado en el Director y `local_research` (búsqueda web
DuckDuckGo para el modelo local, MCP). Objetivos nuevos de Lucas: plan editable/aprobable en el Inicio, subagentes
en bucle siempre trabajando y ver su tarea, pensamiento y tok/s. Empezar con pocas skills y roles.
**Probar en el PC de Lucas:** un agente con «Puede delegar en el modelo local» y una petición que necesite
internet (p. ej. «¿qué versión de X…?»): debe salir «🦙 Modelo local investigó en la web…» en el chat.
**Agente local con herramientas (objetivo 8, v1):** proveedor `local_agent` (`localharness/adapters/local_agent.py`).
Probar: `sandbox` crea `qwen-agente`; arrancar Qwen3.5-9B y pedirle en el chat algo que necesite leer el repo e
internet. Si no usa herramientas, en el agente poner `tool_mode: json`. Diseño completo en `docs/DISENO-OFICINA.md`.
Ya tiene `ejecutar` (lista blanca `DEFAULT_COMMANDS`, ampliable con `commands` en la config; sin shell; 120 s) y
`preguntar_director` (dentro de un plan con Director de Claude: reanuda su sesión, máx. 3 preguntas, tope 0,2 $;
el coste se suma a la tarea). Ojo: `ejecutar` NO aísla la red (los tests podrían usarla).
**Plan editable (objetivo 3, v1):** Ajustes `plans.always_review` (por defecto sí): todo plan te espera. En
Planes → plan: editar paso (título, instrucciones, agente, riesgo), quitar, reordenar, «Pedir al Director que lo
rehaga» (reanuda su sesión con tu comentario) y «Aprobar todo y ejecutar». API: `PUT /api/plans/{id}`,
`POST /api/plans/{id}/redo`. Probado en navegador con la CLI falsa.
**Ver a los subagentes (objetivo 4, v1):** eventos `thinking` (bloques de pensamiento de Claude; razonamiento de
los modelos locales al terminar) y `thinking_live` (efímero, cada 1,5 s mientras un modelo local razona). En el
Inicio, «💭 pensando ahora» en la tarjeta del agente (clic = completo); en el chat, plegado.
**Roles (objetivo 5, v1):** `roles/*.md` → agentes `explorador` (local_agent, solo lectura), `programador-local`
(local_agent), `programador` (Claude Sonnet, delega en local), `revisor` (Claude Haiku, jefe). Se crean/actualizan al
arrancar el servidor y al planificar (`config.from_role`; el archivo manda; un agente tuyo con el mismo nombre no se
toca). `GET /api/roles`. Las pruebas los apagan con `LOCALHARNESS_ROLES_DIR=""` (tests/__init__.py).
**Pensamiento activable (DISENO-OFICINA §5, v1):** niveles apagado / normal / profundo. Claude: `--effort low|high`
(+ `MAX_THINKING_TOKENS=0` al apagar; según la doc, algunos modelos nuevos no lo apagan del todo). Locales
(llama-server con `--jinja`): `chat_template_kwargs.enable_thinking`. «normal» no añade nada. Se fija por agente
(Ajustes), por rol (`thinking:` en roles/*.md; explorador = apagado), por paso del plan (el Director puede marcarlo;
lo cambias al editar) y por conversación (selector en el chat). **Por verificar en tu PC:** que tu CLI acepta
`--effort` y que Qwen3 obedece `enable_thinking`.
Siguiente: bucle continuo (objetivo 7) y límite de tiempo por paso en la GUI.


## SESIÓN ANTERIOR (06/10/2026, mediodía)

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
.venv/Scripts/python -m unittest discover -s tests -t .                       # 111 pruebas, NUNCA llaman a Claude real
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
   agente del Inicio y la última velocidad en Modelos locales (`api.Runner.last_speed`, también en `/api/health`).
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
