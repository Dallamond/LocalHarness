"""Línea de órdenes de LocalHarness (M1). Nunca hace push: integrar pide confirmación y el push es tuyo.

    python -m localharness doctor
    python -m localharness project add <nombre> <ruta-repo>
    python -m localharness agent add <nombre> --provider claude [--model M] [--max-turns N] [--budget USD]
    python -m localharness run <proyecto> "<petición>" --agent <nombre>
    python -m localharness tasks | show <id> [--diff] | merge <id> [--into rama] | discard <id>
"""

import argparse
import asyncio
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from localharness import workspace
from localharness.adapters import ADAPTERS
from localharness.adapters.claude import login_method
from localharness.binaries import resolve
from localharness.events import Event
from localharness.orchestrator import execute_task
from localharness.store import Store

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "localharness.db"


def _store(args) -> Store:
    path = Path(args.db or os.environ.get("LOCALHARNESS_DB") or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(path)
    n = store.mark_interrupted()
    if n:
        print(f"Aviso: {n} tarea(s) que quedaron a medias se marcan como 'interrupted'.")
    return store


def _fail(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return 1


def _ws(store: Store, task: dict) -> workspace.Workspace:
    project = store.get_project(task["project_id"])
    return workspace.Workspace(Path(project["repo_path"]), Path(task["worktree"]), task["branch"],
                               task["base_commit"])


def cmd_doctor(args, store: Store | None = None) -> int:
    ok = True
    print(f"python   {sys.version.split()[0]}  ({sys.executable})")
    g = shutil.which("git")
    print(f"git      {subprocess.run(['git', '--version'], capture_output=True, text=True).stdout.strip() if g else 'NO ENCONTRADO'}")
    ok &= bool(g)
    for name in ADAPTERS:
        cmd = resolve(name)
        if not shutil.which(name):
            print(f"{name:8} no instalado")
            continue
        print(f"{name:8} {cmd[-1]}")
    if shutil.which("claude"):
        method = login_method()
        sub = method == "claude.ai"
        print(f"claude   login: {method}  {'OK (suscripción)' if sub else 'ATENCIÓN: no es la suscripción'}")
        ok &= sub
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if os.environ.get(var):
            print(f"aviso    {var} está definida; LocalHarness la quita del entorno de claude.")
    return 0 if ok else 1


def cmd_project(args, store: Store) -> int:
    if args.action == "add":
        repo = Path(args.path).resolve()
        try:
            workspace.git(repo, "rev-parse", "HEAD")
        except (workspace.GitError, OSError) as e:
            return _fail(f"{repo} no es un repo git con al menos un commit ({e})")
        p = store.add_project(args.name, str(repo))
        print(f"Proyecto #{p['id']} {p['name']} -> {p['repo_path']}")
    else:
        for p in store.list_projects():
            print(f"#{p['id']:<3} {p['name']:20} {p['repo_path']}")
    return 0


def cmd_agent(args, store: Store) -> int:
    if args.action == "add":
        if args.provider not in ADAPTERS:
            return _fail(f"proveedor desconocido {args.provider!r} (hay: {', '.join(ADAPTERS)})")
        cfg = {k: v for k, v in {"max_turns": args.max_turns, "max_budget_usd": args.budget,
                                 "read_only": args.read_only or None,
                                 "tools": args.tools.split(",") if args.tools else None,
                                 "binary": args.binary}.items() if v is not None}
        a = store.add_agent(args.name, args.provider, model=args.model, role=args.role, config=cfg)
        print(f"Agente #{a['id']} {a['name']} ({a['provider']}{'/' + a['model'] if a['model'] else ''}) {cfg}")
    else:
        for a in store.list_agents():
            print(f"#{a['id']:<3} {a['name']:16} {a['provider']:7} {a['model'] or '-':20} {a['role'] or '-':12} {a['config']}")
    return 0


def _print_event(_tid: int, ev: Event) -> None:
    if ev.kind == "text":
        print(f"  · {ev.text}")
    elif ev.kind == "tool":
        detail = json.dumps(ev.data.get("input") or ev.data.get("output") or "", ensure_ascii=False)[:120]
        print(f"  ⚙ {ev.text} {detail}")
    elif ev.kind == "error":
        print(f"  ✗ {ev.text}")
    elif ev.kind == "limit" and (ev.data.get("seven_day") or 0) >= 0.75:
        print(f"  ! uso del plan: 5 h {ev.data.get('five_hour')!s:5}  7 días {ev.data.get('seven_day')}")
    elif ev.kind == "session":
        print(f"  sesión {ev.data.get('session_id')}  modelo {ev.data.get('model')}  herramientas {ev.data.get('tools')}")


def cmd_run(args, store: Store) -> int:
    project = store.find_project(args.project)
    agent = store.find_agent(args.agent)
    if not project:
        return _fail(f"no existe el proyecto {args.project!r} (python -m localharness project add …)")
    if not agent:
        return _fail(f"no existe el agente {args.agent!r} (python -m localharness agent add …)")
    title = args.title or args.prompt.strip().splitlines()[0][:60]
    task = store.add_task(project["id"], title, args.prompt, agent["id"])
    print(f"Tarea #{task['id']} «{title}» con {agent['name']} sobre {project['name']}")
    try:
        res = asyncio.run(execute_task(store, task["id"], on_event=_print_event, timeout_s=args.timeout))
    except (ValueError, workspace.GitError) as e:
        store.update_task(task["id"], status="failed")
        return _fail(str(e))
    except KeyboardInterrupt:
        store.update_task(task["id"], status="cancelled")
        return _fail("cancelada")
    t = store.get_task(task["id"])
    print(f"\nEstado: {t['status']}  ·  {res['duration_s']:.0f} s  ·  coste equivalente {t['cost_usd'] or 0:.4f} $")
    print(f"Rama {t['branch']}  ·  worktree {t['worktree']}")
    print(res["stat"] or "(sin cambios)")
    if t["status"] == "review":
        print(f"Revisa:  python -m localharness show {t['id']} --diff\n"
              f"Integra: python -m localharness merge {t['id']}   (pide confirmación; no hace push)")
    return 0 if t["status"] == "review" else 1


def cmd_tasks(args, store: Store) -> int:
    for t in store.list_tasks():
        cost = f"{t['cost_usd']:.4f}$" if t["cost_usd"] is not None else "-"
        print(f"#{t['id']:<4} {t['status']:11} {cost:>9}  {t['title']}")
    return 0


def cmd_show(args, store: Store) -> int:
    t = store.get_task(args.id)
    if not t:
        return _fail(f"no existe la tarea #{args.id}")
    for k in ("title", "status", "branch", "worktree", "base_commit", "session_id", "cost_usd", "created_at",
              "finished_at"):
        print(f"{k:12} {t[k]}")
    print(f"{'final':12} {t['final']}")
    if t["worktree"] and Path(t["worktree"]).exists():
        ws = _ws(store, t)
        print("\n" + (ws.diff() if args.diff else ws.stat() or "(sin cambios)"))
    return 0


def cmd_merge(args, store: Store) -> int:
    t = store.get_task(args.id)
    if not t or t["status"] != "review":
        return _fail(f"solo se integran tareas en 'review' (#{args.id}: {t and t['status']})")
    ws = _ws(store, t)
    target = args.into or workspace.git(ws.repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    print(ws.stat())
    if not args.yes and input(f"¿Integrar {t['branch']} en {target}? Nunca se hace push. [s/N] ").strip().lower() not in ("s", "si", "sí", "y"):
        return _fail("no integrado")
    try:
        ws.merge(args.into)
    except workspace.GitError as e:
        return _fail(str(e))
    ws.remove()
    store.update_task(t["id"], status="merged", finished_at=_now())
    print(f"Integrado en {target}. El push lo haces tú cuando quieras.")
    return 0


def cmd_discard(args, store: Store) -> int:
    t = store.get_task(args.id)
    if not t or not t["branch"]:
        return _fail(f"la tarea #{args.id} no tiene rama")
    if not args.yes and input(f"¿Borrar worktree y rama {t['branch']}? [s/N] ").strip().lower() not in ("s", "si", "sí", "y"):
        return _fail("no descartado")
    try:
        _ws(store, t).remove()
    except workspace.GitError as e:
        print(f"Aviso: {e}")
    store.update_task(t["id"], status="discarded", finished_at=_now())
    print("Descartada.")
    return 0


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # la consola de Windows no es UTF-8 por defecto
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="localharness", description="Banco local de agentes")
    ap.add_argument("--db", help=f"base de datos SQLite (por defecto {DEFAULT_DB})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="comprueba git, CLIs y login").set_defaults(fn=cmd_doctor)

    p = sub.add_parser("project", help="proyectos (repos git)")
    p.add_argument("action", choices=["add", "list"])
    p.add_argument("name", nargs="?"); p.add_argument("path", nargs="?")
    p.set_defaults(fn=cmd_project)

    p = sub.add_parser("agent", help="agentes (configuraciones de proveedor)")
    p.add_argument("action", choices=["add", "list"]); p.add_argument("name", nargs="?")
    p.add_argument("--provider", default="claude"); p.add_argument("--model"); p.add_argument("--role")
    p.add_argument("--max-turns", type=int); p.add_argument("--budget", type=float, help="tope en USD por tarea")
    p.add_argument("--read-only", action="store_true"); p.add_argument("--tools", help="lista blanca, p. ej. Read,Edit,Write")
    p.add_argument("--binary", help="ruta del ejecutable si no es el del PATH")
    p.set_defaults(fn=cmd_agent)

    p = sub.add_parser("run", help="ejecuta una petición en un worktree aislado")
    p.add_argument("project"); p.add_argument("prompt"); p.add_argument("--agent", required=True)
    p.add_argument("--title"); p.add_argument("--timeout", type=float, default=1800.0)
    p.set_defaults(fn=cmd_run)

    sub.add_parser("tasks", help="lista tareas").set_defaults(fn=cmd_tasks)
    p = sub.add_parser("show", help="detalle de una tarea"); p.add_argument("id", type=int)
    p.add_argument("--diff", action="store_true"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("merge", help="integra una tarea en revisión (sin push)"); p.add_argument("id", type=int)
    p.add_argument("--into"); p.add_argument("--yes", action="store_true"); p.set_defaults(fn=cmd_merge)
    p = sub.add_parser("discard", help="borra worktree y rama de una tarea"); p.add_argument("id", type=int)
    p.add_argument("--yes", action="store_true"); p.set_defaults(fn=cmd_discard)

    args = ap.parse_args(argv)
    if args.cmd in ("project", "agent") and args.action == "add" and not args.name:
        ap.error("falta el nombre")
    if args.cmd == "project" and args.action == "add" and not args.path:
        ap.error("falta la ruta del repo")
    if args.cmd == "doctor":
        return cmd_doctor(args)
    store = _store(args)
    try:
        return args.fn(args, store)
    finally:
        store.close()
