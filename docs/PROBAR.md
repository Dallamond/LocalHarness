# Cómo probar LocalHarness (guía para Lucas)

Todo en PowerShell desde la carpeta `LocalHarness`. `lh` = `.venv\Scripts\python -m localharness`.

## 0. Preparar (una vez, o tras `git pull`)
```powershell
.venv\Scripts\python -m pip install -e .[server]      # si falla porque no existe .venv: py -3.12 -m venv .venv
cd web; npm install; npm run build; cd ..
.venv\Scripts\python -m localharness sandbox          # repo de pruebas en C:\Users\Lucas\LocalHarness-sandbox + agentes
```
`sandbox --reset` lo deja como nuevo cuando quieras repetir una prueba.

Agentes que crea:
| Agente | Qué es | Gasta plan |
|---|---|---|
| `qwen-director`, `qwen-jefe` | tu Qwen local por llama-server | no |
| `qwen-agente` | Qwen local como agente con herramientas e internet (`local_agent`; mejor Qwen3.5-9B) | no |
| `haiku-director`, `haiku-jefe` | Claude Haiku, topes 0,3 $ / 0,2 $ | poco |
| `sonnet-trabajador` | Claude Sonnet, el único que edita archivos (tope 0,5 $) | sí |

## 1. Arrancar (cada vez)
- Terminal 1: `.venv\Scripts\python -m localharness llama serve qwen2.5-coder-7b` (tarda ~4 min en cargar;
  `llama status` dice si ya responde). Solo hace falta para los agentes `qwen-*`.
- Terminal 2: `.venv\Scripts\python -m localharness serve` y abre http://127.0.0.1:8095

## 2. Pruebas (de gratis a con gasto)
**A · Gratis: pregunta al modelo local.** Tareas sueltas → agente `qwen-director`, petición:
«¿Qué fallos ves en este proyecto?». Debería citar `suma`, `divide` y `valor_total`. Estado final: *hecha*.

**B · Plan pequeño (~0,05–0,15 $).** Planes → Director `qwen-director`, jefe `qwen-jefe`, petición:
«Arregla suma en calc.py y añade un test». Mira cómo aparecen las subtareas, quién aprueba cada una y el diff.
Si queda *listo para integrar*: Integrar plan → comprueba en el sandbox `git log` y `py -3.12 -m unittest`.

**C · Plan grande (te tiene que pedir permiso).** Petición: «Arregla los tres fallos del README, añade tests
para todo y documenta cada función en el README». Si el Director lo parte en más de 3 subtareas, el plan se queda
en *espera tu aprobación* y aparece en «Pendiente de ti». Apruébalo o recházalo.

**D · Riesgo alto (debe pararse para ti).** Petición: «Borra tests/test_calc.py y crea requirements.txt con
pytest». Borrar archivos y tocar dependencias es N2: la subtarea debe pararse con sus motivos. Prueba
*Rechazar y seguir* (deshace solo esa subtarea).

**E · Comparar revisores.** Repite B con `haiku-jefe` en vez de `qwen-jefe` y fíjate en si los veredictos difieren.

## 3. Cómo darme feedback
Pega esto rellenado (o una captura) en el chat:
```
Prueba: B
Qué hice: …
Qué esperaba: …
Qué pasó: …           (estado del plan/tarea, mensaje de error, nº de plan)
Molesto / confuso: …  (textos, botones, esperas)
```
Útil también: `lh plan show <n>` y `lh plan inbox` en la terminal, o el `#` del plan que se ve en la web.
Los datos de tus pruebas están en `data/localharness.db` (no se sube a GitHub).

## 4. Novedades de la sesión 3 (06/10/2026) — todo gratis salvo el punto 7
Antes: `cd web; npm run build; cd ..` y reinicia `serve`. Arranca los modelos desde **Modelos locales** (no a mano):
así llevan clave y barra de progreso.
1. **Modelos locales → Arrancar** un modelo que no hayas cargado nunca desde aquí: barra «moviéndose» (sin %) con la
   etapa y 1–2 líneas del log debajo. Párala y vuelve a arrancarla: ahora debe salir **% y «faltan ~X s»**.
2. En la tarjeta de un modelo, **⚙ Arranque de este modelo** → pon contexto 8192 y `-fa on` → Guardar. Debe verse
   «ctx 8192 · -fa on» en la tarjeta y aplicarse al arrancarlo.
3. **Agentes locales → + Crear agente local** (rol jefe): se llama `local-jefe` y dice «usa <modelo arrancado>».
   Si tienes agentes viejos con nombre de modelo (p. ej. DeepSeek) y arrancas otro, deben avisar y ofrecer arrancar el suyo.
4. **Chat** con un agente local: la burbuja «escribiendo…» muestra **pensando/escribiendo · N tok/s · tokens**; la
   cabecera dice qué modelo usa. Con un modelo que razona y pocos tokens debe salir el aviso «se quedó pensando».
5. **Inicio → Te toca a ti**: la tarea #3 (aprobada sin integrar) tiene **Integrar / Descartar**. Pruébalo con una
   tarea del sandbox, no con algo que te importe.
6. **Ajustes → Agentes → Editar** un agente local: temperatura, tokens de respuesta, contexto del repo. Uno Claude:
   casilla «Puede crear subagentes». **Ajustes → Ejecución → Mantenimiento**: «Ver qué borraría».
7. (Gasta plan, solo si quieres) Agente Claude con «Puede crear subagentes» + Haiku y tope 0,2 $, petición:
   «Usa un subagente para listar los archivos .py y resume qué hace cada uno». Si dice que no tiene la herramienta,
   pásame el número de tarea.

## 5. Claude delega en el modelo local
1. Modelos locales → arranca **qwen2.5-coder-7b** (rápido y no se queda pensando).
2. Ajustes → Agentes → edita un agente Claude (mejor Haiku o Sonnet con tope) → marca **Puede delegar en el modelo local**.
3. Chat con ese agente, en el sandbox: «Explícame qué hace cada archivo y escribe tests para calc.py».
   Deberías ver tarjetas verdes «🦙 Modelo local respondió a… / escribió tests/…» y al final
   «N encargos al modelo local · X tokens hechos gratis en local». Compara el coste con una tarea igual sin la casilla.

## 6. Oficina y Catálogo (sesión 4) — gratis
Antes: `git pull`, `.venv\Scripts\python -m pip install -e .[server]` (ya no falla), `cd web; npm install; npm run build; cd ..`
y reinicia `serve`. Abre http://127.0.0.1:8095 (va a la **Oficina**).
1. Al principio solo estás tú: cada agente entra en la oficina cuando le encargas algo (o lo llamas desde «Fuera de
   la oficina», abajo a la izquierda del 3D) y se queda 2 h tras su último trabajo. El rack del modelo local aparece al
   arrancar uno en Modelos locales. Cada puesto: arrastra para girar, rueda para zoom, clic en un puesto o en su placa → inspector.
   La barra de arriba del 3D enfoca cada puesto y el rack del modelo local.
2. **Misión → ＋ Nueva**: proyecto sandbox, un agente local, «¿Qué fallos ves en calc.py?» → Ejecutar. Mira la burbuja
   del muñeco, los pasos, el Timeline y Terminal. Con un modelo arrancado, el rack se enciende.
3. Con una tarea que cambie archivos: la **Bandeja** muestra «Revisar cambios» → «Ver» abre su Diff abajo; Aprobar e
   integrar / Descartar como antes.
4. **Catálogo → Importar → Ejemplos → Servidores MCP → Importar**. Luego Agentes → **Asignar** en un agente Claude:
   marca `fetch` o `internet`. Comprueba que el chip aparece en el inspector. (Ejecutarlo gasta plan: pregunta antes.)
5. **Catálogo → Importar → Skill** (ejemplo) → aparece en Skills como «importada»; asígnala y bórrala.
6. Inspector de un agente → «Instrucción directa»: si tiene una conversación abierta la continúa; si no, crea tarea.
7. Abre una conversación del Chat desde la bandeja o pegando `/chat/<n>` en la barra: antes se quedaba en blanco.
