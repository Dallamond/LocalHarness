"""Agentes a medida: en vez de agentes ya hechos (Sonnet, jefe, director, Qwen…), cada tarea recibe un agente diseñado
desde cero para ELLA: proveedor y modelo, si coordina al modelo local, skills, servidores MCP, herramientas, límites.

1. `design()` le pasa a Claude Haiku (barato, solo lectura, salida JSON validada con `--json-schema`) la petición,
   un vistazo al proyecto y el catálogo (skills instaladas + biblioteca, MCP configurados y preparados, si hay modelo
   local arrancado). Devuelve una propuesta con el motivo de cada elección.
2. Si Claude no está o falla, `heuristic()` decide con reglas simples (palabras clave) para no bloquear nada.
3. `normalize()` limpia la propuesta: solo nombres que existen, límites razonables, combinaciones coherentes.
4. La GUI la enseña (puedes quitar skills/MCP) y `create_agent()` la guarda como agente con `config.generated`.
"""

import json
import re
from pathlib import Path

from localharness import library, settings
from localharness.adapters import get_adapter
from localharness.adapters.base import RunSpec
from localharness.events import Event
from localharness.runner import run
from localharness.store import Store

MODELS = ("haiku", "sonnet", "opus")
SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Nombre corto en minúsculas con guiones (p. ej. «arreglar-calc»)"},
        "description": {"type": "string"},
        "provider": {"type": "string", "enum": ["claude", "local_agent"]},
        "model": {"type": "string", "enum": list(MODELS)},
        "coordinator": {"type": "boolean"},
        "read_only": {"type": "boolean"},
        "web": {"type": "boolean"},
        "thinking": {"type": "string", "enum": ["apagado", "normal", "profundo"]},
        "skills": {"type": "array", "items": {"type": "string"}},
        "local_skills": {"type": "array", "items": {"type": "string"}},
        "mcps": {"type": "array", "items": {"type": "string"}},
        "max_turns": {"type": "integer"},
        "instructions": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["name", "provider", "model", "coordinator", "read_only", "skills", "mcps", "reason"],
}

PROMPT = """Diseña UN agente de programación hecho a medida para la tarea de abajo. No la resuelvas: solo elige su
configuración. Responde con el JSON del esquema.

## Tarea
{request}

## Proyecto «{project}» (primer nivel)
{files}

## Qué puedes elegir
- provider: «claude» (Claude Code con la suscripción del usuario) o «local_agent» (modelo local GRATIS con
  herramientas: leer, buscar, escribir, ejecutar tests; es pequeño y se equivoca más). Modelo local arrancado: {local}.
- model (solo claude): haiku = preguntas, explicar, cambios triviales · sonnet = programar de verdad · opus = solo si
  es muy difícil (gasta mucho).
- coordinator (solo claude, y solo si hay modelo local arrancado): Claude no escribe código, planifica y se lo encarga
  TODO al modelo local, luego revisa. Es lo que más cuota ahorra: úsalo para cambios de código con un plan claro.
- read_only: true si la tarea solo pide entender, revisar, explicar o investigar (sin cambiar archivos).
- web: true solo si hace falta internet (documentación nueva, versiones, errores raros).
- thinking: profundo para diseño/lógica delicada; apagado para lo mecánico; si no, normal.
- skills (del agente) y local_skills (las que llevará su modelo local si coordina): 0–4, SOLO de esta lista y solo
  las que de verdad ayuden:
{skills}
- mcps: 0–2, SOLO de esta lista y solo si la tarea lo necesita de verdad:
{mcps}
- max_turns: 5–40 según el tamaño. instructions: 2–5 líneas de cómo debe trabajar en ESTA tarea.
- reason: una frase por cada elección importante (por qué este modelo, estas skills, estos MCP)."""


def _files(repo: str) -> str:
    try:
        items = sorted(Path(repo).iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return "(no se puede leer)"
    names = [p.name + ("/" if p.is_dir() else "") for p in items if not p.name.startswith(".")][:40]
    return ", ".join(names) or "(vacío)"


def catalog(store: Store) -> dict:
    """Lo que se puede elegir: skills (instaladas + biblioteca), MCP (añadidos + preparados que no piden claves)."""
    from localharness.orchestrator import worker_skill_catalog
    skills = {n: v["description"] for n, v in worker_skill_catalog().items()}
    configured = settings.load(store).get("mcp_servers") or {}
    mcps = {n: str(c.get("description") or "añadido por ti") for n, c in configured.items()}
    for e in library.mcp_library(configured):
        if e["id"] not in mcps and not e.get("params") and e.get("available") and not e.get("added_as"):
            mcps[e["id"]] = e.get("description", "")
    return {"skills": skills, "mcps": mcps}


def heuristic(request: str, cat: dict, local_ready: bool) -> dict:
    """Sin Claude: reglas sencillas por palabras clave. Siempre devuelve algo usable."""
    r = request.lower()
    ask = bool(re.search(r"\b(explica|qué hace|que hace|resume|revisa|analiza|investiga|compara|por qué|cómo funciona)\b", r))
    change = bool(re.search(r"\b(arregla|corrige|añade|crea|implementa|cambia|refactoriza|escribe|actualiza|elimina|test)", r))
    read_only = ask and not change
    web = bool(re.search(r"\b(documentación|docs|versión|internet|web|librería|api de)\b", r))
    want = []
    for key, names in ((r"\b(error|fallo|bug|arregla|corrige)", ["depurar-sistematico", "tests-primero"]),
                       (r"\btest", ["tests-unitarios", "tdd"]), (r"refactor", ["refactor-seguro"]),
                       (r"\b(seguridad|vulnerab)", ["revision-de-seguridad"]), (r"\b(sql|base de datos)", ["sql-seguro"]),
                       (r"\b(vue|componente)", ["componentes-vue"]), (r"\b(readme|documenta)", ["readme"]),
                       (r"\b(revisa|review)", ["revision-de-diff"])):
        if re.search(key, r):
            want += names
    if change:
        want.append("cambios-minimos")
    skills = [s for s in dict.fromkeys(want) if s in cat["skills"]][:4]
    coordinator = local_ready and change and not read_only
    mcps = [m for m in ("context7", "fetch") if web and m in cat["mcps"]][:1]
    return {"name": _slug(request), "description": request[:120], "provider": "claude",
            "model": "haiku" if read_only else "sonnet", "coordinator": coordinator, "read_only": read_only,
            "web": web and not mcps, "thinking": "normal", "skills": [] if coordinator else skills,
            "local_skills": skills if coordinator else [], "mcps": mcps, "max_turns": 10 if read_only else 20,
            "instructions": "", "reason": "Diseño por reglas (Claude no respondió): "
            + ("solo lectura; " if read_only else "cambia código; ")
            + ("coordina al modelo local; " if coordinator else "") + (f"skills: {', '.join(skills)}" if skills else "sin skills")}


def _slug(text: str) -> str:
    words = re.findall(r"[a-záéíóúñü0-9]+", text.lower())
    stop = {"el", "la", "los", "las", "de", "del", "en", "y", "a", "que", "un", "una", "por", "para", "con", "al", "lo", "me", "quiero"}
    s = "-".join(w for w in words if w not in stop)[:28].strip("-")
    tr = str.maketrans("áéíóúñü", "aeiouny")
    return s.translate(tr) or "agente"


def normalize(spec: dict, cat: dict, local_ready: bool) -> dict:
    """Solo lo que existe y combinaciones coherentes (un agente local no coordina ni lleva MCP, etc.)."""
    s = dict(spec or {})
    provider = s.get("provider") if s.get("provider") in ("claude", "local_agent") else "claude"
    if provider == "local_agent" and not local_ready:
        provider = "claude"  # sin modelo arrancado no trabajaría
    pick = lambda xs, pool, n: [x for x in dict.fromkeys(xs or []) if isinstance(x, str) and x in pool][:n]  # noqa: E731
    read_only = bool(s.get("read_only"))
    coordinator = provider == "claude" and local_ready and bool(s.get("coordinator")) and not read_only
    out = {
        "name": _slug(str(s.get("name") or s.get("description") or "agente")),
        "description": str(s.get("description") or "")[:300],
        "provider": provider,
        "model": (s.get("model") if s.get("model") in MODELS else "sonnet") if provider == "claude" else None,
        "coordinator": coordinator,
        "delegate_local": coordinator,
        "read_only": read_only,
        "web": bool(s.get("web")),
        "thinking": s.get("thinking") if s.get("thinking") in ("apagado", "normal", "profundo") else "normal",
        "skills": pick(s.get("skills"), cat["skills"], 4),
        "local_skills": pick(s.get("local_skills"), cat["skills"], 4) if coordinator else [],
        "mcps": pick(s.get("mcps"), cat["mcps"], 2) if provider == "claude" else [],
        "max_turns": max(5, min(40, int(s.get("max_turns") or 15))),
        "instructions": str(s.get("instructions") or "")[:2000],
        "reason": str(s.get("reason") or "")[:1200],
    }
    if provider == "claude":
        out["max_budget_usd"] = {"haiku": 0.3, "sonnet": 1.0, "opus": 3.0}[out["model"]]
    return out


async def design(store: Store, request: str, project: dict, *, binary: str | None = None,
                 local_ready: bool = False, local_model: str | None = None) -> dict:
    """Propuesta de agente para `request`. Nunca lanza: si Claude falla, reglas."""
    cat = catalog(store)
    prompt = PROMPT.format(
        request=request.strip()[:4000], project=project["name"], files=_files(project["repo_path"]),
        local=f"sí ({local_model})" if local_ready and local_model else "sí" if local_ready else "NO (no elijas local_agent ni coordinator)",
        skills="\n".join(f"  - {n}: {d[:110]}" for n, d in sorted(cat["skills"].items())) or "  (ninguna)",
        mcps="\n".join(f"  - {n}: {d[:110]}" for n, d in sorted(cat["mcps"].items())) or "  (ninguno)")
    cost = 0.0
    got: dict | None = None
    try:
        adapter = get_adapter("claude", binary=binary)
        spec = RunSpec(prompt=prompt, cwd=project["repo_path"], model="haiku", read_only=True, max_turns=3,
                       max_budget_usd=0.15, json_schema=SCHEMA, allowed_tools=["Read", "Glob"])
        seen: dict = {"cost": 0.0}

        def collect(ev: Event) -> None:
            if ev.kind == "usage" and ev.data.get("cost_usd") is not None:
                seen["cost"] = ev.data["cost_usd"]
        res = await run(adapter, spec, collect, timeout_s=180)
        cost = seen["cost"]
        got = res.get("structured") or _json(res.get("final"))
        if res["status"] != "done":
            got = None
    except Exception:  # noqa: BLE001 — sin CLI, sin login…: el diseño por reglas siempre funciona
        got = None
    by = "claude" if got else "reglas"
    spec = normalize(got if got else heuristic(request, cat, local_ready), cat, local_ready)
    return {**spec, "designed_by": by, "design_cost_usd": round(cost, 4)}


def _json(text: str | None) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    try:
        v = json.loads(m.group(0)) if m else None
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


def unique_name(store: Store, base: str) -> str:
    name, n = base, 2
    while store.find_agent(name):
        name, n = f"{base}-{n}", n + 1
    return name


def create_agent(store: Store, spec: dict, request: str) -> dict:
    """Guarda la propuesta como agente (marcado `generated`: hecho para una tarea, no un rol fijo)."""
    keys = ("max_turns", "max_budget_usd", "read_only", "skills", "local_skills", "mcps", "web", "thinking",
            "coordinator", "delegate_local", "instructions", "description")
    cfg = {k: spec[k] for k in keys if spec.get(k) not in (None, [], "", False)}
    if spec.get("web") is False and spec.get("provider") == "local_agent":
        cfg["web"] = False
    cfg.update(generated=True, designed_for=request[:300], design_reason=spec.get("reason") or "",
               designed_by=spec.get("designed_by") or "")
    name = unique_name(store, spec.get("name") or "agente")
    return store.add_agent(name, spec["provider"], model=spec.get("model"), role="trabajador", config=cfg)
