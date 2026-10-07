"""M3 — mando jerárquico: Director → plan JSON → trabajadores en serie → jefe técnico → tú.

Un plan trabaja en UNA rama (`localharness/plan-N`) y en un único worktree. Cada subtarea se ejecuta encima de
la anterior y deja su propio commit, así que cada paso tiene su diff revisable (base_commit..head_commit).

Niveles (policy.py): el nivel de cada subtarea es el máximo entre el riesgo que declara el Director, el que
calculan las reglas sobre el diff y lo que pida el jefe técnico. N1 lo aprueba el jefe técnico; N2 te llega a ti
y el plan se para hasta que decidas. Integrar la rama del plan en la tuya es siempre tuyo (N2) y nunca hay push.
"""

import json
from pathlib import Path
from collections.abc import Callable

from localharness import settings, workspace
from localharness.actions import ActionError, now
from localharness.adapters import ADAPTERS
from localharness.adapters.base import THINKING_LEVELS
from localharness.context import load_skills
from localharness.events import Event
from localharness.orchestrator import execute_task
from localharness.roles import sync_roles
from localharness.policy import N0, N1, N2, LEVEL_NAME, RISK_LEVEL, Policy, assess_changes, combine
from localharness.store import Store

RISKS = ["low", "medium", "high"]

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "risk": {"type": "string", "enum": RISKS},
        "subtasks": {
            "type": "array", "minItems": 1, "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "prompt": {"type": "string"},
                    "agent": {"type": "string"},
                    "risk": {"type": "string", "enum": RISKS},
                    "skills": {"type": "array", "items": {"type": "string"}},
                    "thinking": {"type": "string", "enum": list(THINKING_LEVELS)},
                },
                "required": ["title", "prompt", "agent", "risk"],
            },
        },
    },
    "required": ["summary", "risk", "subtasks"],
}

STEP_SCHEMA = {  # «rehacer este paso»: el Director devuelve SOLO la subtarea nueva
    "type": "object",
    "properties": {"subtask": PLAN_SCHEMA["properties"]["subtasks"]["items"]},
    "required": ["subtask"],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "request_changes", "escalate"]},
        "risk": {"type": "string", "enum": RISKS},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "risk", "reason"],
}

STEP_KEYS = ("title", "prompt", "agent", "risk", "skills", "thinking")
MAX_DIFF_FOR_REVIEW = 60_000  # caracteres: un diff más grande ya es N2 por reglas


class PlanError(Exception):
    pass


def director_prompt(request: str, agents: list[dict], skills: dict | None = None) -> str:
    catalog = "\n".join(f"- `{s.name}`: {s.description}" for s in (skills or {}).values()) or "(ninguna)"
    lines = "\n".join(f"- `{a['name']}`: proveedor {a['provider']}, modelo {a['model'] or 'por defecto'}, "
                      f"rol {a['role'] or 'trabajador'}" + _desc(a) for a in agents)
    return f"""Eres el Director (planificador jefe) de un equipo de agentes de programación. NO modificas archivos:
puedes leer el repositorio (directorio actual) para entenderlo y devolver un plan.

PETICIÓN DEL USUARIO:
{request}

AGENTES DISPONIBLES (elige SOLO entre estos, por su nombre exacto):
{lines}

SKILLS DISPONIBLES (procedimientos que se inyectan al agente; pon en `skills` las útiles para cada subtarea,
por su nombre exacto, o ninguna):
{catalog}

{director_manual()}"""


MANUAL = Path(__file__).resolve().parent.parent / "manual" / "director.md"
FALLBACK_MANUAL = """Reglas del plan:
- Divide la petición en subtareas pequeñas y verificables que se ejecutarán EN ORDEN sobre la misma rama.
- El `prompt` de cada subtarea debe ser autocontenido: el agente no verá esta conversación.
- Riesgo: low (pequeño y local), medium (lógica no trivial o varios archivos), high (borra, dependencias,
  migraciones, configuración/CI, secretos o cambios grandes). `risk` global: el mayor de las subtareas.
- No incluyas pasos de git (commit/push/merge): de eso se encarga el sistema."""


def director_manual() -> str:
    """El «algoritmo» del Director vive en manual/director.md (editable sin tocar código)."""
    try:
        text = MANUAL.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    return text or FALLBACK_MANUAL


def _desc(agent: dict) -> str:
    d = json.loads(agent.get("config") or "{}").get("description")
    return f". {d}" if d else ""


def redo_prompt(plan_data: dict, seq: int, comment: str) -> str:
    steps = "\n".join(f"{i}. {x['title']} ({x['agent']}, riesgo {x['risk']})"
                      for i, x in enumerate(plan_data["subtasks"], 1))
    return f"""El humano ha revisado tu plan y quiere que REHAGAS SOLO el paso {seq}. Los demás se quedan igual.

PLAN ACTUAL:
{steps}

PASO {seq} ACTUAL:
{json.dumps({k: v for k, v in plan_data["subtasks"][seq - 1].items() if k != "agent_id"}, ensure_ascii=False, indent=2)}

LO QUE PIDE EL HUMANO:
{comment}

Devuelve la subtarea nueva para el paso {seq} (mismas reglas que el plan: prompt autocontenido con cómo se
comprueba, agente por su nombre exacto, riesgo y skills). NO modificas archivos."""


def reviewer_prompt(request: str, subtask: dict, diff: str, reasons: list[str]) -> str:
    return f"""Eres el jefe técnico. Revisa el diff de una subtarea hecha por otro agente. NO modificas archivos.

PETICIÓN ORIGINAL: {request}
SUBTAREA: {subtask['title']}
INSTRUCCIONES QUE RECIBIÓ: {subtask['prompt']}
REGLAS AUTOMÁTICAS: {'; '.join(reasons)}

DIFF:
```diff
{diff}
```

Decide:
- approve: el diff hace lo pedido, es correcto y de riesgo bajo/medio.
- request_changes: hay errores claros (explica cuáles en `reason`).
- escalate: es correcto pero arriesgado o dudoso; debe decidirlo el humano.
`risk` es tu estimación del riesgo del cambio. Sé concreto y breve en `reason`."""


def validate_plan(data: dict | None, agents: list[dict], skills: dict | None = None) -> dict:
    """Validación propia (además de --json-schema): estructura y agentes existentes."""
    if not isinstance(data, dict):
        raise PlanError("El Director no devolvió un plan estructurado")
    subtasks = data.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        raise PlanError("El plan no tiene subtareas")
    by_name = {a["name"]: a for a in agents}
    for i, s in enumerate(subtasks, 1):
        for k in ("title", "prompt", "agent", "risk"):
            if not isinstance(s.get(k), str) or not s[k].strip():
                raise PlanError(f"Subtarea {i}: falta '{k}'")
        if s["agent"] not in by_name:  # el Director solo elige, no crea agentes (§7.3)
            raise PlanError(f"Subtarea {i}: agente desconocido {s['agent']!r} (hay: {', '.join(by_name)})")
        if s["risk"] not in RISKS:
            raise PlanError(f"Subtarea {i}: riesgo inválido {s['risk']!r}")
        s["agent_id"] = by_name[s["agent"]]["id"]
        asked = s.get("skills") if isinstance(s.get("skills"), list) else []
        s["skills"] = [n for n in asked if isinstance(n, str) and n in (skills or {})]  # nombres inventados fuera
        if s.get("thinking") not in THINKING_LEVELS:
            s.pop("thinking", None)
    if data.get("risk") not in RISKS:
        data["risk"] = max((s["risk"] for s in subtasks), key=RISKS.index)
    return data


def plan_level(plan: dict, policy: Policy) -> tuple[int, list[str]]:
    reasons, level = [], RISK_LEVEL[plan["risk"]]
    n = len(plan["subtasks"])
    if n > policy.max_auto_subtasks:
        reasons.append(f"plan grande: {n} subtareas (> {policy.max_auto_subtasks})")
        level = N2
    high = [s["title"] for s in plan["subtasks"] if s["risk"] == "high"]
    if high:
        reasons.append(f"subtareas de riesgo alto: {', '.join(high[:3])}")
        level = N2
    if plan["risk"] == "high" and not high:
        reasons.append("el Director marca el plan como de riesgo alto")
    if not reasons:
        reasons.append(f"{n} subtarea(s), riesgo declarado {plan['risk']}")
    return level, reasons


class Hierarchy:
    """Ejecuta planes. Lo usan la API (con su hub de eventos) y las pruebas."""

    def __init__(self, store: Store, *, on_event: Callable[[int, Event], None] | None = None,
                 on_plan: Callable[[int], None] | None = None, binaries: dict[str, str] | None = None,
                 worktree_root: str | None = None, policy: Policy | None = None):
        self.store, self.binaries, self.worktree_root = store, binaries, worktree_root
        self._on_event, self._on_plan = on_event, on_plan
        self.policy = policy or settings.policy(store)

    # --- utilidades
    def _emit(self, tid: int, ev: Event) -> None:
        if self._on_event:
            self._on_event(tid, ev)

    def _plan_changed(self, pid: int) -> None:
        if self._on_plan:
            self._on_plan(pid)

    def _set(self, pid: int, **f) -> None:
        self.store.update_plan(pid, **f)
        self._plan_changed(pid)

    def _ws(self, plan: dict) -> workspace.Workspace:
        project = self.store.get_project(plan["project_id"])
        return workspace.Workspace(Path(project["repo_path"]), Path(plan["worktree"]),
                                   plan["branch"], plan["base_commit"])

    def _new_task(self, plan: dict, title: str, prompt: str, agent_id: int, seq: int, kind: str) -> dict:
        t = self.store.add_task(plan["project_id"], title[:80], prompt, agent_id)
        self.store.update_task(t["id"], plan_id=plan["id"], seq=seq, kind=kind)
        return self.store.get_task(t["id"])

    def _total_cost(self, pid: int) -> float:
        return round(sum(t["cost_usd"] or 0 for t in self.store.plan_tasks(pid)), 6)

    # --- 1. planificar
    async def plan(self, pid: int) -> dict:
        plan = self.store.get_plan(pid)
        project = self.store.get_project(plan["project_id"])
        if settings.load(self.store).get("roles_autosync"):
            sync_roles(self.store)  # los roles de roles/*.md, al día (también desde la CLI, sin servidor)
        workers = self._workers(plan)
        if not workers:  # sin agentes fijos: uno diseñado a medida para la petición del plan
            from localharness import designer
            spec = await designer.design(self.store, plan["request"], project,
                                         binary=(self.binaries or {}).get("claude"))
            designer.create_agent(self.store, {**spec, "coordinator": False, "delegate_local": False,
                                               "read_only": False}, plan["request"])
            workers = self._workers(plan)
        if not workers:
            return self._fail(pid, "No hay agentes capaces de modificar archivos (claude/codex) para las subtareas")
        ws = workspace.create(project["repo_path"], f"plan-{pid}", self.worktree_root)
        self._set(pid, status="planning", branch=ws.branch, worktree=str(ws.path), base_commit=ws.base)
        plan = self.store.get_plan(pid)
        catalog = load_skills()
        d = self._new_task(plan, f"Plan: {plan['request']}", director_prompt(plan["request"], workers, catalog),
                           plan["director_agent_id"], 0, "director")
        res = await execute_task(self.store, d["id"], binaries=self.binaries, on_event=self._emit, ws=ws,
                                 json_schema=PLAN_SCHEMA, read_only=True)
        if res["status"] not in ("review", "done"):
            return self._fail(pid, f"El Director falló ({res['status']})")
        self.store.update_task(d["id"], status="done", level=LEVEL_NAME[N0])
        self._emit(d["id"], Event("status", text="done"))
        try:
            data = validate_plan(res.get("structured") or _json_or_none(res.get("final")), workers, catalog)
        except PlanError as e:
            return self._fail(pid, str(e))
        self._store_plan(pid, data)
        return self.store.get_plan(pid)

    def _workers(self, plan: dict) -> list[dict]:
        """Trabajadores: solo agentes capaces de modificar archivos (`local` no lo es; `local_agent` sí) y que no
        estén fuera de servicio (los quitaste de la oficina)."""
        writers = [a for a in self.store.list_agents() if ADAPTERS[a["provider"]].can_write
                   and not json.loads(a.get("config") or "{}").get("off")]
        others = [a for a in writers if a["id"] not in (plan["director_agent_id"], plan["reviewer_agent_id"])]
        return others or writers

    def _store_plan(self, pid: int, data: dict, extra_reasons: list[str] | None = None) -> None:
        """Guarda el plan validado: sus pasos como tareas pendientes, el nivel y si te espera a ti."""
        for t in self.store.plan_tasks(pid):  # al editar: los pasos anteriores (aún sin ejecutar) se sustituyen
            if t["kind"] == "worker" and t["status"] == "pending":
                self.store.delete_task(t["id"])
        level, reasons = plan_level(data, self.policy)
        reasons += extra_reasons or []
        for i, s in enumerate(data["subtasks"], 1):
            t = self._new_task(self.store.get_plan(pid), s["title"], s["prompt"], s["agent_id"], i, "worker")
            if s["skills"]:
                self.store.update_task(t["id"], skills=s["skills"])
            if s.get("thinking"):
                self.store.update_task(t["id"], thinking=s["thinking"])
            # SQLite reutiliza los ids de los pasos borrados al editar: se anuncia cada paso para que la GUI no
            # mezcle el nuevo con lo que tenía guardado del anterior
            self._emit(t["id"], Event("status", text="pending"))
        review = settings.load(self.store)["plans"]["always_review"]
        if review and level != N2:
            reasons.append("revisas siempre el plan antes de empezar (Ajustes → Aprobaciones → Planes)")
        status = "awaiting_you" if level == N2 or review else "approved"
        self._set(pid, plan=data, level=LEVEL_NAME[level], level_reasons=reasons, status=status,
                  cost_usd=self._total_cost(pid))

    # --- 1b. tú revisas el plan antes de empezar: editar pasos o pedir al Director que rehaga uno
    def edit_plan(self, pid: int, subtasks: list[dict]) -> dict:
        plan = self._get(pid)
        if plan["status"] != "awaiting_you":
            raise ActionError(f"Solo se edita un plan que espera tu aprobación (está en '{plan['status']}')")
        old = json.loads(plan["plan"] or "{}")
        data = {"summary": old.get("summary", ""), "risk": None,
                "subtasks": [{k: s.get(k) for k in STEP_KEYS} for s in subtasks]}
        try:
            data = validate_plan(data, self._workers(plan), load_skills())
        except PlanError as e:
            raise ActionError(str(e)) from None
        self._store_plan(pid, data, ["plan editado por ti"])
        return self.store.get_plan(pid)

    async def redo_step(self, pid: int, seq: int, comment: str) -> dict:
        plan = self._get(pid)
        if plan["status"] != "awaiting_you":
            raise ActionError(f"Solo se rehace un paso de un plan que espera tu aprobación (está en '{plan['status']}')")
        data = json.loads(plan["plan"] or "{}")
        if not 1 <= seq <= len(data.get("subtasks") or []):
            raise ActionError(f"El plan no tiene paso {seq}")
        if not comment.strip():
            raise ActionError("Di qué quieres cambiar en el paso")
        d = next((t for t in self.store.plan_tasks(pid) if t["kind"] == "director"), None)
        if not d:
            raise ActionError("El plan no tiene Director al que pedírselo")
        self._set(pid, status="planning", error=None)
        try:
            res = await execute_task(self.store, d["id"], binaries=self.binaries, on_event=self._emit,
                                     json_schema=STEP_SCHEMA, read_only=True,
                                     followup=redo_prompt(data, seq, comment))
            self.store.update_task(d["id"], status="done")
            got = res.get("structured") or _json_or_none(res.get("final")) or {}
            new = got.get("subtask") if isinstance(got, dict) else None
            if res["status"] not in ("review", "done") or not isinstance(new, dict):
                raise ActionError("El Director no devolvió el paso rehecho")
            steps = [{k: x.get(k) for k in STEP_KEYS} for x in data["subtasks"]]
            steps[seq - 1] = new
            candidate = {"summary": data.get("summary", ""), "risk": None, "subtasks": steps}
            try:
                candidate = validate_plan(candidate, self._workers(plan), load_skills())
            except PlanError as e:
                raise ActionError(f"El paso rehecho no es válido: {e}") from None
        except BaseException as e:
            self._set(pid, status="awaiting_you", error=str(e) if isinstance(e, ActionError) else None,
                      cost_usd=self._total_cost(pid))
            raise
        self._store_plan(pid, candidate, [f"paso {seq} rehecho por el Director: {comment[:120]}"])
        return self.store.get_plan(pid)

    def _fail(self, pid: int, msg: str) -> dict:
        close_pending(self.store, pid)
        self._set(pid, status="failed", error=msg, finished_at=now(), cost_usd=self._total_cost(pid))
        return self.store.get_plan(pid)

    # --- 2. ejecutar (o reanudar tras tu decisión)
    async def run(self, pid: int) -> dict:
        plan = self.store.get_plan(pid)
        if plan["status"] not in ("approved", "paused"):
            raise ActionError(f"El plan no está listo para ejecutarse (está en '{plan['status']}')")
        self._set(pid, status="running")
        plan = self.store.get_plan(pid)
        ws = self._ws(plan)
        data = json.loads(plan["plan"])
        reviewer = self.store.get_agent(plan["reviewer_agent_id"]) if plan["reviewer_agent_id"] else None
        for t in self.store.plan_tasks(pid):
            if t["kind"] != "worker" or t["status"] != "pending":
                continue
            sub = data["subtasks"][t["seq"] - 1]
            res = await execute_task(self.store, t["id"], binaries=self.binaries, on_event=self._emit, ws=ws)
            if res["status"] not in ("review", "done"):
                return self._pause(pid, f"La subtarea {t['seq']} terminó en '{res['status']}'", failed=True)
            rules = assess_changes(res["changes"], self.policy)
            if not res["changes"]:
                self._decide(t["id"], "done", N0, rules.reasons)
                continue
            level = combine(rules.level, RISK_LEVEL[sub["risk"]])
            reasons = rules.reasons + ([f"riesgo declarado: {sub['risk']}"] if RISK_LEVEL[sub["risk"]] else [])
            if level == N1 and reviewer:
                verdict = await self._review(plan, t, sub, res["diff"], reasons, reviewer, ws)
                self.store.update_task(t["id"], review=verdict)
                if verdict.get("verdict") == "approve" and RISK_LEVEL.get(verdict.get("risk"), N2) <= N1:
                    self._decide(t["id"], "approved", N1, reasons + [f"jefe técnico: {verdict.get('reason', '')}"],
                                 approved_by=reviewer["name"])
                    continue
                level = N2  # el revisor solo puede subir el nivel
                reasons.append(f"jefe técnico ({verdict.get('verdict', 'sin veredicto')}): {verdict.get('reason', '')}")
            elif level == N1:
                level = N2
                reasons.append("no hay jefe técnico asignado: decides tú")
            self._decide(t["id"], "review", level, reasons)
            return self._pause(pid, f"La subtarea {t['seq']} necesita tu decisión ({LEVEL_NAME[level]})")
        if not any(t["kind"] == "worker" and t["status"] == "approved" for t in self.store.plan_tasks(pid)):
            # nada que integrar (consultas o subtareas sin cambios/rechazadas): se cierra y se limpia la rama
            try:
                ws.remove()
            except workspace.GitError:
                pass
            self._set(pid, status="done", finished_at=now(), cost_usd=self._total_cost(pid))
            return self.store.get_plan(pid)
        self._set(pid, status="ready", cost_usd=self._total_cost(pid))  # integrar la rama: siempre tú
        return self.store.get_plan(pid)

    async def _review(self, plan: dict, task: dict, sub: dict, diff: str, reasons: list[str], reviewer: dict,
                      ws: workspace.Workspace) -> dict:
        if len(diff) > MAX_DIFF_FOR_REVIEW:
            return {"verdict": "escalate", "risk": "high", "reason": "diff demasiado grande para revisarlo"}
        r = self._new_task(plan, f"Revisión: {task['title']}", reviewer_prompt(plan["request"], sub, diff, reasons),
                           reviewer["id"], task["seq"], "reviewer")
        res = await execute_task(self.store, r["id"], binaries=self.binaries, on_event=self._emit, ws=ws,
                                 json_schema=REVIEW_SCHEMA, read_only=True)
        verdict = res.get("structured") or _json_or_none(res.get("final"))
        ok = res["status"] in ("review", "done") and isinstance(verdict, dict) and verdict.get("verdict")
        self.store.update_task(r["id"], status="done" if ok else "failed", level=LEVEL_NAME[N0])
        self._emit(r["id"], Event("status", text="done" if ok else "failed"))
        if res.get("changes"):  # un revisor de solo lectura no debería cambiar nada; si pasa, se escala
            return {"verdict": "escalate", "risk": "high", "reason": "el revisor modificó archivos"}
        return verdict if ok else {"verdict": "escalate", "risk": "high", "reason": "el revisor no dio veredicto"}

    def _decide(self, tid: int, status: str, level: int, reasons: list[str], approved_by: str | None = None) -> None:
        self.store.update_task(tid, status=status, level=LEVEL_NAME[level], level_reasons=reasons,
                               approved_by=approved_by)
        self._emit(tid, Event("status", text=status, data={"level": LEVEL_NAME[level], "reasons": reasons}))

    def _pause(self, pid: int, msg: str, failed: bool = False) -> dict:
        if failed:
            close_pending(self.store, pid)
        self._set(pid, status="failed" if failed else "paused", error=msg, cost_usd=self._total_cost(pid))
        return self.store.get_plan(pid)

    # --- 3. tus decisiones
    def approve_plan(self, pid: int) -> dict:
        plan = self._get(pid)
        if plan["status"] != "awaiting_you":
            raise ActionError(f"El plan no espera tu aprobación (está en '{plan['status']}')")
        self._set(pid, status="approved", error=None)
        return self.store.get_plan(pid)

    def decide_task(self, tid: int, approve: bool) -> dict:
        """Tu decisión sobre una subtarea parada (N2). Rechazar deshace SU commit (es la punta de la rama)."""
        task = self.store.get_task(tid)
        plan = self._get(task["plan_id"]) if task and task["plan_id"] else None
        if not plan or plan["status"] != "paused" or task["status"] != "review":
            raise ActionError("Solo se decide una subtarea en revisión de un plan parado")
        if approve:
            self.store.update_task(tid, status="approved", approved_by="tú")
        else:
            ws = self._ws(plan)
            if ws.head() != task["head_commit"]:
                raise ActionError("La rama del plan ha cambiado: no se puede deshacer esta subtarea con seguridad")
            workspace.git(ws.path, "reset", "-q", "--hard", task["base_commit"])
            self.store.update_task(tid, status="rejected")
        self._emit(tid, Event("status", text=self.store.get_task(tid)["status"]))
        self._set(task["plan_id"], error=None)
        return self.store.get_task(tid)

    def reject_plan(self, pid: int) -> dict:
        plan = self._get(pid)
        if plan["status"] in ("planning", "running", "merged"):
            raise ActionError(f"No se puede rechazar un plan en '{plan['status']}'")
        if plan["worktree"]:
            try:
                self._ws(plan).remove()
            except workspace.GitError:
                pass
        for t in self.store.plan_tasks(pid):
            if t["status"] in ("pending", "review", "approved"):
                self.store.update_task(t["id"], status="rejected")
        self._set(pid, status="rejected", finished_at=now())
        return self.store.get_plan(pid)

    def merge_plan(self, pid: int) -> dict:
        plan = self._get(pid)
        if plan["status"] != "ready":
            raise ActionError(f"Solo se integra un plan terminado (está en '{plan['status']}')")
        ws = self._ws(plan)
        try:
            ws.merge()
            ws.remove()
        except workspace.GitError as e:
            raise ActionError(str(e)) from None
        for t in self.store.plan_tasks(pid):
            if t["status"] == "approved":
                self.store.update_task(t["id"], status="merged")
        self._set(pid, status="merged", finished_at=now())
        return self.store.get_plan(pid)

    def _get(self, pid: int) -> dict:
        plan = self.store.get_plan(pid)
        if not plan:
            raise ActionError(f"No existe el plan #{pid}")
        return plan


def close_pending(store: Store, pid: int, status: str = "cancelled") -> int:
    """Un plan que termina mal (fallido, cancelado, interrumpido) no ejecutará sus subtareas pendientes:
    se cierran para que no se queden «pendientes» para siempre."""
    n = 0
    for t in store.plan_tasks(pid):
        if t["status"] == "pending":
            store.update_task(t["id"], status=status, finished_at=now())
            n += 1
    return n


def inbox(store: Store) -> list[dict]:
    """Bandeja «pendiente de ti»: planes a aprobar, subtareas N2 paradas, planes listos para integrar."""
    items = []
    for p in store.list_plans():
        if p["status"] == "awaiting_you":
            items.append({"type": "plan_approval", "plan_id": p["id"], "title": p["request"][:80],
                          "level": p["level"], "reasons": json.loads(p["level_reasons"] or "[]")})
        elif p["status"] == "ready":
            items.append({"type": "plan_merge", "plan_id": p["id"], "title": p["request"][:80], "level": "N2",
                          "reasons": ["integrar en tu rama principal siempre lo decides tú"]})
        elif p["status"] == "paused":
            for t in store.plan_tasks(p["id"]):
                if t["status"] == "review":
                    items.append({"type": "task_decision", "plan_id": p["id"], "task_id": t["id"],
                                  "title": t["title"], "level": t["level"],
                                  "reasons": json.loads(t["level_reasons"] or "[]")})
    for t in store.list_tasks():
        if t["plan_id"] is None and t["status"] in ("review", "approved"):
            items.append({"type": "task_review", "task_id": t["id"], "title": t["title"], "level": "N2",
                          "reasons": ["tarea suelta: revisa e integra tú"]})
    return items


def _json_or_none(text: str | None) -> dict | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    try:
        v = json.loads(text)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None
