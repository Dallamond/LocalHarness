# Integrar mejor la Tesla M40 — mejoras futuras (14/10/2026)

Base medida (Qwen3-32B Q4_K_M en la M40 vs Qwen2.5-Coder-14B en la 3060, logs de llama-server):

| | M40 | 3060 |
|---|---|---|
| Generar | 6,5 tok/s | 29 tok/s |
| Leer el prompt | 46–52 tok/s | ~950 tok/s |

El 32B pesa ~19,8 GB: 6,5 tok/s son ~129 GB/s efectivos, el 45 % de los 288 GB/s nominales. Leer el prompt es lo peor
de la M40 (20× más lenta que la 3060, contra 4,5× al generar): es Maxwell, sin Tensor Cores. Hecho el 14/10: el reparto
por cola cuenta las dos velocidades (`Server._job_seconds`), la interfaz nombra cada servidor por modelo + GPU y
«Tus modelos» sube arriba.

## Por impacto (lo que más cambia con menos trabajo primero)

1. **Modelo MoE en la M40** (Qwen3-30B-A3B, Gemma 4 26B-A4B; ver `MODELOS-POR-GPU.md`). gpt-oss-20b ya da ~35 tok/s
   ahí porque solo lee ~3-4B de pesos por token; un denso de 32B da 6,5. Es la mejora más barata: descargar y medir.
2. **Decodificación especulativa con borrador en la 3060**: Qwen3-32B en la M40 y un Qwen3 pequeño (0,6B/1,7B; hay que
   descargarlo, el Qwen3.5-0.8B tiene otro tokenizador) en la 3060 con `-devd CUDA0`. Lo normal es 1,5–2,5× al
   generar. El arranque con borrador ya existe (perfil `draft`, P5): falta medirlo con `lh llama bench`.
3. **Prefijos en caché que no se relean**: a 46 tok/s, releer 10k tokens de repo cuesta ~3,5 min. `--cache-reuse` ya
   está; falta `--slot-save-path` (guardar/restaurar la ranura del prefijo del repo entre encargos y entre reinicios).
4. **Prompts más cortos para la M40**: mapa del repo (P11) y RAG (P12) en vez de archivos enteros. Es lo que más reduce
   su coste real.
5. **Modo unido para el 32B** (M40 + 3060 con `-sm layer -ts`): con parte de las capas en la 3060 la lectura del
   prompt podría ir ~2× más rápida. Cuesta la 3060 entera mientras dure; medir con el banco (P4) antes de usarlo.

## Reparto y flujo

6. **Enrutar por tamaño de prompt, no solo por papel**: a la M40 solo lo de entrada corta y salida corta (revisar un
   diff pequeño, clasificar, elegir archivos con lista). Con el prompt estimado > N tokens, a la 3060.
7. **Solapar fases**: mientras la 3060 escribe el bloque N, la M40 revisa el N-1 (la revisión es consultiva, lee poco).
   Hoy planificar → bloques → revisar es en serie y una GPU espera a la otra.
8. **Calibración persistente**: el reparto aprende las velocidades solo dentro de cada proceso. Guardarlas en `data/`
   (por servidor y modelo) para que cada tarea arranque ya calibrada; y que el estimador del catálogo use el ancho de
   banda *efectivo* de Maxwell (~45 %) en vez del nominal, o la nota de velocidad de la M40 sale inflada.
9. **Gestor de turnos (P16)** con esos datos: cambiar el modelo de la M40 según la fase y la cola.

## Interfaz y vigilancia

10. **Temperatura, reloj y potencia de la M40 en la oficina**: no lleva ventilador propio y baja a 324 MHz en reposo;
    si se calienta se estrangula sin avisar. Alerta de temperatura y, si hace falta, límite de potencia (`nvidia-smi -pl`).
11. **En cada tarjeta de servidor**: tok/s de lectura y de generación medidos, VRAM usada de esa GPU y botón
    «Unir / Separar» (hoy el modo unido está en la API pero se ve poco).
12. **El banco contra el reparto**: un contendiente por topología (separado, unido, dos en la M40) con la misma prueba,
    para decidir con nota y tiempo y no a ojo.

## Otros usos de la M40

13. **Embeddings (RAG) y visión/OCR en la M40**: modelos pequeños que caben junto a otro y liberan la 3060 para código.
14. **Dos modelos en la M40** (contendiente `dos-en-m40`): comparten ancho de banda; medir cuánto se pierde antes de
    darlo por bueno.
