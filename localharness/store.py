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
]


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
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

    def get_project(self, pid: int) -> dict | None:
        return self._one("SELECT * FROM projects WHERE id=?", pid)

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
        self.db.commit()
        return cur.rowcount

    def update_task(self, tid: int, **f: Any) -> None:
        keys = ", ".join(f"{k}=?" for k in f)
        self.db.execute(f"UPDATE tasks SET {keys} WHERE id=?", (*f.values(), tid))
        self.db.commit()

    def add_event(self, tid: int, kind: str, text: str = "", data: dict | None = None) -> None:
        self.db.execute("INSERT INTO events(task_id,kind,text,data) VALUES(?,?,?,?)",
                        (tid, kind, text, json.dumps(data or {}, ensure_ascii=False, default=str)))
        self.db.commit()

    def list_events(self, tid: int, after: int = 0) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id", (tid, after))]
