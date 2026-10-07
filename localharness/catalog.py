"""Recomendar modelos locales: qué cabe en tu hardware, con qué ajustes y qué tal sirve para LocalHarness.

- `estimate`: memoria (VRAM / RAM) y tok/s aproximados de un GGUF con unos ajustes de arranque.
- `suggest_options`: los ajustes que proponemos para tu PC (contexto, caché KV, capas o expertos en CPU…).
- `recommend`: el catálogo (`model_catalog.json`) ordenado para tu hardware, con la cuantización que te cabe.
- `rate_local`: nota 0-100 de un GGUF ya descargado como modelo para LocalHarness, con los motivos.

Todo es aproximado (±10 %): llama.cpp reserva además búferes que dependen de la versión y del lote.
"""

import json
import re
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("model_catalog.json")

# bits por peso de cada cuantización (media de llama.cpp, incluye escalas). Para estimar tamaños sin descargar.
QUANT_BPW = {
    "F32": 32, "F16": 16, "BF16": 16, "Q8_0": 8.5, "Q6_K": 6.56, "Q5_K_M": 5.69, "Q5_K_S": 5.54, "Q5_0": 5.5,
    "Q4_K_M": 4.85, "Q4_K_S": 4.58, "Q4_0": 4.55, "IQ4_NL": 4.5, "IQ4_XS": 4.25, "MXFP4": 4.25,
    "Q3_K_L": 4.27, "Q3_K_M": 3.91, "Q3_K_S": 3.5, "IQ3_M": 3.66, "IQ3_S": 3.44, "IQ3_XS": 3.3, "IQ3_XXS": 3.06,
    "Q2_K": 3.0, "Q2_K_L": 3.2, "IQ2_M": 2.7, "IQ2_S": 2.5, "IQ2_XS": 2.31, "IQ2_XXS": 2.06,
}
# de mejor a peor calidad; las «UD-» de Unsloth equivalen a la de su nombre con algo más de precisión
QUANT_ORDER = ["Q8_0", "Q6_K", "Q5_K_M", "Q5_K_S", "Q4_K_M", "Q4_K_S", "MXFP4", "IQ4_NL", "IQ4_XS", "Q4_0",
               "Q3_K_L", "Q3_K_M", "IQ3_M", "Q3_K_S", "IQ3_XS", "IQ3_XXS", "Q2_K_L", "Q2_K", "IQ2_M"]
KV_BYTES = {"f16": 2.0, "bf16": 2.0, "f32": 4.0, "q8_0": 1.0625, "q5_1": 0.75, "q5_0": 0.6875, "q4_1": 0.625,
            "q4_0": 0.5625, "iq4_nl": 0.5625}
CTX_STEPS = [131072, 65536, 49152, 32768, 24576, 16384, 8192, 4096]
EFFICIENCY = 0.7  # fracción del ancho de banda que se aprovecha al generar (cuadra con lo medido en la 3060)

_QUANT_RE = re.compile(r"(?i)(?:^|[-_./])(UD-)?(i?q\d[_a-z0-9]*|f16|bf16|f32|mxfp4)(?=[-./]|$)")


def load_catalog() -> list[dict]:
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))["models"]
    except (OSError, ValueError, KeyError):
        return []


def quant_of(name: str) -> str | None:
    """'Qwen3-8B-UD-Q4_K_XL.gguf' → 'UD-Q4_K_XL'; 'Q4_K_M/x-00001-of-00002.gguf' → 'Q4_K_M'."""
    hits = _QUANT_RE.findall(name)
    if not hits:
        return None
    ud, q = hits[-1]
    return (("UD-" if ud else "") + q).upper()


def base_quant(q: str | None) -> str | None:
    """Cuantización «normal» equivalente (UD-Q4_K_XL → Q4_K_M) para tamaños y orden de calidad."""
    if not q:
        return None
    q = q.upper().removeprefix("UD-")
    if q in QUANT_BPW:
        return q
    m = re.match(r"(I?Q\d)_K_(XL|L)$", q)
    if m:
        return f"{m.group(1)}_K_M" if f"{m.group(1)}_K_M" in QUANT_BPW else None
    m = re.match(r"(I?Q\d)", q)
    return next((k for k in QUANT_ORDER if k.startswith(m.group(1))), None) if m else None


def match_catalog(name: str, catalog: list[dict] | None = None) -> dict | None:
    low = name.lower().replace("_", "-")
    hits = [e for e in (catalog if catalog is not None else load_catalog()) if e.get("match") and e["match"] in low]
    return max(hits, key=lambda e: len(e["match"])) if hits else None


# --- memoria
def kv_bytes_per_token(s: dict) -> float | None:
    """Bytes de caché KV (f16) por token, con atención deslizante e híbridos tenidos en cuenta a medias."""
    layers, hkv, kl, vl = s.get("attn_layers") or s.get("n_layer"), s.get("n_head_kv"), s.get("key_length"), \
        s.get("value_length")
    if not (layers and hkv and kl):
        return None
    return layers * hkv * (kl + (vl or kl)) * 2.0


def _swa_share(s: dict, ctx: int) -> float:
    """Fracción efectiva de la caché cuando parte de las capas usa ventana deslizante (Gemma, gpt-oss)."""
    sw = s.get("sliding_window")
    if not sw or sw >= ctx:
        return 1.0
    swa_layers = {"gemma3": 5 / 6, "gemma2": 0.5, "gpt-oss": 0.5}.get(s.get("arch") or "", 0)
    return (1 - swa_layers) + swa_layers * sw / ctx


def estimate(s: dict, file_gb: float, opts: dict, budget: dict | None = None) -> dict:
    """Memoria y velocidad de un modelo con unos ajustes. `s` = gguf.summarize (o lo que se sepa del catálogo:
    n_layer, moe, params_b, active_b, kv_mb_1k)."""
    ctx = int(opts.get("ctx") or 16384)
    n_layer = int(s.get("n_layer") or 32)
    ngl = opts.get("ngl")
    ngl = n_layer + 1 if ngl in (None, "") else int(ngl)
    fa = (opts.get("flash_attn") or "auto") != "off"
    ck = KV_BYTES.get(str(opts.get("cache_k") or "f16").lower(), 2.0) / 2
    cv = KV_BYTES.get(str(opts.get("cache_v") or "f16").lower(), 2.0) / 2
    per_tok = kv_bytes_per_token(s)
    if per_tok is None:
        per_tok = float(s.get("kv_mb_1k") or 128) * 2**20 / 1000
    kv_gb = per_tok * ((ck + cv) / 2) * ctx * _swa_share(s, ctx) / 2**30

    gpu_frac = min(1.0, max(0.0, ngl / n_layer))
    weights_gpu = file_gb * gpu_frac
    moe_cpu = int(opts.get("n_cpu_moe") or 0)
    if s.get("moe") and moe_cpu and s.get("params_b") and s.get("active_b"):
        expert_share = max(0.0, 1 - s["active_b"] / s["params_b"])  # parte de los pesos que son expertos
        moved = file_gb * expert_share * min(moe_cpu, n_layer) / n_layer
        weights_gpu = max(0.0, weights_gpu - moved)
    weights_cpu = file_gb - weights_gpu
    kv_gpu = kv_gb * gpu_frac
    overhead = 0.3 + ctx / 1000 * (0.006 if fa else 0.03)  # búfer de cálculo de llama.cpp, a ojo
    vram = weights_gpu + kv_gpu + overhead
    ram = weights_cpu + (kv_gb - kv_gpu) + 0.5

    out = {"ctx": ctx, "weights_gb": round(file_gb, 2), "weights_gpu_gb": round(weights_gpu, 2),
           "weights_cpu_gb": round(weights_cpu, 2), "kv_gb": round(kv_gb, 2), "kv_gpu_gb": round(kv_gpu, 2), "overhead_gb": round(overhead, 2),
           "vram_gb": round(vram, 2), "ram_gb": round(ram, 2)}
    if budget:
        bw_gpu, bw_ram = budget.get("bandwidth_gbs") or 300, 50
        active = (s.get("active_b") / s["params_b"]) if s.get("moe") and s.get("active_b") and s.get("params_b") \
            else 1.0
        # cada token lee los pesos activos; lo que está en la CPU va al ritmo de la RAM
        t = (weights_gpu * active) / bw_gpu + (weights_cpu * active) / bw_ram
        eff = EFFICIENCY * (0.75 if s.get("moe") else 1)  # el enrutado de expertos tiene su coste
        out["tps_est"] = round(eff / t, 0) if t > 0 else None
        usable, usable_ram = budget.get("usable_vram_gb") or 0, budget.get("usable_ram_gb") or 0
        if not usable:
            out["fit"] = "cpu" if ram <= usable_ram + vram else "no"
        elif vram <= usable and weights_cpu < 0.05:
            out["fit"] = "gpu"
        elif vram <= usable and ram <= usable_ram:
            out["fit"] = "mixto"
        else:
            out["fit"] = "no"
        out["vram_free_after_gb"] = round(usable - vram, 2)
    return out


def suggest_options(s: dict, file_gb: float, budget: dict, catalog_entry: dict | None = None,
                    cores: int | None = None) -> dict:
    """Ajustes que proponemos: el mayor contexto (hasta 64k, mejor ≥32k para agentes) que quepa en la GPU,
    con caché KV en q8_0 si hace falta; si no cabe, expertos (MoE) o capas a la CPU."""
    train = int(s.get("ctx_train") or 32768)
    n_layer = int(s.get("n_layer") or 32)
    base = {"flash_attn": "on", "parallel": 1, "jinja": True}
    if cores:
        base["threads"] = max(1, cores // 2)  # núcleos físicos, aprox.
    if catalog_entry and catalog_entry.get("sampling"):
        base.update(catalog_entry["sampling"])
    steps = [c for c in CTX_STEPS if c <= min(train, 65536)] or [min(train, 4096)]

    def first_fit(extra: dict) -> dict | None:
        for ctx in steps:
            for kv in ("f16", "q8_0"):
                o = {**base, **extra, "ctx": ctx, "cache_k": kv, "cache_v": kv}
                e = estimate(s, file_gb, o, budget)
                if e["fit"] in ("gpu", "mixto"):  # de mayor a menor contexto; antes f16 que q8_0
                    return {"options": o, "estimate": e}
        return None

    if budget.get("usable_vram_gb"):
        got = first_fit({"ngl": 99})
        if got and got["estimate"]["fit"] == "gpu":
            got["why"] = "Cabe entero en la GPU."
            return got
        if s.get("moe"):  # mover expertos a la CPU apenas cuesta velocidad en MoE
            for n in range(1, n_layer + 1):
                got = first_fit({"ngl": 99, "n_cpu_moe": n})
                if got and got["estimate"]["ctx"] >= min(32768, steps[0]):
                    got["why"] = f"No cabe entero: {n} capas de expertos en la CPU (en MoE apenas se nota)."
                    return got
        for ngl in range(n_layer, 0, -2):
            got = first_fit({"ngl": ngl})
            if got and got["estimate"]["ctx"] >= min(16384, steps[0]):
                got["why"] = f"No cabe entero: {ngl} de {n_layer} capas en la GPU, el resto en la CPU (más lento)."
                return got
    o = {**base, "ctx": min(8192, steps[0]), "ngl": 0, "cache_k": "q8_0", "cache_v": "q8_0"}
    return {"options": o, "estimate": estimate(s, file_gb, o, budget), "why": "Solo CPU: será lento."}


# --- catálogo
def _catalog_summary(e: dict) -> dict:
    """Lo que estimate necesita, sacado de la ficha del catálogo (sin descargar nada)."""
    return {"arch": e.get("arch"), "n_layer": e.get("n_layer") or (48 if e.get("params_b", 0) > 20 else 36),
            "moe": e.get("moe"), "params_b": e.get("params_b"), "active_b": e.get("active_b"),
            "kv_mb_1k": e.get("kv_mb_1k"), "ctx_train": e.get("ctx_train")}


def quant_sizes(e: dict, files: list[dict] | None = None) -> dict[str, dict]:
    """{quant: {size_gb, files[]}} con los tamaños reales de HF si los hay; si no, estimados."""
    out: dict[str, dict] = {}
    for f in files or []:
        p = f["path"]
        if not p.lower().endswith(".gguf") or "mmproj" in p.lower():
            continue
        q = quant_of(p)
        if not q:
            continue
        d = out.setdefault(q, {"size_gb": 0.0, "files": [], "exact": True})
        d["size_gb"] += f.get("size", 0) / 2**30
        d["files"].append(p)
    if not out and e.get("est_quants"):  # modelos con tamaños que no siguen la regla (gpt-oss en MXFP4)
        out = {q: {"size_gb": gb, "files": [], "exact": False} for q, gb in e["est_quants"].items()}
    if not out:
        for q in ("Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "IQ4_XS", "Q3_K_M"):
            out[q] = {"size_gb": e["params_b"] * 1e9 * QUANT_BPW[q] / 8 / 2**30, "files": [], "exact": False}
    for d in out.values():
        d["size_gb"] = round(d["size_gb"], 2)
        d["files"].sort()
    return out


def pick_quant(e: dict, sizes: dict[str, dict], budget: dict, ctx: int = 32768) -> dict | None:
    """La mejor cuantización (≤ Q8_0) que cabe con `ctx` tokens; si ninguna cabe en la GPU, la mejor que
    funciona en modo mixto (MoE con expertos en CPU, o pocas capas fuera)."""
    s = _catalog_summary(e)
    ranked = sorted(sizes.items(), key=lambda kv: (
        QUANT_ORDER.index(base_quant(kv[0])) if base_quant(kv[0]) in QUANT_ORDER else 99,
        0 if kv[0].startswith("UD-") else 1))
    ranked = [(q, d) for q, d in ranked if base_quant(q) in QUANT_ORDER]
    for want in ("gpu", "mixto"):
        for q, d in ranked:
            if want == "mixto" and QUANT_ORDER.index(base_quant(q)) < QUANT_ORDER.index("Q4_K_M"):
                continue  # con parte en la CPU manda la velocidad: no compensa pasar de Q4
            sug = suggest_options(s, d["size_gb"], budget)
            est = sug["estimate"]
            if est["fit"] == want and est["ctx"] >= min(ctx, s["ctx_train"] or ctx, 16384 if want == "mixto" else ctx):
                return {"quant": q, **d, "options": sug["options"], "estimate": est, "why": sug.get("why")}
    return None


def recommend(budget: dict, hf_files: dict[str, list[dict]] | None = None,
              local_names: list[str] | None = None) -> list[dict]:
    """Catálogo ordenado para este hardware: primero lo que cabe y mejor agente es."""
    local_low = [n.lower().replace("_", "-") for n in local_names or []]
    out = []
    for e in load_catalog():
        files = (hf_files or {}).get(e["repo"])
        sizes = quant_sizes(e, files)
        best = pick_quant(e, sizes, budget)
        fit = best["estimate"]["fit"] if best else "no"
        tps = best["estimate"].get("tps_est") if best else None
        speed_pts = min(10, (tps or 0) / 6)  # 60 tok/s o más = 10
        score = e["agentic"] * 6 + (25 if fit == "gpu" else 12 if fit == "mixto" else 0) + speed_pts * 1.5
        out.append({**{k: e.get(k) for k in ("id", "name", "repo", "params_b", "active_b", "moe", "ctx_train",
                                               "agentic", "tools", "thinking", "tags", "roles", "notes")},
                    "url": f"https://huggingface.co/{e['repo']}", "fit": fit, "best": best,
                    "quants": [{"quant": q, "size_gb": d["size_gb"], "exact": d["exact"], "files": d["files"]}
                               for q, d in sizes.items()],
                    "hf_checked": files is not None,
                    "downloaded": any(e["match"] in n for n in local_low),
                    "score": round(min(100, score))})
    out.sort(key=lambda r: -r["score"])
    return out


# --- nota de un modelo descargado
VERDICTS = [(80, "Muy recomendado"), (60, "Recomendado"), (40, "Aceptable"), (0, "Poco recomendado")]


def rate_local(s: dict, file_gb: float, budget: dict, probe: dict | None = None,
               measured_tps: float | None = None, entry: dict | None = None) -> dict:
    """Nota 0-100 para LocalHarness: herramientas (35) + cabe con contexto de agente (25) + capacidad (25)
    + velocidad (15). Una prueba real (`probe`) manda sobre lo que dice la plantilla."""
    reasons: list[str] = []
    sug = suggest_options(s, file_gb, budget, entry)
    est = sug["estimate"]

    if probe and probe.get("tool_calls") is not None:
        tools = 35 if probe["tool_calls"] else 5
        reasons.append("✔ Llamó a la herramienta en la prueba real" if probe["tool_calls"]
                       else "✘ En la prueba real no devolvió tool_calls")
    elif s.get("tools_in_template"):
        tools = 28
        reasons.append("✔ Su plantilla de chat admite herramientas (sin probar aún)")
    elif entry and entry.get("tools"):
        tools = 22
        reasons.append("◐ El catálogo dice que usa herramientas, pero la plantilla del GGUF no las trae")
    else:
        tools = 5
        reasons.append("✘ Su plantilla no admite herramientas: solo sirve para responder/escribir texto")

    ctx = est["ctx"]
    if est["fit"] == "gpu":
        fit = 25 if ctx >= 32768 else 18 if ctx >= 16384 else 10
        reasons.append(f"✔ Cabe en la GPU con {ctx // 1024}k de contexto")
    elif est["fit"] == "mixto":
        fit = 15 if s.get("moe") else 8
        reasons.append(f"◐ {sug.get('why')}")
    else:
        fit = 0
        reasons.append("✘ No cabe en tu GPU ni en RAM con un contexto útil")
    if ctx < 16384:
        reasons.append(f"◐ Contexto corto ({ctx // 1024}k): poco para leer repos")

    params = s.get("params_b") or (entry or {}).get("params_b") or file_gb * 8 / 5  # ~Q4 si no hay datos
    quality = min(20.0, 6 + params * 0.9) if not s.get("moe") else min(20.0, 10 + params * 0.35)
    if entry:
        quality = (quality + entry["agentic"] * 2) / 2
    if s.get("thinking"):
        quality += 3
        reasons.append("✔ Razona antes de responder (mejor como director/jefe técnico; más lento)")
    if probe and probe.get("json") is False:
        quality -= 5
        reasons.append("✘ No devolvió JSON válido en la prueba (malo para veredictos y planes)")
    quality = max(0.0, min(25.0, quality + 2))

    tps = measured_tps or (probe or {}).get("tps") or est.get("tps_est") or 0
    speed = min(15.0, tps / 4)  # 60 tok/s o más = 15
    if tps:
        reasons.append(f"{'✔' if tps >= 30 else '◐'} ~{round(tps)} tok/s {'medidos' if measured_tps or (probe or {}).get('tps') else 'estimados'}")

    score = round(tools + fit + quality + speed)
    if est["fit"] == "no":
        score = min(score, 30)  # si no se puede usar, da igual lo bueno que sea
    verdict = next(v for th, v in VERDICTS if score >= th)
    roles = []
    if tools >= 22 and est["fit"] != "no":
        roles.append("agente con herramientas")
    if quality >= 15 or s.get("thinking"):
        roles += ["director", "jefe técnico"]
    if tps >= 25 and ctx >= 16384:
        roles.append("consultas / delegación (local_ask)")
    return {"score": max(0, min(100, score)), "verdict": verdict, "reasons": reasons, "roles": roles,
            "parts": {"tools": tools, "fit": fit, "quality": round(quality), "speed": round(speed)},
            "suggested": sug}
