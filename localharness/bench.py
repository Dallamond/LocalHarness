"""Banco de pruebas de los modelos locales (P4): la misma petición para todos y sus números de verdad.

Una petición fija (un prompt de ~4.000 tokens de código y pedir ~512 de respuesta) a un llama-server ya arrancado:
llama-server devuelve en `timings` cuántos tokens/s leyó y escribió. Se guarda por modelo y topología (sola en
CUDA0, sola en CUDA1, unida…) en data/llama-bench.json, con la VRAM de cada GPU en ese momento. Con esto se decide
si compensa unir las GPU (P3), si el borrador acelera (P5) y qué perfil poner en cada servidor (P16).
"""

import json
import time
import urllib.request
from pathlib import Path

PROMPT_TOKENS = 4000
ANSWER_TOKENS = 512

# ~4k tokens de código variado (se repite un bloque realista hasta llegar)
_BLOCK = '''
def repartir(bloques, servidores):
    """Asigna cada bloque al servidor con menos trabajo pendiente."""
    cola = {s["id"]: 0 for s in servidores}
    plan = []
    for b in bloques:
        elegido = min(cola, key=cola.get)
        cola[elegido] += len(b.get("instrucciones", ""))
        plan.append((b["id"], elegido))
    return plan

.tarjeta { display: grid; grid-template-columns: 1fr 2fr; gap: 0.75rem; padding: 1rem; }
.tarjeta h2 { font-family: var(--font-serif); color: var(--text-ink); }
<section id="herramientas"><h2>Herramientas del taller</h2><ul class="lista"><li>gubia</li><li>formón</li></ul></section>
'''


def bench_prompt() -> str:
    reps = max(1, PROMPT_TOKENS * 3 // len(_BLOCK))  # ~3 caracteres por token en código
    return ("Lee este código y escribe a continuación una función nueva `equilibrar(plan)` en Python que reparta "
            "mejor los bloques, con docstring y tres tests unittest. Solo código.\n\n" + _BLOCK * reps)


def run(url: str, key: str | None = None, post=None, timeout: float = 600) -> dict:
    """Una pasada contra un llama-server. `post` (pruebas): función (url, body) -> respuesta JSON."""
    body = {"messages": [{"role": "user", "content": bench_prompt()}], "max_tokens": ANSWER_TOKENS,
            "temperature": 0, "cache_prompt": False, "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.monotonic()
    data = (post or _post)(url.rstrip("/") + "/v1/chat/completions", body, key, timeout)
    wall = time.monotonic() - t0
    t = data.get("timings") or {}
    usage = data.get("usage") or {}
    return {"prompt_tokens": usage.get("prompt_tokens") or t.get("prompt_n"),
            "answer_tokens": usage.get("completion_tokens") or t.get("predicted_n"),
            "read_tps": round(t["prompt_per_second"], 1) if t.get("prompt_per_second") else None,
            "write_tps": round(t["predicted_per_second"], 1) if t.get("predicted_per_second") else None,
            # con decodificación especulativa llama-server cuenta cuántos tokens del borrador aceptó
            "draft_accept": (round(t["draft_n_accepted"] / t["draft_n"], 2)
                             if t.get("draft_n") and t.get("draft_n_accepted") is not None else None),
            "seconds": round(wall, 1), "model": data.get("model")}


def _post(url: str, body: dict, key: str | None, timeout: float) -> dict:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def save(path: Path, model: str, topology: str, result: dict, vram: list[dict] | None = None,
         extra: dict | None = None) -> dict:
    """Guarda el resultado (el último de cada modelo × topología) y devuelve la tabla entera."""
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        table = {}
    key = f"{Path(model).name}|{topology}"
    table[key] = {**result, "model": str(model), "topology": topology, "at": time.time(),
                  "vram": vram or [], **(extra or {})}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    return table


def load(path: Path) -> list[dict]:
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return sorted(table.values(), key=lambda r: -(r.get("write_tps") or 0))


def topology_of(srv: dict, options: dict | None) -> str:
    dev = (options or {}).get("device") or srv.get("device") or ""
    draft = " + borrador" if (options or {}).get("draft") else ""
    return ("unido " + dev if "," in dev else dev or "auto") + draft
