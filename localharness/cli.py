"""Línea de órdenes de LocalHarness (M1). Nunca hace push: integrar pide confirmación y el push es tuyo.

    python -m localharness doctor
    python -m localharness project add <nombre> <ruta-repo>
    python -m localharness agent add <nombre> --provider claude [--model M] [--max-turns N] [--budget USD]
    python -m localharness run <proyecto> "<petición>" --agent <nombre>
    python -m localharness tasks | show <id> [--diff] | merge <id> [--into rama] | discard <id>
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from localharness import actions, settings, workspace
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
    settings.apply(store)
    n = store.mark_interrupted()
    if n:
        print(f"Aviso: {n} tarea(s) que quedaron a medias se marcan como 'interrupted'.")
    return store


def _fail(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return 1


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
    if args.action == "memory":
        p = store.find_project(args.name or "")
        if not p:
            return _fail(f"no existe el proyecto {args.name!r}")
        d = Path(args.path).resolve() if args.path else DEFAULT_DB.parent / "memory" / p["name"]
        d.mkdir(parents=True, exist_ok=True)
        store.set_project_memory(p["id"], str(d))
        print(f"Memoria de {p['name']}: {d}  (los .md de esa carpeta se inyectan en cada tarea, solo lectura)")
        return 0
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


def cmd_skills(args, store: Store | None = None) -> int:
    from localharness.context import load_skills, skill_dirs
    print("carpetas: " + ", ".join(map(str, skill_dirs())) + "   (añade más con LOCALHARNESS_SKILL_DIRS)")
    for s in load_skills().values():
        print(f"  {s.name:32} {s.description[:90]}")
    return 0


def cmd_cleanup(args, store: Store) -> int:
    from localharness.maintenance import cleanup
    r = cleanup(store, dry_run=args.dry_run)
    verb = "se borraría" if args.dry_run else "borrado"
    for i in r["removed"]:
        print(f"  {verb}: {i['project']} {i['branch']} ({i['status']})")
    for i in r["kept"]:
        print(f"  se conserva: {i['project']} {i['branch']} ({i['status']})")
    for i in r["unknown"]:
        print(f"  desconocido (no se toca): {i['project']} {i['branch']}")
    for e in r["errors"]:
        print(f"  error: {e}")
    if not any(r.values()):
        print("Nada que limpiar.")
    return 1 if r["errors"] else 0


def cmd_agent(args, store: Store) -> int:
    if args.action == "add":
        if args.provider not in ADAPTERS:
            return _fail(f"proveedor desconocido {args.provider!r} (hay: {', '.join(ADAPTERS)})")
        cfg = {k: v for k, v in {"max_turns": args.max_turns, "max_budget_usd": args.budget,
                                 "read_only": args.read_only or None,
                                 "tools": args.tools.split(",") if args.tools else None,
                                 "binary": args.binary, "base_url": args.base_url,
                                 "skills": args.skill or None}.items() if v is not None}
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
    task = store.add_task(project["id"], title, args.prompt, agent["id"], skills=args.skill or [])
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
    return 0 if t["status"] in ("review", "done") else 1


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
    r = actions.review_data(store, t)
    if r["available"]:
        print("\n" + (r["diff"] if args.diff else r["stat"] or "(sin cambios)"))
    return 0


def _confirm(question: str) -> bool:
    return input(f"{question} [s/N] ").strip().lower() in ("s", "si", "sí", "y")


def cmd_merge(args, store: Store) -> int:
    t = store.get_task(args.id)
    if not t or t["status"] not in actions.REVIEWABLE:
        return _fail(f"solo se integran tareas en revisión (#{args.id}: {t and t['status']})")
    r = actions.review_data(store, t)
    print(r["stat"])
    target = args.into or r["target"]
    if not args.yes and not _confirm(f"¿Integrar {t['branch']} en {target}? Nunca se hace push."):
        return _fail("no integrado")
    try:
        actions.merge(store, t["id"], args.into)
    except actions.ActionError as e:
        return _fail(str(e))
    print(f"Integrado en {target}. El push lo haces tú cuando quieras.")
    return 0


def cmd_discard(args, store: Store) -> int:
    t = store.get_task(args.id)
    if not t:
        return _fail(f"no existe la tarea #{args.id}")
    if not args.yes and not _confirm(f"¿Borrar worktree y rama {t['branch']}?"):
        return _fail("no descartado")
    try:
        actions.discard(store, t["id"])
    except actions.ActionError as e:
        return _fail(str(e))
    print("Descartada.")
    return 0


def _hier(store: Store):
    from localharness.hierarchy import Hierarchy
    return Hierarchy(store, on_event=_print_event)


def _print_plan(store: Store, pid: int) -> None:
    p = store.get_plan(pid)
    print(f"\nPlan #{p['id']}  estado {p['status']}  nivel {p['level'] or '-'}  coste equiv. {p['cost_usd'] or 0:.4f} $")
    for r in json.loads(p["level_reasons"] or "[]"):
        print(f"  motivo: {r}")
    if p["error"]:
        print(f"  aviso: {p['error']}")
    for t in store.plan_tasks(pid):
        who = f" (aprobó {t['approved_by']})" if t["approved_by"] else ""
        print(f"  #{t['id']:<4} {t['kind']:9} {t['status']:9} {t['level'] or '-':3} {t['title']}{who}")
        if t["kind"] == "worker" and t["status"] == "review":
            for r in json.loads(t["level_reasons"] or "[]"):
                print(f"         · {r}")


def _drive(store: Store, pid: int, plan_first: bool) -> int:
    h = _hier(store)
    try:
        p = asyncio.run(h.plan(pid)) if plan_first else store.get_plan(pid)
        if p["status"] in ("approved", "paused"):
            p = asyncio.run(h.run(pid))
    except (actions.ActionError, workspace.GitError) as e:
        return _fail(str(e))
    _print_plan(store, pid)
    hints = {"awaiting_you": f"Aprueba el plan: python -m localharness plan approve {pid}",
             "paused": "Decide la subtarea: python -m localharness plan decide <id> --approve | --reject",
             "ready": f"Revisa: git diff main...{p['branch']}   ·   integra: python -m localharness plan merge {pid}"}
    if p["status"] in hints:
        print(hints[p["status"]])
    return 0 if p["status"] not in ("failed", "cancelled") else 1


def cmd_plan(args, store: Store) -> int:
    if args.action == "new":
        project = store.find_project(args.target or "")
        director = store.find_agent(args.director or "")
        reviewer = store.find_agent(args.reviewer) if args.reviewer else None
        if not project or not director or not args.request:
            return _fail("uso: plan new <proyecto> \"<petición>\" --director <agente> [--reviewer <agente>]")
        if args.reviewer and not reviewer:
            return _fail(f"no existe el agente {args.reviewer!r}")
        p = store.add_plan(project["id"], args.request, director["id"], reviewer["id"] if reviewer else None)
        print(f"Plan #{p['id']} con Director {director['name']}" + (f" y jefe técnico {reviewer['name']}" if reviewer else ""))
        return _drive(store, p["id"], plan_first=True)
    if args.action == "list":
        for p in store.list_plans():
            print(f"#{p['id']:<4} {p['status']:12} {p['level'] or '-':3} {(p['cost_usd'] or 0):.4f}$  {p['request'][:60]}")
        return 0
    if args.action == "inbox":
        from localharness.hierarchy import inbox
        items = inbox(store)
        for i in items:
            ref = f"plan #{i['plan_id']}" + (f" tarea #{i['task_id']}" if i.get("task_id") else "") if i.get("plan_id") else f"tarea #{i['task_id']}"
            print(f"[{i['level']}] {i['type']:14} {ref:22} {i['title']}  — {'; '.join(i['reasons'])}")
        if not items:
            print("Nada pendiente de ti.")
        return 0
    try:
        ident = int(args.target)
    except (TypeError, ValueError):
        return _fail("falta el id")
    h = _hier(store)
    try:
        if args.action == "show":
            if not store.get_plan(ident):
                return _fail(f"no existe el plan #{ident}")
            _print_plan(store, ident)
            return 0
        if args.action == "approve":
            h.approve_plan(ident)
            return _drive(store, ident, plan_first=False)
        if args.action == "decide":
            if args.approve == args.reject:
                return _fail("indica --approve o --reject")
            t = h.decide_task(ident, approve=args.approve)
            return _drive(store, t["plan_id"], plan_first=False)
        if args.action == "merge":
            p = store.get_plan(ident)
            if not args.yes and not _confirm(f"¿Integrar {p and p['branch']} en tu rama actual? Nunca se hace push."):
                return _fail("no integrado")
            h.merge_plan(ident)
            print("Integrado. El push lo haces tú cuando quieras.")
            return 0
        if args.action == "reject":
            h.reject_plan(ident)
            print("Plan rechazado: rama y worktree borrados.")
            return 0
    except actions.ActionError as e:
        return _fail(str(e))
    return _fail(f"acción desconocida {args.action}")


def cmd_llama(args) -> int:
    from localharness import llama
    if args.action == "models":
        models = llama.list_models()
        print(f"llama-server: {llama.server_binary() or 'NO ENCONTRADO (define LOCALHARNESS_LLAMA_SERVER)'}")
        print("carpetas: " + (", ".join(map(str, llama.model_dirs())) or "ninguna (define LOCALHARNESS_MODEL_DIRS)"))
        for m in models:
            print(f"  {m.stat().st_size / 2**30:5.1f} GB  {m.name}")
        return 0
    if args.action == "status":
        import urllib.request
        url = f"http://127.0.0.1:{args.port}"
        try:
            with urllib.request.urlopen(url + "/v1/models", timeout=3) as r:
                data = json.loads(r.read())
            print(f"llama-server en {url}: {', '.join(m.get('id', '?') for m in data.get('data', []))}")
            return 0
        except OSError as e:
            return _fail(f"no responde llama-server en {url} ({e})")
    if not args.model:
        return _fail("uso: llama serve <nombre o parte del nombre del GGUF> [--port 8080 --ctx 16384 --ngl 99]")
    try:
        cmd = llama.serve_command(llama.find_model(args.model), args.port, args.ctx, args.ngl)
    except LookupError as e:
        return _fail(str(e))
    print("Lanzando: " + subprocess.list2cmdline(cmd))
    print(f"Agente para usarlo: python -m localharness agent add local-rev --provider local --role jefe "
          f"(servidor http://127.0.0.1:{args.port}). Ctrl+C para pararlo.")
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 0


def cmd_sandbox(args, store: Store) -> int:
    from localharness import sandbox
    path = Path(args.path) if args.path else sandbox.DEFAULT_PATH
    for line in sandbox.create(store, path, reset=args.reset):
        print(line)
    print("Entorno de pruebas listo. Guía: docs/PROBAR.md")
    return 0


def cmd_serve(args) -> int:
    try:
        import uvicorn
        from localharness.api import create_app
    except ImportError:
        return _fail("faltan dependencias del servidor: .venv/Scripts/python -m pip install -e .[server]")
    db = Path(args.db or os.environ.get("LOCALHARNESS_DB") or DEFAULT_DB)
    db.parent.mkdir(parents=True, exist_ok=True)
    print(f"LocalHarness en http://{args.host}:{args.port}  (base de datos {db})")
    from localharness.api import LOCAL_HOSTS
    # escuchar en otra dirección (p. ej. la LAN) es decisión explícita: entonces se acepta también ese nombre
    hosts = LOCAL_HOSTS if args.host in ("127.0.0.1", "localhost", "::1") else (*LOCAL_HOSTS, args.host)
    if args.host in ("0.0.0.0", "::"):
        hosts = None
        print("AVISO: escuchando en todas las interfaces y SIN contraseña: cualquiera de tu red puede usarlo")
    uvicorn.run(create_app(db, allowed_hosts=hosts), host=args.host, port=args.port, log_level="warning")
    return 0


def web_outdated(web: Path) -> bool:
    """¿Falta la web compilada o el código de la web es más nuevo que lo compilado? (p. ej. tras un git pull)"""
    dist = web / "dist" / "index.html"
    if not dist.is_file():
        return True
    built = dist.stat().st_mtime
    sources = [web / "index.html", web / "package.json", web / "vite.config.ts", *(web / "src").rglob("*"),
               *(web / "public").rglob("*")]
    return any(p.is_file() and p.stat().st_mtime > built + 1 for p in sources)


def rebuild_web(web: Path) -> bool:
    npm = shutil.which("npm")
    if not npm:
        print("Aviso: la web compilada está desactualizada o falta, y no encuentro Node.js (npm) para compilarla.")
        print("Instálalo desde https://nodejs.org y ejecuta Actualizar.bat. Mientras, verás la versión anterior.")
        return False
    print("La web ha cambiado desde la última vez: compilándola (tarda un poco)...")
    for cmd in ([npm, "install", "--no-audit", "--no-fund", "--loglevel=error"], [npm, "run", "build"]):
        if subprocess.run(cmd, cwd=web).returncode != 0:
            print("Aviso: no se pudo compilar la web; verás la versión anterior. Ejecuta Actualizar.bat.")
            return False
    return True


def cmd_start(args) -> int:
    """Para el usuario básico (doble clic en LocalHarness.bat o el icono): si ya está en marcha, solo abre el
    navegador; si no, arranca el servidor (y el último modelo local si lo pediste en Modelos) y abre la GUI."""
    import threading
    import urllib.request
    import webbrowser
    url = f"http://127.0.0.1:{args.port}"

    def alive() -> bool:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1.5) as r:
                return r.status == 200 and b"providers" in r.read()
        except OSError:
            return False

    if alive():
        print(f"LocalHarness ya estaba en marcha: abro {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0
    web = Path(__file__).resolve().parent.parent / "web"
    if web_outdated(web):
        rebuild_web(web)

    def open_when_ready() -> None:
        for _ in range(120):
            if alive():
                webbrowser.open(url)
                return
            time.sleep(0.5)

    if not args.no_browser:
        threading.Thread(target=open_when_ready, daemon=True).start()
    print("No cierres esta ventana mientras uses LocalHarness (al cerrarla se apaga, también el modelo local).")
    args.host = "127.0.0.1"
    return cmd_serve(args)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # la consola de Windows no es UTF-8 por defecto
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="localharness", description="Banco local de agentes")
    ap.add_argument("--db", help=f"base de datos SQLite (por defecto {DEFAULT_DB})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="comprueba git, CLIs y login").set_defaults(fn=cmd_doctor)

    p = sub.add_parser("serve", help="API + GUI web (M2)")
    p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8095)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("start", help="arranca todo y abre la GUI en el navegador (lo que usa el icono)")
    p.add_argument("--port", type=int, default=8095); p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("project", help="proyectos (repos git)")
    p.add_argument("action", choices=["add", "list", "memory"])
    p.add_argument("name", nargs="?"); p.add_argument("path", nargs="?")
    p.set_defaults(fn=cmd_project)

    sub.add_parser("skills", help="lista las skills disponibles (M5)").set_defaults(fn=cmd_skills)

    p = sub.add_parser("agent", help="agentes (configuraciones de proveedor)")
    p.add_argument("action", choices=["add", "list"]); p.add_argument("name", nargs="?")
    p.add_argument("--provider", default="claude"); p.add_argument("--model"); p.add_argument("--role")
    p.add_argument("--max-turns", type=int); p.add_argument("--budget", type=float, help="tope en USD por tarea")
    p.add_argument("--read-only", action="store_true"); p.add_argument("--tools", help="lista blanca, p. ej. Read,Edit,Write")
    p.add_argument("--binary", help="ruta del ejecutable si no es el del PATH")
    p.add_argument("--base-url", help="local: URL de llama-server (por defecto http://127.0.0.1:8080)")
    p.add_argument("--skill", action="append", help="skill que este agente usa siempre (repetible)")
    p.set_defaults(fn=cmd_agent)

    p = sub.add_parser("run", help="ejecuta una petición en un worktree aislado")
    p.add_argument("project"); p.add_argument("prompt"); p.add_argument("--agent", required=True)
    p.add_argument("--title"); p.add_argument("--timeout", type=float, default=1800.0)
    p.add_argument("--skill", action="append", help="skill a inyectar (repetible); ver: python -m localharness skills")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("plan", help="M3: Director → subtareas → jefe técnico → tú")
    p.add_argument("action", choices=["new", "list", "show", "approve", "decide", "merge", "reject", "inbox"])
    p.add_argument("target", nargs="?", help="proyecto (new) o id de plan/tarea")
    p.add_argument("request", nargs="?", help="petición (new)")
    p.add_argument("--director"); p.add_argument("--reviewer")
    p.add_argument("--approve", action="store_true"); p.add_argument("--reject", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("llama", help="M4: modelos locales con llama-server")
    p.add_argument("action", choices=["models", "serve", "status"]); p.add_argument("model", nargs="?")
    p.add_argument("--port", type=int, default=8080); p.add_argument("--ctx", type=int, default=16384)
    p.add_argument("--ngl", type=int, default=99, help="capas en GPU (99 = todas)")
    p.set_defaults(fn=cmd_llama)

    p = sub.add_parser("sandbox", help="crea un repo de pruebas con fallos y agentes ya configurados")
    p.add_argument("path", nargs="?"); p.add_argument("--reset", action="store_true")
    p.set_defaults(fn=cmd_sandbox)

    p = sub.add_parser("cleanup", help="M6: borra worktrees y ramas de tareas/planes ya cerrados")
    p.add_argument("--dry-run", action="store_true", help="solo dice qué borraría")
    p.set_defaults(fn=cmd_cleanup)

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
    if args.cmd in ("doctor", "serve", "start", "llama", "skills"):
        return args.fn(args)
    store = _store(args)
    try:
        return args.fn(args, store)
    finally:
        store.close()
