# Plan: sacar todo el rendimiento a las dos GPU y a los modelos locales (08/10/2026)

Objetivo: que los modelos locales hagan más trabajo, más rápido y mejor, y que Claude solo audite. Hardware: RTX 3060
12 GB (`CUDA0`) + GTX 1060 6 GB (`CUDA1`, con ~3 GB ocupados por los monitores). Cada parche es pequeño, lleva sus
pruebas (con llama-server falso, como siempre) y un criterio de aceptación que Lucas comprueba en su PC.

Lo que ya hay y se aprovecha: `llama.OPTION_FLAGS` ya traduce `device`, `split_mode`, `tensor_split` y `main_gpu`;
`llama.list_devices()` da la VRAM libre de cada GPU; `describe()` ya detecta `mmproj` (visión); `mcp_local` reparte
por cola (`claim`/`release`) y `LlamaManager` mide tiempos de carga.

## Estado (08/10/2026, tarde) — qué está hecho

Hecho con pruebas (llama-server falso, 256 pruebas en verde); lo que necesita GPU lo prueba Lucas en su PC.

| Parche | Estado | Dónde | Qué falta probar en el PC |
|---|---|---|---|
| P0 «hace 20714 días» | ✅ | ModelsView (segundos → ms), `ago()` | — |
| P1 Armario de modelos | ✅ | `profiles.py`, `GET/PUT /api/llama/profiles`, tarjeta «Armario de modelos» | que las capacidades deducidas cuadren con tus GGUF |
| P2 Cambio en caliente | ✅ | `local_servers.swap`, `POST /api/llama/swap` y `/use`, MCP `local_models`/`local_use` | cambiar el Rápido a otro modelo con una tarea en marcha |
| P3 Modo unido | ✅ | `local_servers.set_topology`, `POST /api/llama/topology`, botón «Unir las GPU» | un modelo de ~14 GB repartido; ver VRAM de cada GPU |
| P4 Banco de pruebas | ✅ | `bench.py`, `POST /api/llama/bench`, `lh llama bench`, tabla en el armario | medir 14B sola vs unida |
| P5 Especulativa | ✅ (arranque) | perfil `draft` → `-md -ngld -devd --draft-max/min`; `spec_type` (MTP); aviso de tokenizador | 14B + 0.5B de borrador en la 1060: ¿sube el tok/s? |
| P6 Caché de prompts | ✅ | `cache_prompt` en cada encargo; opción `cache_reuse` | — |
| P7 Modelo según la fase | ⚠️ parcial | `local_use` por capacidad; falta agrupar «planificar todo → cambiar una vez a programar» | — |
| P8 Planificador local | ✅ | MCP `local_plan` (mapa + JSON validado + reintento; `execute`) | un parche de plantilla planificado por el local |
| P9 JSON garantizado | ✅ | `complete(schema=…)` → `response_format: json_schema` (plan); `local_agent` en modo json ya lo usaba | — |
| P10 Buscar/reemplazar | ✅ | `edits.py`, `local_edit_file`, bloques `edit`, `editar_archivo` en `local_agent` | — |
| P11 Mapa del repo | ✅ | `repomap.py`, MCP `local_map` | — |
| P12 RAG | ✅ | `rag.py`, MCP `local_search` (solo con `llama.embed_url`) | arrancar Qwen3-Embedding con `--embeddings` y poner su URL |
| P13 Presupuesto de contexto | ✅ | `input_budget()` desde `/props` → `n_ctx` | — |
| P14 Documentos | ✅ | `vision.py`, MCP `local_read_documents` (pypdf/pypdfium2 opcionales) | PDF escaneado con Qwen3.5 + mmproj |
| P15 Revisión visual | ✅ | MCP `local_look` (Chrome headless, escritorio y móvil) | una página de poeta con el 4B con visión |
| P16 Gestor de turnos | ⚠️ parcial | `llama.auto_swap`: carga solo un modelo con visión cuando hace falta; `pick` elige perfil/servidor | decidir topología sola con los datos del banco |
| P17 Verlo en la oficina | ⚠️ parcial | armario en Modelos locales (cargado en, cambiando…, banco); falta en la oficina 3D | — |

Además, con los datos del autopiloto del 08/10: arreglo automático a 1 ronda y solo si el error nombra un archivo del
plan, `local_agent` se para si no escribe en 8 pasos o repite llamadas, y el autopiloto pide cerrar un parche que se
queda sin tiempo en vez de tirarlo.

## Mapa de fases

| Fase | Parches | Qué consigue |
|---|---|---|
| 0. Base | P0–P2 | Saber qué modelos hay y para qué sirve cada uno, y poder cambiar de modelo en caliente |
| 1. Rendimiento GPU | P3–P6 | Modo unido (`--tensor-split`), banco de pruebas, decodificación especulativa, caché de prompts |
| 2. Modelo según la fase | P7–P9 | Planificador local (~20B) → cambio a programador; plan en subtareas pequeñas; JSON garantizado |
| 3. Editar y contexto | P10–P13 | Edición por buscar/reemplazar; mapa del repo; RAG con embeddings; presupuesto de contexto |
| 4. Otras tareas | P14–P15 | Leer PDF/OCR/imágenes con un modelo de visión; revisión visual de la web |
| 5. Gestor de turnos | P16–P17 | El sistema decide solo topología y modelos según la cola; verlo en la oficina |

---

## Fase 0 — Base

### P0. Bug «hace 20714 días» (calentamiento)
Modelos locales → «Velocidad de la última respuesta» con fecha 0. No pintar la fecha si `ts` es 0/None.
*Aceptación*: sin respuesta previa sale «—».

### P1. Armario de modelos (perfiles)
Un **perfil** = GGUF + lo que sabe hacer + cómo arrancarlo.
- Capacidades: `plan`, `code`, `review`, `vision` (tiene `mmproj`), `ocr`, `embed`, `draft` (sirve de borrador),
  `tools`, `thinking`. Se deducen de `model_catalog.json` (`match`, `tags`, `roles`), de los metadatos GGUF
  (`gguf.py`: arquitectura, `pooling_type` → embeddings) y de `mmproj`; Lucas puede corregirlas a mano.
- Lanzamiento: `ctx`, `ngl`, caché KV, muestreo, `n_cpu_moe`, topología admitida (`sola` en CUDA0/CUDA1 o `unida`),
  VRAM estimada (ya hay estimador) y tiempo de carga medido.
- Guardado en `settings.llama.profiles`; API `GET/PUT /api/llama/profiles`; tarjeta por perfil en Modelos locales.
*Aceptación*: la pestaña lista cada GGUF con sus capacidades y en qué GPU cabe.

### P2. Cambio de modelo en caliente
- `local_servers.swap(store, pool, srv, perfil)`: espera a que el servidor no tenga encargos (contador de
  `claim`/`release`), lo para, arranca el perfil, espera `health == ok`; candado por servidor; si falla, vuelve al
  anterior.
- Herramientas MCP nuevas: `local_models` (qué hay cargado en cada servidor y qué perfiles hay, con capacidades y
  segundos de carga) y `local_use` (pide una capacidad: «necesito `vision`» → elige perfil y servidor, cambia si hace
  falta y devuelve cuál quedó). Claude y el planificador local piden **capacidades**, no nombres de archivo.
- Evaluar como alternativa el *router mode* de llama-server (carga el modelo según el campo `model` de la petición)
  si la build de Lucas lo trae; si va bien, P2 se apoya en él en vez de parar y arrancar.
*Aceptación*: desde el chat, «lee esta imagen» cambia el Rápido a un modelo de visión, responde y lo deja anotado.

## Fase 1 — Rendimiento GPU

### P3. Modo unido (`--tensor-split`)
- Ajuste `llama.topology`: `separado` (un servidor por GPU, lo de ahora) o `unido` (un solo servidor con
  `-dev CUDA0,CUDA1 -sm layer -ts A,B -mg 0`; el otro servidor se apaga y el reparto de `mcp_local` lo sabe).
- `-ts` automático según la VRAM **libre** de cada GPU (`list_devices`), dejando margen; editable.
- Botón «Unir las GPU / Separarlas» en Modelos locales (usa P2 para el cambio).
- **Regla honesta**: la 1060 tiene la mitad de ancho de banda que la 3060. Con `-sm layer` un modelo que ya cabe
  en la 3060 irá **más lento** unido. El modo unido es para modelos que no caben en 12 GB (p. ej. un ~20B denso,
  gpt-oss-20b con contexto largo o Qwen3-Coder-30B-A3B). P4 lo mide en lugar de suponerlo.
*Aceptación*: un modelo de ~15 GB arranca repartido y la GUI muestra cuánto va en cada GPU.

### P4. Banco de pruebas
`lh llama bench` y un botón: para cada perfil y topología, una petición fija (procesar prompt de ~4k tokens y generar
~512) y se guardan tok/s de lectura y escritura, VRAM y tiempo de carga. Alimenta P3, P5 y P16 con números reales.
*Aceptación*: tabla «perfil × topología → tok/s» en la pestaña.

### P5. Decodificación especulativa
Perfil con modelo borrador (`-md`, `-ngld`, `-devd`, `--draft-max/--draft-min`). Combinación prometedora: el
programador en la 3060 y un borrador de la misma familia (p. ej. Qwen2.5-Coder-0.5B/1.5B para Qwen2.5-Coder-14B) en
la 1060 (`-devd CUDA1`). Tiene que compartir tokenizador; P1 avisa si no. Además, **MTP**: los GGUF «-MTP» de
Qwen3.6 traen su propio borrador (`--spec-type draft-mtp`, 1,4–2,2× según unsloth): el perfil debe admitirlo.
*Aceptación*: P4 muestra la mejora de tok/s en código (lo normal es 1,5–2,5×; medir).

### P6. Caché de prompts y ranuras
Muchos bloques de un plan comparten el mismo prompt de sistema y los mismos archivos. `cache_prompt: true` en cada
petición, `--cache-reuse` y, con `-np 2`, enviar los bloques del mismo grupo de archivos a la misma ranura
(`id_slot`). Valores por defecto sensatos por GPU: `-fa on`, caché KV `q8_0` en la 1060.
*Aceptación*: en un plan de 6 bloques sobre los mismos archivos, el tiempo de leer el prompt baja de forma visible
(se ve en los tiempos que ya devuelve llama-server).

## Fase 2 — El modelo adecuado para cada fase

### P7. Fases con perfil: planificar → programar → revisar
Ajuste `phases`: qué capacidad o perfil usa cada fase y en qué topología (p. ej. plan = un ~20B razonador en
unido; código = programador en la 3060 + rápido en la 1060; revisión = el que esté libre). Para no cambiar de modelo
a cada rato, **se agrupa**: primero se planifica todo lo pendiente, después se cambia una sola vez a programar.

### P8. Planificador local con subtareas pequeñas (escalado inverso)
- Herramienta `local_plan` y modo del autopiloto «planifica el local»: el planificador descompone cada parche en
  **subtareas pequeñas** (un archivo o una edición, criterio de aceptación y `after`) con el mismo formato que
  `local_execute_plan`.
- Validación determinista del plan (rutas dentro del repo, ids únicos, `after` sin ciclos; reutiliza
  `validate_plan`/`tests_after_code`).
- Claude solo entra si: el plan no valida dos veces, los tests fallan tras el arreglo automático o el diff final
  sale N2. Opción «Claude aprueba el plan»: revisar un plan cuesta mucho menos que escribirlo.
*Aceptación*: en «poeta», un parche de plantilla sale sin llamar a Claude; el informe lo dice.

### P9. JSON garantizado
`response_format`/`json_schema` de llama-server en el plan local, en el modo `json` de `local_agent` y en cualquier
respuesta estructurada. Se acaban los planes rotos y el agente atascado por mal formato.

## Fase 3 — Editar archivos y ajustar el contexto

### P10. Edición por buscar/reemplazar
- Bloque nuevo `kind: "edit"` en `local_execute_plan`, herramienta `local_edit_file` y `editar_archivo` en
  `local_agent`. Formato: varios pares BUSCAR/REEMPLAZAR.
- Aplicación: coincidencia exacta → coincidencia ignorando espacios → si no, error con las líneas más parecidas para
  que el modelo reintente (una vez).
- Las guías de Claude y del planificador prefieren `edit` cuando el archivo existe y el cambio es pequeño.
*Aceptación*: en «poeta», `styles.css` deja de reescribirse entero; menos tokens por parche en el informe.

### P11. Mapa del repo
Por archivo, su esquema (funciones/clases de Python con `ast`, selectores de CSS, ids/secciones de HTML, exports de
JS por regex), en caché por hash. Se inyecta el mapa en vez de archivos enteros cuando no caben, y es lo primero que
lee el planificador. Sustituye la idea de `MAPA.md`.

### P12. RAG con embeddings
Perfil `embed` (p. ej. Qwen3-Embedding-0.6B o nomic-embed) en CPU o en la 1060 con `--embeddings`. Trozos por
función/sección (usa P11), vectores en SQLite, coseno en Python (repos pequeños: sin dependencias). Cada bloque
recibe sus archivos + los k trozos más relevantes.

### P13. Presupuesto de contexto
`max_input` sale del contexto real del modelo cargado (`/props` → `n_ctx`) menos la reserva de salida, no de un
número fijo. Prioridad al llenar: instrucciones > archivo a editar > tests relacionados > trozos RAG > mapa. El
evento `context` registra qué entró y qué se recortó; se ve en el chat. Ajustable por perfil.

## Fase 4 — Más allá del código

### P14. Documentos: PDF, OCR e imágenes
Herramienta `local_read_documents(paths, pregunta)`: PDF con texto → extracción directa (`pypdf`); escaneado o
imagen → páginas a imagen (`pypdfium2`) y modelo de visión (Qwen2.5-VL/Qwen3-VL con su `mmproj`, vía P2). Varios
documentos → resumen por documento y luego uno conjunto (map-reduce). Sirve también fuera de la programación
(apuntes, enunciados).

### P15. Revisión visual de la web
Playwright saca capturas de cada parche (escritorio y móvil) y el modelo de visión responde «¿se parece a lo pedido?
¿hay algo roto?». Entra en `run_checks` como comprobación opcional y en el autopiloto. Ataca lo más flojo de «poeta».

## Fase 5 — Que el sistema decida solo

### P16. Gestor de turnos de GPU
Mira la cola (bloques pendientes por capacidad y tamaño) y los números de P4 y decide: separado o unido, qué perfil
en cada servidor y cuándo cambiar. Agrupa trabajo por perfil para cambiar lo mínimo y no cambia si el ahorro
estimado es menor que el tiempo de carga. Con modo manual siempre disponible.

### P17. Verlo en la oficina
En la oficina y en Modelos locales: qué perfil hay en cada GPU, «cambiando de modelo…» con su progreso, la cola por
capacidad y si están unidas o separadas.

---

## Orden de trabajo propuesto

| Sesión | Parches | Por qué en este orden |
|---|---|---|
| Esta tarde | P0, P1, P2, P3, P4 | Todo lo demás se apoya en perfiles y cambio de modelo; el modo unido y el banco dan números desde el primer día |
| Siguiente | P10, P9, P6, P5 | Editar archivos y JSON garantizado son la mayor ganancia de calidad; caché y borrador, de velocidad |
| Después | P7, P8, P13, P11 | Planificador local con subtareas, sobre perfiles, edición y contexto ya hechos |
| Luego | P12, P14, P15 | RAG, documentos y visión |
| Al final | P16, P17 | Automatizar las decisiones cuando ya hay datos de P4 y del autopiloto |

## Modelos candidatos
Lista completa, por GPU y con la batería de pruebas: `docs/MODELOS-A-PROBAR.md`. Resumen:
- **Planificar** (~20B, modo unido): gpt-oss-20b; o un Qwen3 razonador de tamaño parecido.
- **Programar**: Qwen2.5-Coder-14B (3060 sola, ya probado ~28 tok/s); Qwen3-Coder-30B-A3B en unido con
  `n_cpu_moe` si P4 dice que compensa.
- **Rápido / borrador**: Qwen3.5-4B (ya probado); Qwen2.5-Coder-0.5B/1.5B como borrador del 14B.
- **Visión/OCR** (1060): Qwen2.5-VL-7B o Qwen3-VL-4B, con su `mmproj`.
- **Embeddings**: Qwen3-Embedding-0.6B o nomic-embed-text (CPU vale).

## Qué se prueba en el PC de Lucas en cada parche
Aquí no hay GPU: cada parche llega con pruebas de llama-server falso. En el PC: P3/P4/P5 con `lh llama bench`; P2 y
P14 con un modelo de visión real; P8 y P10 con un autopiloto corto en «poeta» y su informe comparado con el del
08/10 (coste, tokens, rondas de arreglo, tiempo).
