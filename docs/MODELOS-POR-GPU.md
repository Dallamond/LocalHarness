# Modelos candidatos por GPU (09/10/2026) — para cuando llegue la M40

Lista que trajo Lucas el 09/10/2026 para las pruebas intensivas con tres GPU: GTX 1060 6 GB, RTX 3060 12 GB y Tesla
M40 24 GB. **Las puntuaciones y velocidades son ESTIMADAS** (una hipótesis para elegir qué probar, no un benchmark
común). «Tu nota» = la que dieron nuestras pruebas. Lo que mide LocalHarness (el banco, `/banco`, y las notas de
abajo) manda sobre esta tabla. Ver también [MODELOS-A-PROBAR.md](MODELOS-A-PROBAR.md) (lista del 08/10).

## Medido ya en LocalHarness (contrasta con la estimación)

| Modelo | GPU | Medido | Estimación de la lista |
|---|---|---|---|
| gpt-oss-20b UD-Q4_K_XL, `n_cpu_moe 4` | 3060 sola | **~45–50 tok/s** (08/10; 35–45 en los encargos del banco) | 3–9 tok/s |
| Qwen3.5-9B Q4_K_M | 3060 | **~46 tok/s** (banco del 09/10) | 18–35 tok/s |
| Qwen3.5-4B Q4_K_M | 1060 | **~25 tok/s**; 40 encargos y 0 fallos con Claude dirigiendo | 15–30 tok/s |

- **M40, banco `basico` con el Jefe local 2 (21/10, nota media del examen oculto, ruido ~17 puntos con n=1):**
  Qwen3.5-35B-A3B solo en la M40 **96,1 %** (22 casos, 20 al 100: el mejor con diferencia); gpt-oss-20b
  solo 80,0 y 70,2 % (dos tiradas), con `diag-alto` 87,6 %, con `plan-medio` 79,2 %; gpt-oss + Coder-14B (3060) 81,1 % por `cola`
  y 81,7 % por `dividir`; gpt-oss + Qwen3.5-9B por `dividir` 76,7 %. El reparto `dividir` no mejora a `cola`. Detalle en
  [ESTADO.md](ESTADO.md).
- Los Qwen3.5 razonan sin tope si su servidor está en «normal»: el `effort` del jefe solo lo entiende gpt-oss. En
  el banco, `pensamiento: apagado` (o un tope por papel en `cerebro.ROLES`).
- gpt-oss necesita `reasoning_effort` bajo o entra en bucle.
- Dos modelos a la vez en GPUs unidas se pisaron la VRAM y bajaron a 4–7 tok/s: un modelo por GPU.

## GTX 1060 6 GB — el «Rápido»
Modelos pequeños que quepan enteros, con contexto contenido. Los grandes van a la M40.

| # | Modelo y GGUF a buscar | Puntuación estimada | Velocidad estimada |
|---|---|---|---|
| 1 | Qwen3.5-4B — Q4_K_M | 76/100 — tu nota: 76 | 15–30 tok/s |
| 2 | Gemma 4 E4B IT — Q4_K_M | 74/100 | 15–30 tok/s |
| 3 | Qwen3-4B-Instruct-2507 — Q4_K_M (tienes Q8_0) | 73/100 — tu nota Q8: 83 | 12–25 tok/s |
| 4 | Qwen2.5-Coder-3B-Instruct — Q4_K_M | 71/100 | 18–35 tok/s |
| 5 | Phi-4-mini-instruct — Q4_K_M | 69/100 | 15–30 tok/s |
| 6 | Qwen2.5-Coder-7B-Instruct — Q3_K_M | 68/100 | 6–14 tok/s |
| 7 | Qwen3.5-4B — Q5_K_M | 76/100 | 10–22 tok/s |
| 8 | Gemma 4 E4B IT — Q5_K_M | 74/100 | 9–20 tok/s |
| 9 | Qwen2.5-Coder-7B-Instruct — Q4_K_M, probablemente con offload parcial | 68/100 | 4–10 tok/s |
| 10 | Llama 3.1 8B Instruct — Q3_K_M | 65/100 | 4–10 tok/s |

Los puestos 7–10 son para experimentar: las cuantizaciones más bajas o el offload parcial pueden bajar bastante la
calidad y la velocidad. Un 7B/8B no debería ser jefe en la 1060 si puede ir en la M40.

## RTX 3060 12 GB — el «Fuerte» (escribir código)
Los 7B–14B que quepan con margen para el contexto. Los de 20B+ arrancan con parte en RAM/CPU.

| # | Modelo y GGUF a buscar | Puntuación estimada | Velocidad estimada |
|---|---|---|---|
| 1 | Qwen3.5-9B — Q4_K_M | 84/100 — tu nota: 84 | 18–35 tok/s |
| 2 | Gemma 4 12B IT — Q4 (tienes Q6) | 80/100 | 10–22 tok/s |
| 3 | Qwen2.5-Coder-14B-Instruct — Q4_K_M, KV Q8 y contexto moderado | 78/100 — tu nota: 74 | 6–14 tok/s |
| 4 | Qwen2.5-Coder-7B-Instruct — Q8_0 (lo tienes) | 75/100 | 15–28 tok/s |
| 5 | DeepSeek-R1-Distill-Qwen-14B — Q4_K_M | 74/100 — tu nota: 74 | 6–14 tok/s |
| 6 | Ministral 3 14B Reasoning — Q4_K_M | 74/100 | 6–14 tok/s |
| 7 | Qwen3.5-9B — Q5_K_M | 84/100 | 14–28 tok/s |
| 8 | Llama 3.1 8B Instruct — Q5_K_M | 69/100 — tu nota: 82 | 17–30 tok/s |
| 9 | GPT-OSS-20B — Q4, con parte en CPU | 80/100 — tu nota: 77 | 3–9 tok/s (medido: ~45–50) |
| 10 | Devstral Small 2507 — tu IQ2_M, con offload según la memoria | 78/100 — tu nota: 79 | 4–12 tok/s |

El orden entre Qwen3.5-9B, Gemma 4 12B y Qwen2.5-Coder-14B es una hipótesis: la evidencia propia de LocalHarness va
por delante.

## Tesla M40 24 GB — el «cerebro» (diagnosticar, planificar, revisar)
La tarjeta para los modelos que más pueden subir la capacidad del jefe local. Es Maxwell (sm_52), sin Tensor Cores:
un modelo grande no tiene por qué ser rápido, y un GGUF de 17–19 GB deja poco sitio a la caché y al contexto. En el
cerebro 2 encaja en los papeles que **leen mucho y escriben poco** (diagnosticar, planificar, revisar): ahí la
velocidad de generación importa menos. llama.cpp tiene que ir con CUDA 12.x (CUDA 13 ya no soporta Maxwell).

| # | Modelo y GGUF a buscar | Puntuación estimada | Velocidad estimada |
|---|---|---|---|
| 1 | Gemma 4 26B-A4B IT — Q4_K_M, ~16,8 GB | 87/100 | 8–18 tok/s |
| 2 | Qwen3-Coder-30B-A3B-Instruct — IQ4_XS, ~16,4 GB | 86/100 | 8–18 tok/s |
| 3 | Qwen3-Coder-30B-A3B-Instruct — Q4_K_M, ~18,6 GB; contexto limitado | 86/100 | 6–15 tok/s |
| 4 | Qwen3.5-27B — Q3_K_M o IQ3, según tamaño | 85/100 | 4–10 tok/s |
| 5 | Qwen3.5-9B — Q8_0 | 84/100 | 14–28 tok/s |
| 6 | GPT-OSS-20B — Q4; revisar compatibilidad y memoria del backend | 82/100 | 7–16 tok/s |
| 7 | Gemma 4 12B IT — Q6_K | 80/100 — tu nota: 67 | 12–24 tok/s |
| 8 | Devstral Small 2507 — IQ4_XS o Q3_K_M si hay GGUF compatible | 79/100 — tu IQ2_M: 79 | 6–14 tok/s |
| 9 | Qwen2.5-Coder-14B-Instruct — Q5_K_M | 78/100 — tu Q4: 74 | 9–18 tok/s |
| 10 | DeepSeek-R1-Distill-Qwen-14B — Q5_K_M o Q6_K | 75/100 — tu Q4: 74 | 9–18 tok/s |

## Cómo probarlos cuando llegue la M40
1. Un servidor local nuevo para la M40 (Modelos locales → Servidores, `device` CUDA1: sin la 1060, llama.cpp
   numera 3060 = CUDA0, M40 = CUDA1; con la 1060 puesta sería CUDA2) y medir tok/s reales con
   `/api/llama/bench`; apuntarlos arriba en «Medido ya».
2. Elegir el modelo del papel «diagnosticar» con el banco de diagnóstico (fallos reales que arregló Claude: minutos
   por modelo) antes de gastar horas en el banco completo.
3. Contendiente con el Jefe local 2 y `roles` apuntando a la M40, p. ej.
   `"roles": {"diagnosticar": {"servidor": "m40"}, "planificar": {"servidor": "m40"}, "revisar": {"servidor": "m40"}}`,
   y los obreros donde están (gpt-oss o Qwen3.5-9B en la 3060, Qwen3.5-4B en la 1060). Medirlo contra la mejor nota
   local del banco.
