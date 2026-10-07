"""Analíticas de uso: peticiones, tokens de Claude y del modelo local, coste, encargos y uso por agente.

Todo sale de lo que ya se guarda (tareas y eventos): no hay contadores aparte que se puedan desincronizar.
- Tokens de Claude: eventos `usage` de las tareas de Claude (input = input + caché creada + caché leída; output).
- Tokens locales: eventos `usage` con `local` (agentes locales) + encargos `delegate` (lo que Claude delegó).
- Una «petición» es una tarea (cada subtarea de un plan cuenta) y cada respuesta tuya en una conversación.
"""

import datetime
import json
from collections import defaultdict

from localharness.store import Store

NOT_ENCARGOS = ("local_execute_plan", "local_prepare")  # resumen de plan y equipar: sin tokens propios


def _day(ts: str | None) -> str:
    return (ts or "")[:10]


def _n(v) -> int:
    return int(v) if isinstance(v, (int, float)) else 0


def compute(store: Store, days: int = 30) -> dict:
    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    tasks = {r["id"]: dict(r) for r in store.db.execute(
        "SELECT t.id, t.agent_id, t.status, t.cost_usd, t.created_at, t.kind, t.plan_id, a.name AS agent, "
        "a.provider FROM tasks t LEFT JOIN agents a ON a.id = t.agent_id WHERE t.created_at >= ?", (since,))}
    blank = {"requests": 0, "cost_usd": 0.0, "claude_in": 0, "claude_out": 0, "local_in": 0, "local_out": 0,
             "delegations": 0}
    total = {**blank, "tasks": len(tasks), "plans": 0, "delegations_ok": 0, "seconds_local": 0.0}
    by_agent: dict[str, dict] = {}
    by_day: dict[str, dict] = defaultdict(lambda: dict(blank))
    by_tool: dict[str, int] = defaultdict(int)
    by_status: dict[str, int] = defaultdict(int)
    by_model: dict[str, int] = defaultdict(int)  # tokens locales por modelo GGUF

    def agent_row(t: dict) -> dict:
        key = t["agent"] or "(sin agente)"
        if key not in by_agent:
            by_agent[key] = {**blank, "agent": key, "provider": t["provider"] or "", "tasks": 0}
        return by_agent[key]

    for t in tasks.values():
        a, d = agent_row(t), by_day[_day(t["created_at"])]
        for row in (total, a, d):
            row["requests"] += 1
            row["cost_usd"] += t["cost_usd"] or 0
        a["tasks"] += 1
        by_status[t["status"]] += 1
    total["plans"] = store.db.execute("SELECT COUNT(*) FROM plans WHERE created_at >= ?", (since,)).fetchone()[0]

    if tasks:
        marks = ",".join("?" * len(tasks))
        rows = store.db.execute(f"SELECT task_id, kind, data, ts FROM events WHERE kind IN ('usage', 'delegate', 'user') "
                                f"AND task_id IN ({marks})", list(tasks))
        for r in rows:
            t = tasks[r["task_id"]]
            a, d = agent_row(t), by_day[_day(r["ts"]) or _day(t["created_at"])]
            if r["kind"] == "user":  # tu respuesta en una conversación: otra petición
                for row in (total, a, d):
                    row["requests"] += 1
                continue
            try:
                data = json.loads(r["data"] or "{}")
            except ValueError:
                continue
            if r["kind"] == "usage":
                u = data.get("usage") or {}
                if data.get("local"):
                    i, o = _n(u.get("prompt_tokens")), _n(u.get("completion_tokens"))
                    keys = ("local_in", "local_out")
                    if data.get("model"):
                        by_model[str(data["model"])] += i + o
                else:
                    i = _n(u.get("input_tokens")) + _n(u.get("cache_creation_input_tokens")) + _n(
                        u.get("cache_read_input_tokens"))
                    o = _n(u.get("output_tokens"))
                    keys = ("claude_in", "claude_out")
                for row in (total, a, d):
                    row[keys[0]] += i
                    row[keys[1]] += o
            else:  # delegate: un encargo al modelo local (los bloques de un plan cuentan uno a uno)
                tool = str(data.get("tool") or "")
                if tool in NOT_ENCARGOS:
                    continue
                i, o = _n(data.get("prompt_tokens")), _n(data.get("completion_tokens"))
                for row in (total, a, d):
                    row["local_in"] += i
                    row["local_out"] += o
                    row["delegations"] += 1
                total["delegations_ok"] += 1 if data.get("ok") else 0
                total["seconds_local"] += float(data.get("seconds") or 0)
                by_tool[tool.split("/")[0].removeprefix("local_")] += 1
                if data.get("model"):
                    by_model[str(data["model"])] += i + o

    claude = total["claude_in"] + total["claude_out"]
    local = total["local_in"] + total["local_out"]
    today = datetime.datetime.now(datetime.timezone.utc).date()  # como CURRENT_TIMESTAMP de SQLite
    series = []
    for k in range(days - 1, -1, -1):
        day = (today - datetime.timedelta(days=k)).isoformat()
        row = by_day.get(day, blank)
        series.append({"day": day, "requests": row["requests"], "cost_usd": round(row["cost_usd"], 4),
                       "claude_tokens": row["claude_in"] + row["claude_out"],
                       "local_tokens": row["local_in"] + row["local_out"]})
    agents = sorted(({**r, "cost_usd": round(r["cost_usd"], 4)} for r in by_agent.values()),
                    key=lambda r: -(r["claude_in"] + r["claude_out"] + r["local_in"] + r["local_out"] + r["tasks"]))
    return {
        "days": days,
        "total": {**total, "cost_usd": round(total["cost_usd"], 4), "seconds_local": round(total["seconds_local"], 1),
                  "claude_tokens": claude, "local_tokens": local, "tokens": claude + local,
                  "local_share": round(local / (claude + local), 3) if claude + local else 0.0},
        "by_day": series,
        "by_agent": agents,
        "by_tool": dict(sorted(by_tool.items(), key=lambda kv: -kv[1])),
        "by_status": dict(by_status),
        "by_model": dict(sorted(by_model.items(), key=lambda kv: -kv[1])),
    }
