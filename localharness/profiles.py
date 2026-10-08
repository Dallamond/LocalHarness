"""Armario de modelos (P1 de docs/PLAN-MODELOS-LOCALES.md): cada GGUF como un PERFIL = qué sabe hacer + cómo
arrancarlo + dónde cabe.

- Capacidades (`CAPS`): se deducen del nombre, de los metadatos del GGUF (plantilla con herramientas o
  pensamiento, parámetros), del catálogo (tags) y de si hay un `mmproj` al lado (visión). Lucas las corrige a mano
  en Modelos locales; lo suyo manda (`llama.profiles[ruta].caps`).
- Arranque: lo de siempre (`llama.per_model`: ctx, ngl y opciones) más lo que no cabe en una opción simple:
  el proyector de visión (`mmproj`) y el modelo borrador para la decodificación especulativa (`draft`, P5).
- Dónde cabe: la estimación de memoria (catalog.estimate) en cada GPU sola y en las dos unidas.

Claude y el planificador piden CAPACIDADES («necesito visión»), no archivos: `pick` elige perfil y servidor.
"""

import re
from pathlib import Path

from localharness import catalog, hardware, llama, settings
from localharness.store import Store

CAPS = ("plan", "code", "review", "vision", "ocr", "embed", "draft", "tools", "thinking", "fast")
CAP_TEXT = {"plan": "planificar", "code": "programar", "review": "revisar", "vision": "ver imágenes",
            "ocr": "leer escaneados", "embed": "embeddings (RAG)", "draft": "borrador (especulativa)",
            "tools": "herramientas", "thinking": "razona", "fast": "rápido"}
TAG_CAPS = {"código": "code", "agente": "tools", "razonador": "plan", "visión": "vision", "embeddings": "embed"}
UNIDO = "unido"


def auto_caps(name: str, meta: dict, size_gb: float, entry: dict | None, has_mmproj: bool) -> list[str]:
    n = name.lower()
    params = meta.get("params_b") or (entry or {}).get("params_b") or 0
    caps: set[str] = set()
    if re.search(r"embed|bge-|e5-|nomic|minilm", n) or "bert" in str(meta.get("arch") or ""):
        return ["embed"]  # un modelo de embeddings no sirve para nada más
    if re.search(r"coder|devstral|codestral|starcoder|deepseek-coder", n):
        caps |= {"code", "review"}
    elif params >= 7 or size_gb >= 4.5:
        caps |= {"code", "review"}  # los generalistas de 7B+ programan bien para trozos pequeños
    if meta.get("tools_in_template") or (entry or {}).get("tools"):
        caps.add("tools")
    if meta.get("thinking") or (entry or {}).get("thinking") or re.search(r"gpt-oss|reason|r1\b|qwq", n):
        caps.add("thinking")
        if params >= 14 or re.search(r"gpt-oss", n):
            caps.add("plan")
    if has_mmproj:
        caps |= {"vision", "ocr"}
    if params and params <= 2.5 or size_gb <= 1.8:
        caps.add("draft")
    if size_gb <= 3.5:
        caps.add("fast")
    for tag in (entry or {}).get("tags") or []:
        if tag in TAG_CAPS:
            caps.add(TAG_CAPS[tag])
    return [c for c in CAPS if c in caps]


def mmproj_for(model: Path) -> Path | None:
    """El proyector de visión que va con este GGUF: un mmproj*.gguf en su carpeta (si hay varios, el que más
    se parece de nombre)."""
    found = sorted(model.parent.glob("mmproj*.gguf"))
    if not found:
        return None
    stem = re.sub(r"(?i)[-_.](i?q\d[_a-z0-9]*|f16|bf16|f32)$", "", model.stem).lower()

    def score(p: Path) -> int:
        other = p.stem.lower().removeprefix("mmproj").strip("-_.")
        return sum(1 for a, b in zip(stem, other) if a == b)
    return max(found, key=score)


def tokenizer_of(path: Path) -> tuple[str | None, int | None]:
    """(tipo de tokenizador, tamaño del vocabulario): el borrador tiene que compartirlos con el modelo."""
    from localharness import gguf
    try:
        meta = gguf.read_metadata(path)
    except Exception:  # noqa: BLE001 — un GGUF raro no rompe la lista
        return None, None
    tokens = meta.get("tokenizer.ggml.tokens")
    return meta.get("tokenizer.ggml.model"), len(tokens) if isinstance(tokens, list) else None


def draft_problem(model: Path, draft: Path) -> str | None:
    """None si `draft` puede ser borrador de `model`; si no, por qué (lo avisa la GUI antes de arrancar)."""
    a, b = tokenizer_of(model), tokenizer_of(draft)
    if None in a or None in b:
        return None  # no se sabe: que lo diga llama.cpp
    if a[0] != b[0]:
        return f"tokenizadores distintos ({a[0]} y {b[0]})"
    if abs(a[1] - b[1]) > 128:  # misma familia: el vocabulario apenas cambia (tokens especiales)
        return f"vocabularios distintos ({a[1]} y {b[1]} tokens): no son de la misma familia"
    return None


def own(store: Store, path: str) -> dict:
    return (settings.load(store)["llama"].get("profiles") or {}).get(path) or {}


def launch_extra(store: Store, path: str) -> list[str]:
    """Argumentos de llama-server que salen del perfil (no son opciones simples: llevan rutas)."""
    p = own(store, path)
    out: list[str] = []
    if p.get("mmproj") and Path(p["mmproj"]).is_file():
        out += ["--mmproj", p["mmproj"]]
    d = p.get("draft") or {}
    if d.get("model") and Path(d["model"]).is_file():
        out += ["-md", d["model"], "-ngld", str(d.get("ngl", 99))]
        if d.get("device"):
            out += ["-devd", str(d["device"])]
        if d.get("max"):
            out += ["--draft-max", str(int(d["max"]))]
        if d.get("min"):
            out += ["--draft-min", str(int(d["min"]))]
    return out


def describe_all(store: Store, modelinfo, load_times: dict | None = None, devices: list[dict] | None = None,
                 budget: dict | None = None) -> list[dict]:
    """Todos los GGUF como perfiles: capacidades (auto y a mano), arranque, dónde caben y lo que tardan en cargar."""
    devices = llama.list_devices() if devices is None else devices
    if budget is None:
        budget = hardware.budget(hardware.detect(), settings.load(store)["llama"].get("hardware"))
    cat = catalog.load_catalog()
    times = load_times or {}
    out = []
    for m in llama.list_models():
        d = llama.describe(m)
        meta = modelinfo.summary(m) or {} if modelinfo else {}
        if meta.get("error"):
            meta = {}
        entry = catalog.match_catalog(m.name, cat)
        mine = own(store, str(m))
        proj = mine.get("mmproj") or (str(mmproj_for(m)) if d["vision"] and mmproj_for(m) else "")
        auto = auto_caps(m.name, meta, d["size_gb"], entry, bool(proj))
        caps = [c for c in mine["caps"] if c in CAPS] if isinstance(mine.get("caps"), list) else auto
        launch = settings.llama_launch(store, str(m))
        out.append({**d, "caps": caps, "auto_caps": auto, "manual": isinstance(mine.get("caps"), list),
                    "mmproj": proj, "draft": mine.get("draft") or None,
                    "ctx": launch["ctx"], "ngl": launch["ngl"], "options": launch["options"],
                    "load_s": times.get(str(m)) or times.get(m.name),
                    "fits": fits(meta, d["size_gb"], launch, budget, devices)})
    return out


def fits(meta: dict, size_gb: float, launch: dict, budget: dict, devices: list[dict]) -> dict:
    """{CUDA0: {fit, vram_gb, tps_est}, CUDA1: …, unido: …}. fit: gpu | mixto | no (como en catalog.estimate)."""
    out = {}
    targets = [x["id"] for x in devices] + ([",".join(x["id"] for x in devices)] if len(devices) > 1 else [])
    for dev in targets:
        b = hardware.device_budget(budget, devices, dev)
        est = catalog.estimate(meta, size_gb, {**launch["options"], "ctx": launch["ctx"], "ngl": launch["ngl"]}, b)
        out[UNIDO if "," in dev else dev] = {"fit": est.get("fit"), "vram_gb": est.get("vram_gb"),
                                             "tps_est": est.get("tps_est")}
    return out


def pick(cap: str, profiles: list[dict], servers: list[dict]) -> tuple[dict, dict] | None:
    """El mejor (perfil, servidor) para una capacidad. Primero uno que ya esté cargado (no hay que cambiar nada);
    si no, el perfil con esa capacidad que quepa entero en la GPU del servidor, prefiriendo el servidor más libre
    de papel parecido y el modelo más capaz que quepa (más grande) — salvo para `fast`/`draft`, el más pequeño."""
    able = [p for p in profiles if cap in p["caps"]]
    if not able:
        return None
    for srv in servers:
        loaded = (srv.get("status") or {}).get("model")
        hit = next((p for p in able if loaded and Path(p["path"]) == Path(loaded)), None)
        if hit:
            return hit, srv
    small_first = cap in ("fast", "draft", "embed")
    best = None
    for srv in servers:
        dev = srv.get("device") or ""
        key = UNIDO if "," in dev else dev
        for p in able:
            fit = (p.get("fits") or {}).get(key, {}).get("fit") if key else "gpu"
            if fit != "gpu":
                continue
            score = (-p["size_gb"] if small_first else p["size_gb"])
            if best is None or score > best[0]:
                best = (score, p, srv)
    return (best[1], best[2]) if best else None
