r"""Cola del 21/10 con la M40 sola (la 3060 sigue siendo de Lucas): jefe local con los arreglos mecánicos nuevos
(Jest→node:test, tests sueltos/inventados, choque import/declaración), pensamiento por papel y la prueba larga.

    .venv\Scripts\python.exe scripts\encolar_hoy.py             # simula
    .venv\Scripts\python.exe scripts\encolar_hoy.py --aplicar --empezar

Usa la API (no la CLI) y las mismas reglas que `encolar_manana.py` (idempotente, salta lo que no está descargado)."""
import sys

import encolar_manana as base

base.PLAN[:] = [
    ("m40-solo-gptoss", {"repertorio": "basico"}, 2, None),                # código nuevo: 2 tiradas (antes 90,6 y 73,6 %)
    ("m40-solo-gptoss-diag-alto", {"repertorio": "basico"}, 1, None),      # diagnóstico con razonamiento alto
    ("m40-solo-gptoss-plan-medio", {"repertorio": "basico"}, 1, None),     # planificador con razonamiento medio
    ("m40-solo-qwen35-35b-a3b", {"repertorio": "basico"}, 1, None),        # 2.ª tirada con el código nuevo (83,6 %)
    ("m40-solo-gptoss", {"prueba": "cuentas-claras", "modalidad": "guiada"}, 1, None),  # la prueba difícil (31,0 %)
]

if __name__ == "__main__":
    sys.exit(base.main())
