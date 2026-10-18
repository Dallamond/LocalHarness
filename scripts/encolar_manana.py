"""Monta la cola del banco para una jornada larga con las dos GPU (M40 + 3060). Se lanza con LocalHarness abierto:

    .venv\\Scripts\\python.exe scripts\\encolar_manana.py            # simula: dice qué encolaría
    .venv\\Scripts\\python.exe scripts\\encolar_manana.py --aplicar   # encola y deja las tandas nuevas delante de lo pendiente
    .venv\\Scripts\\python.exe scripts\\encolar_manana.py --aplicar --empezar   # y arranca la cola

Habla con la API (no con la CLI, que interrumpe tareas vivas). Si un modelo no está descargado, esa tanda se salta y lo
dice. Es idempotente: no repite una tanda igual que ya esté pendiente o en marcha.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8095"
CONT = Path(__file__).resolve().parent.parent / "banco" / "contendientes"
# casos que separan unos modelos de otros (los fáciles que algunos fallan y los difíciles): cribado rápido de un modelo nuevo
CRIBADO = ["e-precio", "t-valores", "d-mixto", "a-modulo-falta", "a-archivo-largo", "m-carrito", "m-paso", "v-divisas"]

# (contendiente, qué corre, repeticiones, casos): el orden es el de la cola
PLAN = [
    ("par-gptoss-coder14b-cola", {"repertorio": "basico"}, 1, None),       # A/B del reparto: control
    ("par-gptoss-coder14b-dividir", {"repertorio": "basico"}, 1, None),    # A/B del reparto: el cambio
    ("par-gptoss-qwen9b-dividir", {"repertorio": "basico"}, 1, None),      # otro obrero, más rápido
    ("m40-solo-gptoss", {"repertorio": "basico"}, 1, None),                # 2ª tirada de la referencia: cuánto es ruido
    ("m40-solo-qwen3-coder-30b", {"repertorio": "basico"}, 1, CRIBADO),    # modelo nuevo (si está descargado)
    ("m40-solo-qwen35-35b-a3b", {"repertorio": "basico"}, 1, CRIBADO),     # modelo nuevo (si está descargado)
    ("m40-solo-gptoss", {"prueba": "cuentas-claras", "modalidad": "guiada"}, 1, None),        # la prueba difícil, referencia
    ("par-gptoss-coder14b-dividir", {"prueba": "cuentas-claras", "modalidad": "guiada"}, 1, None),
]


def api(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def resolver(nombre: str, disponibles: list[str]) -> str | None:
    """El nombre exacto del GGUF en disco: igual, o el único que lo contiene (sin mayúsculas)."""
    if nombre in disponibles:
        return nombre
    hits = [m for m in disponibles if nombre.lower() in m.lower()]
    return hits[0] if len(hits) == 1 else (sorted(hits)[0] if hits else None)


def modelos_de(cont: dict) -> list:
    return [v for v in (cont.get("modelos") or {}).values() if v]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aplicar", action="store_true", help="encolar de verdad (si no, solo simula)")
    ap.add_argument("--empezar", action="store_true", help="arrancar la cola al acabar")
    args = ap.parse_args()
    try:
        info = api("GET", "/api/llama")
    except OSError as e:
        print(f"LocalHarness no responde en {BASE}: ábrelo primero ({e})")
        return 1
    disponibles = [m["name"] for m in info.get("models") or []]
    cola = api("GET", "/api/banco/cola")
    existentes = {(t["contendiente"].get("nombre"), t.get("prueba"), t.get("modalidad"), tuple(t.get("casos") or ()))
                  for t in cola["tandas"] if t["estado"] in ("pendiente", "en marcha")}
    nuevas: list[str] = []
    for nombre, que, reps, casos in PLAN:
        cont = json.loads((CONT / f"{nombre}.json").read_text(encoding="utf-8"))
        faltan = []
        for clave, v in (cont.get("modelos") or {}).items():
            if not v:
                continue
            quiere = v if isinstance(v, str) else v["modelo"]
            real = resolver(quiere, disponibles)
            if not real:
                faltan.append(quiere)
            elif real != quiere:  # nombre aproximado: se usa el exacto del disco
                if isinstance(v, str):
                    cont["modelos"][clave] = real
                else:
                    v["modelo"] = real
        etiqueta = que.get("repertorio") or f"{que['prueba']} {que['modalidad']}"
        if faltan:
            print(f"SALTO  {nombre} ({etiqueta}): falta descargar {', '.join(faltan)}")
            continue
        todos = json.loads((CONT.parent / "repertorios" / "basico.json").read_text(encoding="utf-8"))["casos"]
        elegidos = tuple(casos or todos) if que.get("repertorio") else ()
        key = (nombre, que.get("repertorio") or que.get("prueba"),
               "repertorio" if que.get("repertorio") else que.get("modalidad"), elegidos)
        if key in existentes:
            print(f"YA ESTÁ {nombre} ({etiqueta})")
            continue
        n = f"{len(elegidos)} casos" if elegidos else ""
        print(f"{'ENCOLO' if args.aplicar else 'ENCOLARÍA'} {nombre} · {etiqueta} {n}")
        if not args.aplicar:
            continue
        r = api("POST", "/api/banco/cola", {**que, "repeticiones": reps, "casos": casos, "contendiente": {**cont, "nombre": nombre}})
        nuevas.append(r["id"])
    if args.aplicar and nuevas:
        colocar(nuevas)
    if args.aplicar and args.empezar:
        print("cola:", api("POST", "/api/banco/cola/empezar"))
    return 0


def colocar(nuevas: list[str]) -> None:
    """Las tandas nuevas, delante de las pendientes antiguas (y detrás de lo hecho y de lo que corre ahora)."""
    for k, tid in enumerate(nuevas):
        tandas = api("GET", "/api/banco/cola")["tandas"]
        ids = [t["id"] for t in tandas]
        frontera = next((i for i, t in enumerate(tandas) if t["estado"] == "pendiente" and t["id"] not in nuevas), None)
        if frontera is None:
            return
        delta = (frontera + k) - ids.index(tid)
        if delta < 0:
            api("POST", f"/api/banco/cola/{tid}/mover", {"delta": delta})


if __name__ == "__main__":
    sys.exit(main())
