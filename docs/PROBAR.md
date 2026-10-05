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
