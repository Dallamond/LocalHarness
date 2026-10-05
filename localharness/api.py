"""API de M2: FastAPI + SSE. Un único proceso: el bucle de asyncio ejecuta las tareas y emite sus eventos.

    .venv/Scripts/python -m localharness serve        # http://127.0.0.1:8095

Solo escucha en 127.0.0.1 por defecto: no hay autenticación (acceso por LAN es una fase posterior).
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from localharness import actions, workspace
from localharness.adapters import ADAPTERS
from localharness.events import Event
from localharness.hierarchy import Hierarchy, inbox
from localharness.hub import EventHub, sse_format
from localharness.orchestrator import execute_task
from localharness.store import Store

__version__ = "0.1.0"
SSE_HEARTBEAT_S = 15.0
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    repo_path: str = Field(min_length=1)


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    provider: str = "claude"
    model: str | None = None
    role: str | None = None
    max_turns: int | None = Field(default=None, ge=1, le=200)
    max_budget_usd: float | None = Field(default=None, gt=0)
    read_only: bool = False
    tools: list[str] | None = None


class TaskIn(BaseModel):
    project_id: int
    agent_id: int
    prompt: str = Field(min_length=1)
    title: str | None = None
    start: bool = True


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
                self.store.update_plan(pid, status="cancelled", finished_at=actions.now())
            except Exception as e:  # noqa: BLE001 — se registra en el plan, no tumba el servidor
                self.store.update_plan(pid, status="failed", error=str(e), finished_at=actions.now())
            finally:
                self.plans.pop(pid, None)
                self.publish_plan(pid)

        self.plans[pid] = asyncio.create_task(go())

    def on_event(self, tid: int, ev: Event) -> None:
        self.hub.publish("task_event", {"task_id": tid, **ev.as_dict()})
        if ev.kind in ("status", "session", "usage"):
            self.publish_task(tid)
        if ev.kind == "limit":
            self.last_limit = ev.data
            self.hub.publish("limit", ev.data)

    def start(self, tid: int) -> None:
        async def go() -> None:
            try:
                await execute_task(self.store, tid, binaries=self.binaries, on_event=self.on_event,
                                   worktree_root=self.worktree_root)
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
        app.state.store = store
        app.state.hub = EventHub()
        app.state.runner = Runner(store, app.state.hub, binaries, worktree_root)
        yield
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
        return {"version": __version__, "providers": list(ADAPTERS),
                "running": sorted(request.app.state.runner.active), "limit": request.app.state.runner.last_limit}

    # --- proyectos
    @app.get("/api/projects")
    async def projects(request: Request) -> list[dict]:
        return st(request).list_projects()

    @app.post("/api/projects", status_code=201)
    async def add_project(request: Request, body: ProjectIn) -> dict:
        repo = Path(body.repo_path).expanduser().resolve()
        try:
            workspace.git(repo, "rev-parse", "HEAD")
        except (workspace.GitError, OSError):
            raise HTTPException(422, f"{repo} no es un repo git con al menos un commit") from None
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
                                 "read_only": body.read_only or None, "tools": body.tools}.items() if v is not None}
        a = st(request).add_agent(body.name, body.provider, model=body.model, role=body.role, config=cfg)
        return {**a, "config": cfg}

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
        t = store.add_task(body.project_id, title, body.prompt, body.agent_id)
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
            "review": json.loads(t["review"]) if t.get("review") else None}


def _last_limit(store: Store) -> dict | None:
    row = store.db.execute("SELECT data FROM events WHERE kind='limit' ORDER BY id DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None
