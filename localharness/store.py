"""SQLite local: estado operativo (proyectos, tareas, eventos). La memoria legible vive en Markdown."""

import json
import sqlite3
from pathlib import Path
from typing import Any

MIGRATIONS = [
    """
    CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL, repo_path TEXT NOT NULL UNIQUE,
        memory_dir TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE agents (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, provider TEXT NOT NULL,
        model TEXT, role TEXT, config TEXT DEFAULT '{}');
    CREATE TABLE tasks (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
        title TEXT NOT NULL, prompt TEXT NOT NULL, agent_id INTEGER REFERENCES agents(id),
        skills TEXT DEFAULT '[]', status TEXT NOT NULL DEFAULT 'pending',
        branch TEXT, worktree TEXT, base_commit TEXT, session_id TEXT, final TEXT, cost_usd REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT);
    CREATE TABLE events (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        kind TEXT NOT NULL, text TEXT, data TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE INDEX events_task ON events(task_id, id);
    """,
    # M3: planes del Director y aprobaciones por niveles
    """
    CREATE TABLE plans (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
        request TEXT NOT NULL, director_agent_id INTEGER REFERENCES agents(id),
        reviewer_agent_id INTEGER REFERENCES agents(id), status TEXT NOT NULL DEFAULT 'planning',
        plan TEXT, level TEXT, level_reasons TEXT DEFAULT '[]', branch TEXT, worktree TEXT, base_commit TEXT,
        cost_usd REAL, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT);
    ALTER TABLE tasks ADD COLUMN plan_id INTEGER REFERENCES plans(id);
    ALTER TABLE tasks ADD COLUMN seq INTEGER;
    ALTER TABLE tasks ADD COLUMN level TEXT;
    ALTER TABLE tasks ADD COLUMN level_reasons TEXT DEFAULT '[]';
    ALTER TABLE tasks ADD COLUMN review TEXT;
    ALTER TABLE tasks ADD COLUMN approved_by TEXT;
    ALTER TABLE tasks ADD COLUMN head_commit TEXT;
    ALTER TABLE tasks ADD COLUMN kind TEXT DEFAULT 'worker';  -- director | worker | reviewer
    """,
    # Ajustes de la GUI (settings.py): clave → JSON
    """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # Pensamiento por tarea: apagado | normal | profundo (NULL = el del agente)
    """
    ALTER TABLE tasks ADD COLUMN thinking TEXT;
    """,
    # Comparativa (compare.py): la misma petición hecha de varias maneras, con sus números
    """
    CREATE TABLE comparisons (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
        prompt TEXT NOT NULL, claude_model TEXT NOT NULL DEFAULT 'sonnet', check_cmd TEXT, variants TEXT NOT NULL,
        results TEXT DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending', error TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, finished_at TEXT);
    """,
]


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)  # la API lo usa desde el hilo del bucle y el de git
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def close(self) -> None:
        self.db.close()

    def migrate(self) -> None:
        v = self.db.execute("PRAGMA user_version").fetchone()[0]
        for i, sql in enumerate(MIGRATIONS[v:], start=v + 1):
            self.db.executescript(sql)
            self.db.execute(f"PRAGMA user_version={i}")
        self.db.commit()

    def _one(self, sql: str, *a: Any) -> dict | None:
        r = self.db.execute(sql, a).fetchone()
        return dict(r) if r else None

    def add_project(self, name: str, repo_path: str, memory_dir: str | None = None) -> dict:
        cur = self.db.execute("INSERT INTO projects(name,repo_path,memory_dir) VALUES(?,?,?)",
                              (name, repo_path, memory_dir))
        self.db.commit()
        return self._one("SELECT * FROM projects WHERE id=?", cur.lastrowid)  # type: ignore[return-value]

    def add_agent(self, name: str, provider: str, model: str | None = None, role: str | None = None,
                  config: dict | None = None) -> dict:
        cur = self.db.execute("INSERT INTO agents(name,provider,model,role,config) VALUES(?,?,?,?,?)",
                              (name, provider, model, role, json.dumps(config or {})))
        self.db.commit()
        return self._one("SELECT * FROM agents WHERE id=?", cur.lastrowid)  # type: ignore[return-value]

    def get_agent(self, agent_id: int) -> dict | None:
        return self._one("SELECT * FROM agents WHERE id=?", agent_id)

    def find_agent(self, name: str) -> dict | None:
        return self._one("SELECT * FROM agents WHERE name=?", name)

    def list_agents(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM agents ORDER BY id")]

    def update_agent(self, agent_id: int, **f: Any) -> None:
        f = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in f.items()}
        keys = ", ".join(f"{k}=?" for k in f)
        self.db.execute(f"UPDATE agents SET {keys} WHERE id=?", (*f.values(), agent_id))
        self.db.commit()

    def agent_in_use(self, agent_id: int) -> bool:
        return bool(self.db.execute(
            "SELECT 1 FROM tasks WHERE agent_id=? UNION SELECT 1 FROM plans WHERE director_agent_id=? "
            "OR reviewer_agent_id=? LIMIT 1", (agent_id, agent_id, agent_id)).fetchone())

    def delete_agent(self, agent_id: int) -> None:
        self.db.execute("DELETE FROM agents WHERE id=?", (agent_id,))
        self.db.commit()

    def get_settings(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.db.execute("SELECT key, value FROM settings")}

    def set_setting(self, key: str, value: Any) -> None:
        self.db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def clear_settings(self) -> None:
        self.db.execute("DELETE FROM settings")
        self.db.commit()

    def last_event(self, tid: int, kinds: tuple[str, ...] = ("text", "tool", "status", "context")) -> dict | None:
        marks = ",".join("?" * len(kinds))
        return self._one(f"SELECT * FROM events WHERE task_id=? AND kind IN ({marks}) ORDER BY id DESC LIMIT 1",
                         tid, *kinds)

    def get_project(self, pid: int) -> dict | None:
        return self._one("SELECT * FROM projects WHERE id=?", pid)

    def set_project_memory(self, pid: int, memory_dir: str | None) -> None:
        self.db.execute("UPDATE projects SET memory_dir=? WHERE id=?", (memory_dir, pid))
        self.db.commit()

    def find_project(self, name: str) -> dict | None:
        return self._one("SELECT * FROM projects WHERE name=?", name)

    def list_projects(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM projects ORDER BY id")]

    def add_task(self, project_id: int, title: str, prompt: str, agent_id: int | None = None,
                 skills: list[str] | None = None) -> dict:
        cur = self.db.execute("INSERT INTO tasks(project_id,title,prompt,agent_id,skills) VALUES(?,?,?,?,?)",
                              (project_id, title, prompt, agent_id, json.dumps(skills or [])))
        self.db.commit()
        return self.get_task(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def get_task(self, tid: int) -> dict | None:
        return self._one("SELECT * FROM tasks WHERE id=?", tid)

    def add_plan(self, project_id: int, request: str, director_agent_id: int | None,
                 reviewer_agent_id: int | None = None) -> dict:
        cur = self.db.execute("INSERT INTO plans(project_id,request,director_agent_id,reviewer_agent_id) VALUES(?,?,?,?)",
                              (project_id, request, director_agent_id, reviewer_agent_id))
        self.db.commit()
        return self.get_plan(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def get_plan(self, pid: int) -> dict | None:
        return self._one("SELECT * FROM plans WHERE id=?", pid)

    def list_plans(self, project_id: int | None = None) -> list[dict]:
        if project_id is None:
            return [dict(r) for r in self.db.execute("SELECT * FROM plans ORDER BY id")]
        return [dict(r) for r in self.db.execute("SELECT * FROM plans WHERE project_id=? ORDER BY id", (project_id,))]

    def delete_task(self, tid: int) -> None:
        self.db.execute("DELETE FROM tasks WHERE id=?", (tid,))  # sus eventos se borran en cascada
        self.db.commit()

    def update_plan(self, pid: int, **f: Any) -> None:
        f = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in f.items()}
        keys = ", ".join(f"{k}=?" for k in f)
        self.db.execute(f"UPDATE plans SET {keys} WHERE id=?", (*f.values(), pid))
        self.db.commit()

    def plan_tasks(self, plan_id: int) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM tasks WHERE plan_id=? ORDER BY seq, id", (plan_id,))]

    def list_tasks(self, project_id: int | None = None, status: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM tasks WHERE 1=1", []
        if project_id is not None:
            sql += " AND project_id=?"; args.append(project_id)
        if status is not None:
            sql += " AND status=?"; args.append(status)
        return [dict(r) for r in self.db.execute(sql + " ORDER BY id", args)]

    def mark_interrupted(self) -> int:
        """Al arrancar: una tarea que seguía 'running' murió con el proceso anterior (como Arena)."""
        cur = self.db.execute("UPDATE tasks SET status='interrupted' WHERE status='running'")
        self.db.execute("UPDATE plans SET status='interrupted' WHERE status IN ('planning','running')")
        # subtareas que ya nunca se ejecutarán: su plan terminó sin llegar a ellas
        self.db.execute("UPDATE tasks SET status='cancelled' WHERE status='pending' AND plan_id IN "
                        "(SELECT id FROM plans WHERE status IN ('failed','cancelled','interrupted','rejected'))")
        self.db.commit()
        return cur.rowcount

    def update_task(self, tid: int, **f: Any) -> None:
        f = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in f.items()}
        keys = ", ".join(f"{k}=?" for k in f)
        self.db.execute(f"UPDATE tasks SET {keys} WHERE id=?", (*f.values(), tid))
        self.db.commit()

    def add_event(self, tid: int, kind: str, text: str = "", data: dict | None = None) -> int:
        cur = self.db.execute("INSERT INTO events(task_id,kind,text,data) VALUES(?,?,?,?)",
                        (tid, kind, text, json.dumps(data or {}, ensure_ascii=False, default=str)))
        self.db.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def list_events(self, tid: int, after: int = 0) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id", (tid, after))]
