r"""Cola del 22/10 con las dos GPU libres hasta las 14:00 (M40 + 3060): confirmar Qwen3.5-35B-A3B, probarlo como jefe con
obrero en la 3060 y medir los tres arreglos mecánicos nuevos (vallas, exports perdidos, pasada tras la última ronda).

    .venv\Scripts\python.exe scripts\encolar_2gpu.py             # simula
    .venv\Scripts\python.exe scripts\encolar_2gpu.py --aplicar --empezar

Orden y duración estimada (pares ~1 h, solo ~2 h en la M40): suma ~6,5 h; lo último se puede quitar si no llega.
Usa la API (no la CLI) y las reglas de `encolar_manana.py` (idempotente, salta lo que no está descargado)."""
import sys

import encolar_manana as base

BASICO = {"repertorio": "basico"}
base.PLAN[:] = [
    ("par-qwen35-coder14b-cola", BASICO, 1, None),    # ~1 h: jefe Qwen35 (M40) + obrero Coder-14B (3060)
    ("par-gptoss-coder14b-cola", BASICO, 1, None),    # ~1 h: control con el código nuevo (antes 81,1 %): ¿suben v-divisas/e-texto?
    ("par-qwen35-qwen9b-cola", BASICO, 1, None),      # ~1 h: mismo jefe con obrero Qwen3.5-9B
    ("m40-solo-qwen35-35b-a3b", BASICO, 1, None),     # ~2 h: 2.ª tirada (hoy 96,7 %) para saber cuánto es ruido
    ("par-qwen35-coder14b-cola", {"prueba": "cuentas-claras", "modalidad": "guiada"}, 1, None),  # la prueba larga (31,0 % con gpt-oss)
]

if __name__ == "__main__":
    sys.exit(base.main())
