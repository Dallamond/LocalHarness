"""Comparativa: la MISMA petición, en el mismo proyecto, hecha de varias maneras, para saber con números si
compensa delegar en los modelos locales.

Variantes (VARIANTS): Claude solo · Claude coordinando un modelo local (el principal) · Claude coordinando todos
los modelos locales (normalmente uno por GPU). Cada una es una tarea normal (su worktree y su rama, desde el mismo
commit), una detrás de otra (una tarea por repo a la vez). Al terminar cada una se mide (`measure`):
- tokens de Claude (lo que gasta tu plan) y coste nominal,
- tokens y encargos del modelo local (por servidor),
- tiempo, archivos y líneas cambiadas,
- la orden de comprobación (tests) ejecutada en su worktree: ¿pasa?
Las tareas quedan en revisión (Trabajo) para ver cada diff; nada se integra solo.
"""

import asyncio
import datetime
import json
import shlex
import time
from pathlib import Path

from localharness import workspace
from localharness.store import Store

VARIANTS = {
    "solo": {"label": "Solo Claude", "config": {}},
    "local1": {"label": "Claude + 1 modelo local", "config": {"coordinator": True, "delegate_local": True,
                                                               "local_servers": ["principal"]}},
    "local2": {"label": "Claude + todos los modelos locales", "config": {"coordinator": True,
                                                                         "delegate_local": True}},
}
CLAUDE_MODELS = ("haiku", "sonnet", "opus")
CLOSED = ("done", "failed", "cancelled")


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace(" ", "T")).replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def _n(v) -> int:
    return int(v) if isinstance(v, (int, float)) else 0


def run_check(worktree: str, command: str) -> dict:
    """La orden de comprobación en el worktree de la variante, con la misma lista blanca que la delegación."""
    from localharness.mcp_local import Server
    out = Server({"LH_ROOT": worktree, "LH_LOCAL_URL": "http://127.0.0.1:9"}).run_check(command)
    first = out.split("\n", 1)[0]
    code = int(first.rsplit(" ", 1)[-1]) if first.startswith("código de salida") else None
    return {"command": command, "exit": code, "ok": code == 0, "output": out[-1500:]}


def measure(store: Store, tid: int, check: str = "") -> dict:
    """Números de una tarea terminada (todo sale de sus eventos, como las Analíticas)."""
    t = store.get_task(tid)
    m = {"task_id": tid, "status": t["status"], "cost_usd": round(t["cost_usd"] or 0, 4),
         "claude_in": 0, "claude_out": 0, "claude_cache_read": 0, "local_in": 0, "local_out": 0,
         "delegations": 0, "delegations_ok": 0, "local_seconds": 0.0, "by_server": {}, "claude_tools": 0,
         "limit": None}
    started = None
    for e in store.list_events(tid):
        try:
            data = json.loads(e["data"] or "{}")
        except ValueError:
            data = {}
        if e["kind"] == "status" and e["text"] == "running" and started is None:
            started = _ts(e["ts"])
        elif e["kind"] == "usage" and not data.get("local"):
            u = data.get("usage") or {}
            m["claude_in"] += _n(u.get("input_tokens")) + _n(u.get("cache_creation_input_tokens"))
            m["claude_cache_read"] += _n(u.get("cache_read_input_tokens"))
            m["claude_out"] += _n(u.get("output_tokens"))
        elif e["kind"] == "usage" and data.get("local"):
            u = data.get("usage") or {}
            m["local_in"] += _n(u.get("prompt_tokens"))
            m["local_out"] += _n(u.get("completion_tokens"))
        elif e["kind"] == "delegate" and str(data.get("tool") or "") not in ("local_execute_plan", "local_prepare"):
            m["delegations"] += 1
            m["delegations_ok"] += 1 if data.get("ok") else 0
            m["local_in"] += _n(data.get("prompt_tokens"))
            m["local_out"] += _n(data.get("completion_tokens"))
            m["local_seconds"] += float(data.get("seconds") or 0)
            srv = str(data.get("server") or "principal")
            m["by_server"][srv] = m["by_server"].get(srv, 0) + 1
        elif e["kind"] == "tool":
            m["claude_tools"] += 1
        elif e["kind"] == "limit":
            m["limit"] = data
    end = _ts(t["finished_at"])
    start = started or _ts(t["created_at"])
    m["seconds"] = round(end - start, 1) if end and start else None
    m["local_seconds"] = round(m["local_seconds"], 1)
    # lo que gasta el plan: lo que Claude lee nuevo y escribe (la caché leída cuenta mucho menos)
    m["claude_tokens"] = m["claude_in"] + m["claude_out"]
    m["local_tokens"] = m["local_in"] + m["local_out"]
    files, added, deleted = [], 0, 0
    if t["worktree"] and t["base_commit"] and Path(t["worktree"]).is_dir():
        try:
            raw = workspace.git(Path(t["worktree"]), "diff", "--numstat", t["base_commit"])
            for line in raw.splitlines():
                parts = line.split("\t")
                if len(parts) == 3:
                    files.append(parts[2])
                    added += int(parts[0]) if parts[0].isdigit() else 0
                    deleted += int(parts[1]) if parts[1].isdigit() else 0
        except (workspace.GitError, OSError):
            pass
        if check.strip():
            m["check"] = run_check(t["worktree"], check)
    m.update(files=files, added=added, deleted=deleted)
    return m


def create(store: Store, project_id: int, prompt: str, variants: list[str], claude_model: str = "sonnet",
           check: str = "") -> dict:
    variants = [v for v in dict.fromkeys(variants) if v in VARIANTS]
    if not variants:
        raise ValueError(f"Elige al menos una variante: {', '.join(VARIANTS)}")
    if claude_model not in CLAUDE_MODELS:
        raise ValueError(f"Modelo de Claude no válido: {claude_model}")
    if check.strip():
        try:
            shlex.split(check)
        except ValueError as e:
            raise ValueError(f"Orden de comprobación mal escrita: {e}") from None
    cur = store.db.execute(
        "INSERT INTO comparisons (project_id, prompt, claude_model, check_cmd, variants, results) "
        "VALUES (?, ?, ?, ?, ?, '{}')", (project_id, prompt, claude_model, check.strip(), json.dumps(variants)))
    store.db.commit()
    return get(store, cur.lastrowid)


def get(store: Store, cid: int) -> dict | None:
    r = store.db.execute("SELECT * FROM comparisons WHERE id = ?", (cid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["variants"] = json.loads(d["variants"] or "[]")
    d["results"] = json.loads(d["results"] or "{}")
    d["labels"] = {k: VARIANTS[k]["label"] for k in d["variants"] if k in VARIANTS}
    return d


def list_all(store: Store, limit: int = 30) -> list[dict]:
    ids = [r[0] for r in store.db.execute("SELECT id FROM comparisons ORDER BY id DESC LIMIT ?", (limit,))]
    return [get(store, i) for i in ids]


def _save(store: Store, cid: int, **f) -> None:
    if "results" in f:
        f["results"] = json.dumps(f["results"], ensure_ascii=False)
    sets = ", ".join(f"{k} = ?" for k in f)
    store.db.execute(f"UPDATE comparisons SET {sets} WHERE id = ?", (*f.values(), cid))
    store.db.commit()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def run(store: Store, cid: int, start_task, wait_task, publish=lambda cid: None) -> None:
    """Hace las variantes una detrás de otra. `start_task(tid)` la lanza (Runner.start) y `wait_task(tid)` espera a
    que termine. Cada variante tiene su agente (oculto en la oficina: `off`) con su configuración."""
    c = get(store, cid)
    project = store.get_project(c["project_id"])
    results = dict(c["results"])
    _save(store, cid, status="running")
    publish(cid)
    try:
        for v in c["variants"]:
            name = f"comparativa-{cid}-{v}"
            agent = store.find_agent(name) or store.add_agent(
                name, "claude", c["claude_model"], "trabajador",
                {**VARIANTS[v]["config"], "off": True, "generated": True, "compare": cid, "max_turns": 40,
                 "description": f"Comparativa #{cid}: {VARIANTS[v]['label']}"})
            title = f"[Comparativa #{cid}] {VARIANTS[v]['label']}"
            t = store.add_task(project["id"], title, c["prompt"], agent["id"])
            results[v] = {"task_id": t["id"], "status": "running", "started": time.time()}
            _save(store, cid, results=results)
            publish(cid)
            start_task(t["id"])
            await wait_task(t["id"])
            results[v] = await asyncio.to_thread(measure, store, t["id"], c["check_cmd"] or "")
            _save(store, cid, results=results)
            publish(cid)
        _save(store, cid, status="done", finished_at=_now())
    except asyncio.CancelledError:
        _save(store, cid, status="cancelled", finished_at=_now())
        raise
    except Exception as e:  # noqa: BLE001 — se guarda en la comparativa, no tumba el servidor
        _save(store, cid, status="failed", error=str(e)[:500], finished_at=_now())
    finally:
        publish(cid)
