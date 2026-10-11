"""Saca de la base de datos el primer plan (`local_execute_plan`) que Claude mandó a los obreros en cada parche de una
prueba del banco con `claude-dirige`, para dárselo al cerebro 2 (`config.recetas`) y medir solo el bucle local.
Uso: python banco/recetas/extraer.py data/banco/<prueba>-<modalidad>/claude-dirige-<fecha> banco/recetas/<salida>.json"""
import json
import sqlite3
import sys
from pathlib import Path

run, salida = Path(sys.argv[1]), Path(sys.argv[2])
res = json.loads((run / "resultado.json").read_text(encoding="utf-8"))
db = sqlite3.connect(Path(__file__).resolve().parents[2] / "data" / "localharness.db")
recetas = []
for p in res["parches"]:
    blocks = None
    for tid in p.get("tareas") or []:
        for text, data in db.execute("select text, data from events where task_id=? and kind='tool' order by id", (tid,)):
            if text == "mcp__local__local_execute_plan":
                blocks = json.loads(data)["input"]["blocks"]
                break
        if blocks:
            break
    print(f"parche {p['n']}: {len(blocks) if blocks else 'SIN'} bloques")
    if blocks:
        recetas.append({"n": p["n"], "texto": p["texto"], "blocks": blocks})
salida.write_text(json.dumps(recetas, ensure_ascii=False, indent=1), encoding="utf-8")
