# Modelos locales a probar (08/10/2026)

Lista para probar estos días y decidir qué modelos se quedan en LocalHarness. Hardware: RTX 3060 12 GB (`CUDA0`) +
GTX 1060 6 GB (`CUDA1`, con ~3 GB ocupados por los monitores: **libres ~2,9 GB**).

**Ojo**: los tamaños y las puntuaciones salen de fichas de modelo y artículos (Hugging Face no era accesible desde la
sesión en la nube donde se escribió esto). Columna «Fuente»: **oficial** = anuncio o ficha del fabricante;
**blogs** = solo artículos de terceros, comprobar el repo antes de descargar. Las puntuaciones de los fabricantes
no son independientes: lo que manda es nuestra batería de pruebas (abajo).

## Antes de empezar: libera la 1060
Con 2,9 GB libres en la 1060 solo caben modelos de ~2 GB. Si los monitores van a la 3060 (o a la gráfica integrada,
si tu CPU tiene), la 1060 queda con ~5,5 GB y entra un 9B en Q4 (visión/OCR, borrador, segundo trabajador). Merece
la pena probar las dos configuraciones.

¿Cuánta RAM tiene el PC? Los MoE del grupo D necesitan **32 GB o más** para dejar expertos en RAM (`n_cpu_moe`).

---

## A. Caben en la 3060 sola (programar y agente; el «Fuerte»)

| Modelo | Tamaño Q4 aprox. | Por qué probarlo | Fuente |
|---|---|---|---|
| **Qwen3.5-9B** | ~5,7 GB (Q4_K_M) · Q8 ~9,5 GB | Ya lo tienes; el único que devolvía `tool_calls` bien en las pruebas. Multimodal (visión/OCR con su mmproj). Con la 3060 sola cabe en Q8: probar Q8 frente a Q4 | oficial |
| **Gemma 4 12B** (QAT Q4_0) | ~7–8 GB con 16k de contexto | Function calling nativo, multimodal, 128k de contexto. Candidato fuerte a «agente que no se atasca» | oficial (modelo) · blogs (GGUF de unsloth) |
| **Qwen2.5-Coder-14B** | ~9 GB | **Referencia**: es el que usó el autopiloto del 08/10 (~28 tok/s). Todo se compara contra él | ya probado |
| Qwen3-14B | ~9 GB | Razonador con herramientas; posible planificador barato sin unir GPU | ya en el catálogo |

## B. Para la 1060 (el «Rápido», borradores, utilidades)

| Modelo | Tamaño | Uso | Fuente |
|---|---|---|---|
| **Qwen3.5-4B** | ~2,7 GB | Ya lo tienes (~25 tok/s). Rápido, multimodal; OCR casi tan bueno como el 9B según pruebas de la comunidad | oficial |
| **Qwen3.5-0.8B / 2B** | <1,5 GB | **Borrador** para decodificación especulativa del Qwen3.5-9B (mismo tokenizador) y clasificar/resumir al instante | oficial |
| **Gemma 4 E4B / E2B** | ~3 / ~1,5 GB | Pequeños con function calling; alternativa al 4B de Qwen | oficial |
| **Qwen3-Embedding-0.6B** (Q8_0) | ~0,6 GB | Embeddings para el RAG (P12). Puede ir en CPU | oficial (modelo) |

## C. Uniendo las dos GPU (`--tensor-split`, ~14–15 GB útiles) — planificar / tareas difíciles

| Modelo | Tamaño | Por qué probarlo | Fuente |
|---|---|---|---|
| **gpt-oss-20b** | ~12–13 GB (MXFP4) | Razonador con herramientas; **candidato principal a planificador** (fase «plan» del P7) | oficial; ya en el catálogo |
| **Devstral Small 2 24B** (2512) | ~13–14 GB (IQ4_XS/Q4) | Hecho para agentes de código: 68 % en SWE-bench Verified (Mistral), Apache 2.0, 256k | oficial |
| **Qwen3.6-27B** (IQ3/Q3) | ~12–13 GB en 3 bits (Q4 ~16,5 GB no cabe) | 77,2 % SWE-bench Verified según Qwen: el mejor denso de su tamaño. En 3 bits pierde algo: medir | oficial |
| **Qwen3.8-27B** (IQ3/Q3) | igual que el anterior (Q4 ~15,9 GiB + 0,9 visión) | El más reciente (14/08/2026). 61,7 % SWE-bench Pro según Alibaba. Si la 1060 queda libre, quizá un Q4 justo | blogs |

## D. MoE con expertos en RAM (`n_cpu_moe`; necesitan RAM)
Solo ~3–4 B parámetros activos por token: aunque parte vaya en RAM siguen siendo usables. Probar en modo unido y en
la 3060 sola con `n_cpu_moe`.

| Modelo | Tamaño Q4 | Por qué probarlo | Fuente |
|---|---|---|---|
| **Qwen3.6-35B-A3B** (variante **MTP**) | ~20–22 GB | 73,4 % SWE-bench Verified según Qwen; la variante MTP de unsloth da 1,4–2,2× más velocidad en llama.cpp (`--spec-type draft-mtp`, ~2 GB extra) | oficial (modelo) · unsloth (MTP) |
| **Qwen3-Coder-30B-A3B** | ~18,6 GB | Ya en el catálogo; especialista en agentes de código | oficial |
| **Gemma 4 26B A4B** | ~14,4 GB (QAT Q4_0) / ~17 GB (Q4_K_M) | El QAT podría caber casi entero unido; resultados de código contradictorios en blogs: medir | oficial (modelo) |
| GLM-4.7-Flash (30B-A3B) | ~16 GB | 59,2 % SWE-bench Verified según Z.ai; **comprobar que hay GGUF y soporte en llama.cpp** | oficial (modelo) · GGUF sin confirmar |
| Nemotron 3 Nano (30B-A3B) | ~18 GB | NVIDIA, orientado a agentes, 262k de contexto; **comprobar GGUF** | oficial (modelo) · GGUF sin confirmar |

## E. Visión, OCR y documentos (P14/P15)
- **Qwen3.5-4B** (1060) y **Qwen3.5-9B** (3060): multimodales nativos; según pruebas de la comunidad, el 9B es el
  mejor equilibrio para OCR (~3 s por página) y el 4B se le acerca. Necesitan su `mmproj` del mismo tamaño.
- **Gemma 4 12B**: multimodal; para comparar con Qwen en capturas de webs.

## Descartados por tamaño
- Qwen3-Coder-Next (80B-A3B): ~46 GB en 4 bits. No cabe ni con RAM normal.
- Familias grandes (Qwen3.8-Max, Kimi, GLM-5, DeepSeek-V4…): no son para este PC.
- Nombres que solo aparecen en un blog (Ornith, Mellum 2, MiMo-Distill…): no entran hasta encontrar su repo.

---

## Cómo probarlos (la misma batería para todos)
Para que la comparación sea justa: mismo contexto (16k), mismo muestreo recomendado por la ficha y mismas tareas.

1. **Arranque**: VRAM usada en cada GPU, tiempo de carga, tok/s de lectura y escritura (`lh llama bench` cuando
   exista el P4; hasta entonces, los números de la pestaña Modelos locales).
2. **Herramientas**: `lh probar-delegacion` → ¿acaba en ✔? ¿devuelve `tool_calls` o hace falta `tool_mode: json`?
3. **Escribir código**: 3 parches cortos de `poeta` con el autopiloto (lista de prueba fija) → tests a la primera,
   rondas de arreglo, tokens.
4. **Agente**: una tarea con `local_agent` (ej.: «añade un test y haz que pase») → ¿acaba o se atasca releyendo?
5. **Planificar** (solo grupos C/D): pedirle un plan en bloques con `after` para un parche → ¿JSON válido? ¿bloques
   pequeños y sensatos? Claude puntúa el plan del 0 al 10.
6. **Visión** (grupo E): 3 capturas de `poeta` + 2 páginas de PDF escaneado → ¿describe bien? ¿transcribe bien?

### Hoja de resultados (rellenar)

| Modelo · cuant | Dónde | VRAM | Carga (s) | tok/s | Herramientas | Tests a la 1.ª | Agente acaba | Plan (0–10) | Visión | Nota |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen2.5-Coder-14B Q4_K_M | 3060 | | | ~28 | | | | — | — | referencia |
| | | | | | | | | | | |

Con esta hoja se rellenan los perfiles del P1 (capacidades y en qué GPU va cada modelo) y se elige el equipo por
defecto: planificador, programador, rápido, visión y embeddings.

## Fuentes
- Qwen3.6-35B-A3B y Qwen3.6-27B: blog de Qwen (qwen.ai/blog?id=qwen3.6-35b-a3b, ?id=qwen3.6-27b).
- Qwen3.5 (fechas y tamaños): anuncio de Qwen en X y Wikipedia «Qwen».
- MTP en llama.cpp: documentación de unsloth (unsloth.ai/docs/models/mtp).
- Qwen3.8-27B: datanorth.ai, letsdatascience.com (cifras de Alibaba).
- Gemma 4: ai.google.dev/gemma/docs/releases y /core.
- Devstral Small 2: mistral.ai/news/devstral-2-vibe-cli.
- GLM-4.7-Flash: huggingface.co/zai-org/GLM-4.7-Flash. Nemotron 3 Nano: openrouter.ai/nvidia/nemotron-3-nano-30b-a3b.
- Qwen3-Coder-Next: huggingface.co/Qwen/Qwen3-Coder-Next-GGUF, unsloth.ai/docs/models/qwen3-coder-next.
- OCR con Qwen3.5: martinalderson.com/posts/how-to-use-qwen-3-5-to-ocr-documents.
- Qwen3-Embedding: huggingface.co/Qwen/Qwen3-Embedding-8B-GGUF (instrucciones de llama.cpp).
