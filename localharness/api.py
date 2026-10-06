"""API de M2: FastAPI + SSE. Un único proceso: el bucle de asyncio ejecuta las tareas y emite sus eventos.

    .venv/Scripts/python -m localharness serve        # http://127.0.0.1:8095

Solo escucha en 127.0.0.1 por defecto: no hay autenticación (acceso por LAN es una fase posterior).
"""

import asyncio
import json
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from localharness import actions, llama, maintenance, settings, workspace
from localharness.adapters import ADAPTERS
from localharness.context import load_skills
from localharness.events import Event
from localharness.hierarchy import Hierarchy, close_pending, inbox
from localharness.hub import EventHub, sse_format
from localharness.orchestrator import execute_task
from localharness.store import Store

__version__ = "0.1.0"
SSE_HEARTBEAT_S = 15.0
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    repo_path: str = Field(min_length=1)
    init_git: bool = False  # carpeta sin git: `git init` + commit inicial (solo si lo pides)


class LlamaStartIn(BaseModel):
    path: str
    ctx: int | None = Field(default=None, ge=512, le=1_048_576)
    ngl: int | None = Field(default=None, ge=0, le=999)


class PickIn(BaseModel):
    kind: str = "folder"  # folder | file (el exe de llama-server)
    title: str | None = None


class ReplyIn(BaseModel):
    message: str = Field(min_length=1)


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    provider: str = "claude"
    model: str | None = None
    role: str | None = None
    max_turns: int | None = Field(default=None, ge=1, le=200)
    max_budget_usd: float | None = Field(default=None, gt=0)
    read_only: bool = False
    tools: list[str] | None = None
    skills: list[str] | None = None
    base_url: str | None = None  # solo proveedor local
    description: str | None = None  # en qué es bueno: el Director lo lee para repartir subtareas
    subagents: bool = False  # solo claude: puede lanzar subagentes (herramienta Agent; gasta más)
    temperature: float | None = Field(default=None, ge=0, le=2)  # solo local
    max_tokens: int | None = Field(default=None, ge=64, le=131_072)  # solo local
    repo_context: int | None = Field(default=None, ge=0, le=2_000_000)  # solo local: caracteres del repo


class AgentPatch(BaseModel):
    """Edición desde Ajustes: solo cambian los campos enviados (null en un límite = quitarlo)."""
    model: str | None = None
    role: str | None = None
    max_turns: int | None = Field(default=None, ge=1, le=200)
    max_budget_usd: float | None = Field(default=None, gt=0)
    read_only: bool | None = None
    skills: list[str] | None = None
    base_url: str | None = None
    description: str | None = None
    subagents: bool | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=64, le=131_072)
    repo_context: int | None = Field(default=None, ge=0, le=2_000_000)


AGENT_CFG = ("max_turns", "max_budget_usd", "read_only", "skills", "base_url", "description", "subagents",
             "temperature", "max_tokens", "repo_context")


class ProjectPatch(BaseModel):
    memory_dir: str | None = None


class TaskIn(BaseModel):
    project_id: int
    agent_id: int
    prompt: str = Field(min_length=1)
    title: str | None = None
    start: bool = True
    skills: list[str] | None = None  # M5: skills inyectadas solo en esta tarea (además de las del agente)


class MergeIn(BaseModel):
    confirm: bool = False  # la GUI lo manda tras tu confirmación explícita


class PlanIn(BaseModel):
    project_id: int
    request: str = Field(min_length=1)
    director_agent_id: int
    reviewer_agent_id: int | None = None


class DecideIn(BaseModel):
    approve: bool


class Runner:
    """Tareas en marcha en este proceso (para cancelar y para saber qué está vivo)."""

    def __init__(self, store: Store, hub: EventHub, binaries: dict[str, str] | None,
                 worktree_root: str | None):
        self.store, self.hub, self.binaries, self.worktree_root = store, hub, binaries, worktree_root
        self.active: dict[int, asyncio.Task] = {}
        self.plans: dict[int, asyncio.Task] = {}
        self.hier = Hierarchy(store, on_event=self.on_event, on_plan=self.publish_plan, binaries=binaries,
                              worktree_root=worktree_root)
        self.last_limit = _last_limit(store)  # último uso del plan conocido (evento rate_limit_event)
        self.last_speed: dict | None = None    # última velocidad de un modelo local (tokens/s)

    def publish_task(self, tid: int) -> None:
        t = self.store.get_task(tid)
        if t:
            self.hub.publish("task", task_out(t))

    def publish_plan(self, pid: int) -> None:
        p = self.store.get_plan(pid)
        if p:
            self.hub.publish("plan", plan_out(p))

    def run_plan(self, pid: int, plan_first: bool) -> None:
        """Planifica (si toca) y ejecuta hasta terminar o hasta necesitar tu decisión."""
        async def go() -> None:
            try:
                p = await self.hier.plan(pid) if plan_first else self.store.get_plan(pid)
                if p["status"] in ("approved", "paused"):
                    await self.hier.run(pid)
            except asyncio.CancelledError:
                close_pending(self.store, pid)
                self.store.update_plan(pid, status="cancelled", finished_at=actions.now())
            except Exception as e:  # noqa: BLE001 — se registra en el plan, no tumba el servidor
                close_pending(self.store, pid)
                self.store.update_plan(pid, status="failed", error=str(e), finished_at=actions.now())
            finally:
                self.plans.pop(pid, None)
                self.publish_plan(pid)

        self.plans[pid] = asyncio.create_task(go())

    def on_event(self, tid: int, ev: Event) -> None:
        self.hub.publish("task_event", {"task_id": tid, **ev.as_dict()})
        if ev.kind in ("status", "session", "usage"):
            self.publish_task(tid)
        if ev.kind == "speed" or (ev.kind == "usage" and ev.data.get("local") and ev.data.get("tps")):
            self.last_speed = {"model": ev.data.get("model"), "tps": ev.data.get("tps"), "task_id": tid,
                               "at": time.time(), "final": ev.kind == "usage"}
        if ev.kind == "limit":
            self.last_limit = ev.data
            self.hub.publish("limit", ev.data)

    def start(self, tid: int, followup: str | None = None) -> None:
        async def go() -> None:
            try:
                await execute_task(self.store, tid, binaries=self.binaries, on_event=self.on_event,
                                   worktree_root=self.worktree_root, followup=followup)
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001 — cualquier fallo se registra en la tarea, no tumba el servidor
                if self.store.get_task(tid)["status"] in ("pending", "running"):
                    self.store.update_task(tid, status="failed", finished_at=actions.now())
                eid = self.store.add_event(tid, "error", str(e))
                self.hub.publish("task_event", {"task_id": tid, "id": eid, "kind": "error", "text": str(e), "data": {}})
            finally:
                self.active.pop(tid, None)
                self.publish_task(tid)

        self.active[tid] = asyncio.create_task(go())

    async def cancel(self, tid: int) -> bool:
        task = self.active.get(tid)
        if not task:
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def cancel_plan(self, pid: int) -> bool:
        task = self.plans.get(pid)
        if not task:
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def shutdown(self) -> None:
        for tid in list(self.active):
            await self.cancel(tid)
        for pid in list(self.plans):
            await self.cancel_plan(pid)


def create_app(db_path: str | Path = ":memory:", *, binaries: dict[str, str] | None = None,
               worktree_root: str | None = None, web_dist: Path | None = WEB_DIST) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = Store(db_path)
        store.mark_interrupted()
        settings.apply(store)
        app.state.store = store
        app.state.hub = EventHub()
        app.state.runner = Runner(store, app.state.hub, binaries, worktree_root)
        log = Path(db_path).parent / "llama-server.log" if str(db_path) != ":memory:" else Path(
            tempfile.gettempdir()) / "localharness-llama-server.log"
        app.state.llama = llama.LlamaManager(log)
        # M6: restos de tareas y planes cerrados (worktrees y ramas) se limpian al arrancar
        try:
            app.state.cleanup = await asyncio.to_thread(maintenance.cleanup, store)
        except Exception as e:  # noqa: BLE001 — una limpieza fallida no impide arrancar
            app.state.cleanup = {"removed": [], "kept": [], "unknown": [], "errors": [str(e)]}
        yield
        await asyncio.to_thread(app.state.llama.stop)  # el llama-server lanzado desde la GUI muere con ella
        await app.state.runner.shutdown()
        store.close()

    app = FastAPI(title="LocalHarness", version=__version__, lifespan=lifespan)

    def st(request: Request) -> Store:
        return request.app.state.store

    def task_or_404(store: Store, tid: int) -> dict:
        t = store.get_task(tid)
        if not t:
            raise HTTPException(404, f"No existe la tarea #{tid}")
        return t

    # --- estado general
    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        port = settings.load(st(request))["llama"]["port"]
        ls = await asyncio.to_thread(request.app.state.llama.status, port)
        return {"version": __version__, "providers": list(ADAPTERS),
                "running": sorted(request.app.state.runner.active), "limit": request.app.state.runner.last_limit,
                # qué modelo responde de verdad a los agentes locales (el arrancado, no el nombre del agente)
                "local": {"state": ls["state"], "model": _model_name(ls.get("model")) if ls["state"] != "off" else None},
                "speed": request.app.state.runner.last_speed}

    # --- proyectos
    @app.get("/api/projects")
    async def projects(request: Request) -> list[dict]:
        return st(request).list_projects()

    @app.post("/api/projects", status_code=201)
    async def add_project(request: Request, body: ProjectIn) -> dict:
        repo = Path(body.repo_path.strip().strip('"')).expanduser().resolve()
        if not repo.is_dir():
            raise HTTPException(422, f"No existe la carpeta {repo}")
        try:
            workspace.git(repo, "rev-parse", "HEAD")
        except (workspace.GitError, OSError):
            if not body.init_git:
                raise HTTPException(422, f"{repo} no es un repo git con al menos un commit "
                                         "(marca «inicializar git» para crearlo)") from None
            try:
                await asyncio.to_thread(workspace.init_repo, repo)
            except (workspace.GitError, OSError) as e:
                raise HTTPException(422, f"No se pudo inicializar git: {e}") from None
        if st(request).find_project(body.name):
            raise HTTPException(409, f"Ya existe un proyecto llamado {body.name!r}")
        try:
            return st(request).add_project(body.name, str(repo))
        except Exception:  # noqa: BLE001 — repo_path es UNIQUE
            raise HTTPException(409, "Ese repo ya está registrado") from None

    # --- agentes
    @app.get("/api/agents")
    async def agents(request: Request) -> list[dict]:
        return [{**a, "config": json.loads(a["config"] or "{}")} for a in st(request).list_agents()]

    @app.post("/api/agents", status_code=201)
    async def add_agent(request: Request, body: AgentIn) -> dict:
        if body.provider not in ADAPTERS:
            raise HTTPException(422, f"Proveedor desconocido: {body.provider}")
        if st(request).find_agent(body.name):
            raise HTTPException(409, f"Ya existe un agente llamado {body.name!r}")
        cfg = {k: v for k, v in {"max_turns": body.max_turns, "max_budget_usd": body.max_budget_usd,
                                 "read_only": body.read_only or None, "tools": body.tools,
                                 "skills": body.skills or None, "base_url": body.base_url or None,
                                 "description": (body.description or "").strip() or None,
                                 "subagents": body.subagents or None, "temperature": body.temperature,
                                 "max_tokens": body.max_tokens, "repo_context": body.repo_context}.items()
               if v is not None}
        a = st(request).add_agent(body.name, body.provider, model=body.model, role=body.role, config=cfg)
        return {**a, "config": cfg}

    @app.patch("/api/agents/{aid}")
    async def edit_agent(request: Request, aid: int, body: AgentPatch) -> dict:
        store = st(request)
        a = store.get_agent(aid)
        if not a:
            raise HTTPException(404, f"No existe el agente #{aid}")
        sent = body.model_fields_set
        cols = {k: getattr(body, k) or None for k in ("model", "role") if k in sent}
        cfg = json.loads(a["config"] or "{}")
        for k in sent & set(AGENT_CFG):
            v = getattr(body, k)
            if v is None or v is False or v == [] or v == "":  # 0 es válido (repo_context = 0: sin contexto)
                cfg.pop(k, None)
            else:
                cfg[k] = v
        store.update_agent(aid, **cols, config=cfg)
        a = store.get_agent(aid)
        return {**a, "config": json.loads(a["config"] or "{}")}

    @app.delete("/api/agents/{aid}", status_code=204)
    async def delete_agent(request: Request, aid: int) -> None:
        store = st(request)
        if not store.get_agent(aid):
            raise HTTPException(404, f"No existe el agente #{aid}")
        if store.agent_in_use(aid):
            raise HTTPException(409, "Ese agente tiene tareas o planes en el historial: edítalo en vez de borrarlo")
        store.delete_agent(aid)

    @app.patch("/api/projects/{pid}")
    async def edit_project(request: Request, pid: int, body: ProjectPatch) -> dict:
        store = st(request)
        if not store.get_project(pid):
            raise HTTPException(404, f"No existe el proyecto #{pid}")
        store.set_project_memory(pid, (body.memory_dir or "").strip() or None)
        return store.get_project(pid)

    # --- mantenimiento (M6)
    @app.get("/api/maintenance")
    async def maintenance_report(request: Request) -> dict:
        """Lo que se limpió al arrancar y lo que se conserva (ramas con trabajo de tareas fallidas/canceladas)."""
        return request.app.state.cleanup

    @app.post("/api/maintenance/cleanup")
    async def maintenance_cleanup(request: Request, dry_run: bool = False) -> dict:
        if request.app.state.runner.active or request.app.state.runner.plans:
            raise HTTPException(409, "Hay tareas o planes en marcha: espera a que terminen")
        request.app.state.cleanup = await asyncio.to_thread(maintenance.cleanup, st(request), dry_run)
        return request.app.state.cleanup

    # --- ajustes y skills
    @app.get("/api/settings")
    async def get_settings(request: Request) -> dict:
        return {"values": settings.load(st(request)), "defaults": settings.DEFAULTS}

    @app.put("/api/settings")
    async def put_settings(request: Request, body: dict[str, Any]) -> dict:
        try:
            values = settings.save(st(request), body)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        request.app.state.runner.hier.policy = settings.policy(st(request))
        return {"values": values, "defaults": settings.DEFAULTS}

    @app.post("/api/settings/reset")
    async def reset_settings(request: Request) -> dict:
        values = settings.reset(st(request))
        request.app.state.runner.hier.policy = settings.policy(st(request))
        return {"values": values, "defaults": settings.DEFAULTS}

    # --- modelos locales (llama.cpp)
    @app.get("/api/llama")
    async def llama_info(request: Request) -> dict:
        cfg = settings.load(st(request))["llama"]

        def gather() -> dict:
            return {"server": llama.server_binary(), "dirs": [str(d) for d in llama.model_dirs()],
                    "models": [llama.describe(m) for m in llama.list_models()],
                    "status": request.app.state.llama.status(cfg["port"]), "config": cfg,
                    "speed": request.app.state.runner.last_speed,
                    "load_times": request.app.state.llama.load_times()}
        return await asyncio.to_thread(gather)

    @app.post("/api/llama/start")
    async def llama_start(request: Request, body: LlamaStartIn) -> dict:
        store = st(request)
        cfg = settings.load(store)["llama"]
        model = Path(body.path)
        if not model.is_file() or model.suffix.lower() != ".gguf":
            raise HTTPException(422, "Eso no es un archivo .gguf")
        own = settings.llama_launch(store, str(model))
        try:
            await asyncio.to_thread(request.app.state.llama.start, model, cfg["port"], body.ctx or own["ctx"],
                                    body.ngl if body.ngl is not None else own["ngl"], own["extra"])
        except (LookupError, RuntimeError, OSError) as e:
            raise HTTPException(409, str(e)) from None
        # los agentes locales sin URL propia se conectan a este servidor
        settings.save(store, {"local_base_url": f"http://127.0.0.1:{cfg['port']}"})
        return await asyncio.to_thread(request.app.state.llama.status, cfg["port"])

    @app.post("/api/llama/stop")
    async def llama_stop(request: Request) -> dict:
        await asyncio.to_thread(request.app.state.llama.stop)
        return request.app.state.llama.status(settings.load(st(request))["llama"]["port"])

    @app.post("/api/pick")
    async def pick(body: PickIn) -> dict:
        """Abre el selector nativo de carpetas/archivos EN ESTE PC (el servidor es local) y devuelve la ruta."""
        try:
            path = await asyncio.to_thread(_pick_dialog, body.kind, body.title)
        except Exception as e:  # noqa: BLE001 — sin tkinter o sin escritorio: la GUI deja escribir la ruta
            raise HTTPException(501, f"No se puede abrir el selector aquí: {e}") from None
        return {"path": path or None}

    @app.get("/api/skills")
    async def skills() -> list[dict]:
        return [s.summary() for s in (await asyncio.to_thread(load_skills)).values()]

    # --- inicio: qué hace cada agente ahora y qué ha cambiado últimamente
    @app.get("/api/activity")
    async def activity(request: Request, limit: int = 12) -> dict:
        store = st(request)
        current = {}
        for t in store.list_tasks(status="running"):
            e = store.last_event(t["id"])
            if e:
                current[t["id"]] = {**e, "data": json.loads(e["data"] or "{}")}
        done = [t for t in reversed(store.list_tasks()) if t["finished_at"] and t["kind"] != "director"][:limit]
        recent = await asyncio.to_thread(lambda: [{**task_out(t), "files": _files(store, t)} for t in done])
        return {"current": current, "recent": recent}

    # --- tareas
    @app.get("/api/tasks")
    async def tasks(request: Request, project_id: int | None = None) -> list[dict]:
        return [task_out(t) for t in reversed(st(request).list_tasks(project_id))]

    @app.post("/api/tasks", status_code=201)
    async def add_task(request: Request, body: TaskIn) -> dict:
        store = st(request)
        if not store.get_project(body.project_id):
            raise HTTPException(422, "Proyecto inexistente")
        if not store.get_agent(body.agent_id):
            raise HTTPException(422, "Agente inexistente")
        if body.start and store.list_tasks(body.project_id, status="running"):
            raise HTTPException(409, "Ese proyecto ya tiene una tarea en marcha (una por repo a la vez)")
        title = (body.title or body.prompt.strip().splitlines()[0])[:80]
        t = store.add_task(body.project_id, title, body.prompt, body.agent_id, skills=body.skills or [])
        request.app.state.hub.publish("task", task_out(t))
        if body.start:
            request.app.state.runner.start(t["id"])
        return task_out(t)

    @app.get("/api/tasks/{tid}")
    async def task(request: Request, tid: int) -> dict:
        return task_out(task_or_404(st(request), tid))

    @app.get("/api/tasks/{tid}/events")
    async def task_events(request: Request, tid: int, after: int = 0) -> list[dict]:
        task_or_404(st(request), tid)
        return [{**e, "data": json.loads(e["data"] or "{}")} for e in st(request).list_events(tid, after)]

    @app.get("/api/tasks/{tid}/review")
    async def task_review(request: Request, tid: int) -> dict:
        store = st(request)
        t = task_or_404(store, tid)
        return await asyncio.to_thread(actions.review_data, store, t)

    @app.post("/api/tasks/{tid}/start")
    async def start(request: Request, tid: int) -> dict:
        store = st(request)
        t = task_or_404(store, tid)
        if t["status"] != "pending":
            raise HTTPException(409, f"Solo se arranca una tarea pendiente (está en '{t['status']}')")
        if store.list_tasks(t["project_id"], status="running"):
            raise HTTPException(409, "Ese proyecto ya tiene una tarea en marcha")
        request.app.state.runner.start(tid)
        return task_out(t)

    @app.post("/api/tasks/{tid}/cancel")
    async def cancel(request: Request, tid: int) -> dict:
        t = task_or_404(st(request), tid)
        if not await request.app.state.runner.cancel(tid):
            raise HTTPException(409, f"La tarea no está en marcha (está en '{t['status']}')")
        return task_out(st(request).get_task(tid))

    def _action(request: Request, fn, *args) -> dict:
        try:
            t = fn(st(request), *args)
        except actions.ActionError as e:
            raise HTTPException(409, str(e)) from None
        request.app.state.hub.publish("task", task_out(st(request).get_task(t["id"])))
        return task_out(t)

    @app.post("/api/tasks/{tid}/reply")
    async def reply(request: Request, tid: int, body: ReplyIn) -> dict:
        """Tu respuesta en la conversación: el agente sigue en la misma rama (y la misma sesión si es Claude)."""
        store = st(request)
        t = task_or_404(store, tid)
        if t["plan_id"] is not None:
            raise HTTPException(409, "Las subtareas de un plan se deciden desde el plan")
        if t["status"] in ("running", "pending"):
            raise HTTPException(409, "El agente aún no ha terminado: espera a que conteste")
        if t["status"] in ("merged", "rejected", "discarded"):
            raise HTTPException(409, f"La conversación está cerrada (tarea {t['status']}): empieza otra")
        if [r for r in store.list_tasks(t["project_id"], status="running") if r["id"] != tid]:
            raise HTTPException(409, "Ese proyecto ya tiene una tarea en marcha (una por repo a la vez)")
        request.app.state.runner.start(tid, followup=body.message.strip())
        return task_out(t)

    @app.post("/api/tasks/{tid}/approve")
    async def approve(request: Request, tid: int) -> dict:
        task_or_404(st(request), tid)
        return _action(request, actions.approve, tid)

    @app.post("/api/tasks/{tid}/reject")
    async def reject(request: Request, tid: int) -> dict:
        task_or_404(st(request), tid)
        return _action(request, actions.discard, tid, "rejected")

    @app.post("/api/tasks/{tid}/merge")
    async def merge(request: Request, tid: int, body: MergeIn) -> dict:
        task_or_404(st(request), tid)
        if not body.confirm:
            raise HTTPException(422, "Integrar exige confirmación explícita")
        # Integrar en la rama principal es nivel N2 (tú): antes hay que aprobar la tarea
        return _action(request, actions.merge, tid, None, True)

    # --- planes (M3)
    def plan_or_404(store: Store, pid: int) -> dict:
        p = store.get_plan(pid)
        if not p:
            raise HTTPException(404, f"No existe el plan #{pid}")
        return p

    def _plan_action(fn, *args) -> dict:
        try:
            return fn(*args)
        except actions.ActionError as e:
            raise HTTPException(409, str(e)) from None

    @app.get("/api/plans")
    async def plans(request: Request) -> list[dict]:
        return [plan_out(p) for p in reversed(st(request).list_plans())]

    @app.get("/api/plans/{pid}")
    async def plan(request: Request, pid: int) -> dict:
        p = plan_or_404(st(request), pid)
        return {**plan_out(p), "tasks": [task_out(t) for t in st(request).plan_tasks(pid)]}

    @app.post("/api/plans", status_code=201)
    async def add_plan(request: Request, body: PlanIn) -> dict:
        store = st(request)
        if not store.get_project(body.project_id):
            raise HTTPException(422, "Proyecto inexistente")
        for aid in (body.director_agent_id, body.reviewer_agent_id):
            if aid is not None and not store.get_agent(aid):
                raise HTTPException(422, f"Agente inexistente: #{aid}")
        if any(p["status"] in ("planning", "running") for p in store.list_plans(body.project_id)):
            raise HTTPException(409, "Ese proyecto ya tiene un plan en marcha")
        p = store.add_plan(body.project_id, body.request, body.director_agent_id, body.reviewer_agent_id)
        request.app.state.runner.publish_plan(p["id"])
        request.app.state.runner.run_plan(p["id"], plan_first=True)
        return plan_out(p)

    @app.post("/api/plans/{pid}/approve")
    async def approve_plan(request: Request, pid: int) -> dict:
        plan_or_404(st(request), pid)
        runner = request.app.state.runner
        p = _plan_action(runner.hier.approve_plan, pid)
        runner.run_plan(pid, plan_first=False)
        return plan_out(p)

    @app.post("/api/plans/{pid}/reject")
    async def reject_plan(request: Request, pid: int) -> dict:
        plan_or_404(st(request), pid)
        return plan_out(_plan_action(request.app.state.runner.hier.reject_plan, pid))

    @app.post("/api/plans/{pid}/merge")
    async def merge_plan(request: Request, pid: int, body: MergeIn) -> dict:
        plan_or_404(st(request), pid)
        if not body.confirm:
            raise HTTPException(422, "Integrar exige confirmación explícita")
        return plan_out(_plan_action(request.app.state.runner.hier.merge_plan, pid))

    @app.post("/api/plans/{pid}/cancel")
    async def cancel_plan(request: Request, pid: int) -> dict:
        p = plan_or_404(st(request), pid)
        if not await request.app.state.runner.cancel_plan(pid):
            raise HTTPException(409, f"El plan no está en marcha (está en '{p['status']}')")
        return plan_out(st(request).get_plan(pid))

    @app.post("/api/tasks/{tid}/decide")
    async def decide(request: Request, tid: int, body: DecideIn) -> dict:
        task_or_404(st(request), tid)
        runner = request.app.state.runner
        t = _plan_action(runner.hier.decide_task, tid, body.approve)
        runner.run_plan(t["plan_id"], plan_first=False)  # el plan sigue con la siguiente subtarea
        return task_out(t)

    @app.get("/api/inbox")
    async def get_inbox(request: Request) -> list[dict]:
        return inbox(st(request))

    # --- eventos en vivo
    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        hub: EventHub = request.app.state.hub

        async def stream() -> AsyncIterator[str]:
            q = hub.subscribe()
            try:
                yield sse_format("hello", json.dumps({"version": __version__, "t": time.time()}))
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event, payload = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_S)
                        yield sse_format(event, payload)
                    except TimeoutError:
                        yield ": latido\n\n"
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # --- web compilada (web/dist) con retorno a index.html para las rutas de la SPA
    if web_dist and (web_dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            candidate = (web_dist / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(web_dist.resolve()):
                return FileResponse(candidate)
            if full_path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(web_dist / "index.html")

    return app


def plan_out(p: dict) -> dict:
    return {**p, "plan": json.loads(p["plan"]) if p.get("plan") else None,
            "level_reasons": json.loads(p.get("level_reasons") or "[]")}


def task_out(t: dict) -> dict:
    return {**t, "level_reasons": json.loads(t.get("level_reasons") or "[]"),
            "review": json.loads(t["review"]) if t.get("review") else None,
            "skills": json.loads(t.get("skills") or "[]")}


def _pick_dialog(kind: str, title: str | None) -> str:
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # que no se quede detrás del navegador
    try:
        if kind == "file":
            return filedialog.askopenfilename(parent=root, title=title or "Elige un archivo")
        return filedialog.askdirectory(parent=root, title=title or "Elige una carpeta", mustexist=True)
    finally:
        root.destroy()


def _files(store: Store, t: dict) -> list[dict]:
    """Archivos que tocó una tarea (numstat de su rango de commits); vacío si no hay rango o ya no existe."""
    if not (t.get("base_commit") and t.get("head_commit")) or t["base_commit"] == t["head_commit"]:
        return []
    project = store.get_project(t["project_id"])
    try:
        out = workspace.git(project["repo_path"], "diff", "--numstat", t["base_commit"], t["head_commit"])
    except (workspace.GitError, OSError):
        return []
    files = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            add, rem, path = parts
            files.append({"path": path, "added": int(add) if add.isdigit() else 0,
                          "deleted": int(rem) if rem.isdigit() else 0})
    return files


def _model_name(path: str | None) -> str | None:
    return Path(path.replace("\\", "/")).name.removesuffix(".gguf") if path else None


def _last_limit(store: Store) -> dict | None:
    row = store.db.execute("SELECT data FROM events WHERE kind='limit' ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None
