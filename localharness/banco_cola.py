"""Cola del banco de pruebas: tandas que se montan desde la web (pestaña Banco) y se corren solas, una detrás de otra.

Una **tanda** es prueba × modalidad × contendiente × repeticiones (p. ej. «Supersalto libre con gpt-oss + Qwen 4B y el
Jefe local 2, 5 veces»). El contendiente va dentro de la tanda (lo que se eligió en la web) con la misma forma que
banco/contendientes/*.json. Varias tandas seguidas = «5 con estos modelos, luego 5 con estos otros».

La cola vive en data/banco/cola.json. La procesa un proceso aparte (`python -m localharness banco cola`), que el
servidor arranca al pulsar «Empezar» y que habla con LocalHarness por su API como el autopiloto; su salida va a
data/banco/cola.log. Parar: «al acabar la ejecución» (termina la que corre y no empieza otra) o «ya» (no empieza el
parche siguiente y se cancela la tarea en marcha; la ejecución queda «parada» y se puede seguir con `banco seguir`).
Si el proceso muere a medias (se apagó el PC), la tanda queda «en marcha»: al volver a empezar, retoma esa ejecución.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from statistics import mean

from localharness import autopilot, banco

COLA = banco.DATOS / "cola.json"
LOG = banco.DATOS / "cola.log"
ESTADOS = ("pendiente", "en marcha", "hecha", "parada", "error")
NOMBRE_OK = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$")


# --- el archivo (lo tocan el servidor y el proceso de la cola: escritura con cerrojo y reemplazo atómico)
def _vacia() -> dict:
    return {"tandas": [], "parar": None, "proceso": None}


def leer(path: Path | None = None) -> dict:
    path = path or COLA
    try:
        return {**_vacia(), **json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return _vacia()


def editar(fn: Callable[[dict], object], path: Path | None = None) -> dict:
    """Lee, aplica `fn` (que cambia el dict) y guarda, con un cerrojo de archivo para que el servidor y el proceso de
    la cola no se pisen."""
    path = path or COLA
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    for _ in range(200):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - lock.stat().st_mtime > 30:  # cerrojo huérfano (un proceso murió con él)
                lock.unlink(missing_ok=True)
            time.sleep(0.05)
    else:
        raise RuntimeError("la cola del banco está bloqueada")
    try:
        cola = leer(path)
        fn(cola)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cola, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
        return cola
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def _tanda(cola: dict, tid: str) -> dict:
    t = next((t for t in cola["tandas"] if t["id"] == tid), None)
    if t is None:
        raise KeyError(tid)
    return t


# --- montar la cola
def contendiente(c: dict) -> dict:
    """El contendiente de una tanda, validado y con los valores por defecto de cargar_contendiente."""
    nombre = str(c.get("nombre") or "").strip().lower()
    if not NOMBRE_OK.match(nombre):
        raise ValueError("el nombre del contendiente: minúsculas, números, «-», «_» o «.» (máx. 60)")
    out = {"agente": "Jefe local", "horas": 12, "minutos_tarea": 45, "presupuesto": 1.0,
           **{k: v for k, v in c.items() if v not in (None, "", {})}, "nombre": nombre}
    for k, lo, hi in (("horas", 0.1, 48), ("minutos_tarea", 1, 240), ("presupuesto", 0, 100), ("linea", 0, 5),
                      ("reparar", 0, 5)):
        if k in out:
            v = float(out[k])
            if not lo <= v <= hi:
                raise ValueError(f"«{k}» tiene que estar entre {lo} y {hi}")
            out[k] = int(v) if k in ("linea", "reparar") else v
    if out.get("relevo") and not (banco.DATOS / out["relevo"] / "resultado.json").is_file():
        raise ValueError(f"no existe la ejecución de relevo «{out['relevo']}»")
    return out


def anadir(prueba: str, modalidad: str, repeticiones: int, cont: dict, path: Path | None = None,
           base: Path | None = None) -> dict:
    p = banco.cargar_prueba(prueba, base or banco.BANCO)
    if modalidad not in p.modalidades:
        raise ValueError(f"«{prueba}» no tiene la modalidad «{modalidad}» (tiene: {', '.join(p.modalidades)})")
    if not 1 <= int(repeticiones) <= 50:
        raise ValueError("repeticiones: de 1 a 50")
    t = {"id": uuid.uuid4().hex[:8], "prueba": prueba, "modalidad": modalidad, "repeticiones": int(repeticiones),
         "contendiente": contendiente(cont), "estado": "pendiente", "hechas": [], "actual": None,
         "error": None, "creada": datetime.now().isoformat(timespec="seconds")}
    editar(lambda c: c["tandas"].append(t), path)
    return t


def quitar(tid: str, path: Path | None = None) -> None:
    def fn(c):
        if _tanda(c, tid)["estado"] == "en marcha" and vivo(c):
            raise ValueError("esa tanda está corriendo: para la cola antes")
        c["tandas"] = [t for t in c["tandas"] if t["id"] != tid]
    editar(fn, path)


def mover(tid: str, delta: int, path: Path | None = None) -> None:
    def fn(c):
        ts = c["tandas"]
        i = ts.index(_tanda(c, tid))
        j = max(0, min(len(ts) - 1, i + delta))
        ts.insert(j, ts.pop(i))
    editar(fn, path)


def reabrir(tid: str, path: Path | None = None) -> None:
    """Una tanda parada o con error vuelve a pendiente: sigue con las repeticiones que le falten."""
    def fn(c):
        t = _tanda(c, tid)
        if t["estado"] == "hecha":  # una hecha que se reabre: una repetición más
            t["repeticiones"] += 1
        if t["estado"] in ("parada", "error", "hecha"):
            t["estado"], t["error"] = "pendiente", None
    editar(fn, path)


def guardar_contendiente(c: dict, sobrescribir: bool = False, base: Path | None = None) -> Path:
    """El contendiente montado en la web, como banco/contendientes/<nombre>.json (para reutilizarlo o pasarlo por
    la CLI)."""
    c = contendiente(c)
    f = (base or banco.BANCO) / "contendientes" / f"{c['nombre']}.json"
    if f.exists() and not sobrescribir:
        raise FileExistsError(f"ya hay un contendiente «{c['nombre']}»")
    f.write_text(json.dumps({k: v for k, v in c.items() if k != "nombre"}, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return f


# --- el proceso que la corre
def vivo(cola: dict) -> bool:
    p = cola.get("proceso") or {}
    if not p.get("pid"):
        return False
    try:
        import psutil
        proc = psutil.Process(int(p["pid"]))
        return proc.is_running() and abs(proc.create_time() - float(p.get("creado") or 0)) < 2
    except Exception:  # noqa: BLE001 — no existe, sin permiso o sin psutil: se da por muerto
        return False


def empezar(url: str, path: Path | None = None, log: Path = LOG) -> bool:
    """Arranca el proceso de la cola si no está ya. False si ya corría."""
    cola = leer(path)
    if vivo(cola):
        return False
    editar(lambda c: c.update(parar=None), path)
    log.parent.mkdir(parents=True, exist_ok=True)
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
    with open(log, "a", encoding="utf-8") as out:
        out.write(f"\n[{datetime.now():%d/%m %H:%M}] Empieza la cola\n")
        out.flush()
        proc = subprocess.Popen([sys.executable, "-m", "localharness", "banco", "cola", "--url", url],
                                cwd=str(banco.RAIZ), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=flags, env={**os.environ, "PYTHONIOENCODING": "utf-8",
                                                          "PYTHONUNBUFFERED": "1"})
    try:
        import psutil
        creado = psutil.Process(proc.pid).create_time()
    except Exception:  # noqa: BLE001
        creado = time.time()
    editar(lambda c: c.update(proceso={"pid": proc.pid, "creado": creado,
                                       "inicio": datetime.now().isoformat(timespec="seconds")}), path)
    return True


def parar(modo: str, api: Callable | None = None, path: Path | None = None) -> None:
    """«despues»: acaba la ejecución en marcha y no empieza otra. «ya»: además no empieza el parche siguiente y
    cancela la tarea en marcha de la ejecución actual."""
    if modo not in ("despues", "ya"):
        raise ValueError("modo: despues o ya")
    cola = editar(lambda c: c.update(parar=modo), path)
    if modo != "ya" or api is None:
        return
    actual = next((t.get("actual") for t in cola["tandas"] if t["estado"] == "en marcha" and t.get("actual")), None)
    if not actual:
        return
    try:
        proyecto = json.loads((banco.DATOS / actual / "resultado.json").read_text(encoding="utf-8"))["proyecto"]
        pid = next(p["id"] for p in api("GET", "/api/projects") if p["name"] == proyecto)
        for t in api("GET", "/api/tasks"):
            if t.get("project_id") == pid and t.get("status") in ("running", "pending"):
                api("POST", f"/api/tasks/{t['id']}/cancel")
    except (OSError, ValueError, KeyError, StopIteration, autopilot.ApiError):
        pass


def correr(api: Callable, say: Callable[[str], None] = print, path: Path | None = None, datos: Path = banco.DATOS,
           proyectos: Path = banco.PROYECTOS, base: Path = banco.BANCO, piloto: type = autopilot.Autopilot,
           **kw) -> None:
    """Procesa la cola hasta vaciarla o hasta que pidan parar. Lo llama `banco cola` (el proceso aparte)."""
    def parada() -> bool:
        return leer(path).get("parar") is not None

    def para_ya() -> bool:
        return leer(path).get("parar") == "ya"

    try:
        while not parada():
            cola = leer(path)
            t = next((t for t in cola["tandas"] if t["estado"] in ("en marcha", "pendiente")), None)
            if t is None:
                say("Cola vacía.")
                break
            tid = t["id"]
            editar(lambda c: _tanda(c, tid).update(estado="en marcha"), path)
            try:
                prueba = banco.cargar_prueba(t["prueba"], base)
                while len(t["hechas"]) < t["repeticiones"] and not parada():
                    if t.get("actual"):  # se cortó a medias: se retoma esa ejecución
                        ej = banco.Ejecucion(datos / t["actual"])
                        say(f"\n=== Sigo {t['actual']}")
                    else:
                        ej = banco.Ejecucion.nueva(api, prueba, t["modalidad"], t["contendiente"], datos=datos,
                                                   proyectos=proyectos)
                        ej.datos.update(tanda=tid, repeticion=len(t["hechas"]) + 1)
                        ej.guardar()
                        ide = f"{ej.carpeta.parent.name}/{ej.carpeta.name}"
                        editar(lambda c: _tanda(c, tid).update(actual=ide), path)
                        say(f"\n=== {prueba.titulo} ({t['modalidad']}) · {t['contendiente']['nombre']} · "
                            f"repetición {len(t['hechas']) + 1}/{t['repeticiones']} · {ide}")
                    d = ej.correr(api, say=say, piloto=piloto, stop=para_ya, **kw)
                    ide = f"{ej.carpeta.parent.name}/{ej.carpeta.name}"
                    say(f"=== nota {(d.get('examen_final') or {}).get('nota')} % · "
                        f"{d['totales'].get('integrados')}/{d['parches_total']} integrados · {d['estado']}")
                    if d["estado"] != "terminada":  # parada a mitad: queda como actual para seguirla luego
                        break

                    def hecha(c, ide=ide):
                        x = _tanda(c, tid)
                        x["hechas"].append(ide)
                        x["actual"] = None
                    t = editar(hecha, path)
                    t = _tanda(t, tid)
                fin = "hecha" if len(t["hechas"]) >= t["repeticiones"] else "parada"
                editar(lambda c: _tanda(c, tid).update(estado=fin), path)
            except Exception as e:  # noqa: BLE001 — una tanda que falla no para la cola
                say(f"=== la tanda {tid} falló: {e}")
                # sin `actual`: al reabrirla empieza una ejecución nueva en vez de retomar la que falló
                editar(lambda c: _tanda(c, tid).update(estado="error", error=str(e)[:500], actual=None), path)
    finally:
        editar(lambda c: c.update(proceso=None, parar=None), path)


# --- resultados: por configuración (prueba × modalidad × contendiente), con varias tiradas
def _fila(d: dict) -> dict:
    t = d.get("totales") or {}
    return {"nota": t.get("nota"), "integrados": t.get("integrados"), "parches": d.get("parches_total"),
            "minutos": round((t.get("segundos") or 0) / 60, 1), "estado": d.get("estado")}


def ejecucion_corta(ide: str, datos: Path | None = None) -> dict | None:
    datos = datos or banco.DATOS
    try:
        d = json.loads((datos / ide / "resultado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {"id": ide, **_fila(d)}


def resumen(datos: Path | None = None) -> list[dict]:
    """Una fila por configuración con todas sus ejecuciones terminadas: tiradas, media, mejor y peor nota,
    integrados y minutos de media. Las paradas o en marcha no cuentan (sesgarían la media)."""
    grupos: dict[tuple, list[dict]] = {}
    for e in banco.ejecuciones(datos or banco.DATOS):
        if e.get("estado") != "terminada" or (e.get("totales") or {}).get("nota") is None:
            continue
        clave = (e["prueba"], e["modalidad"], e["contendiente"])
        grupos.setdefault(clave, []).append(e)
    out = []
    for (prueba, modalidad, cont), es in grupos.items():
        notas = [e["totales"]["nota"] for e in es]
        out.append({"prueba": prueba, "modalidad": modalidad, "contendiente": cont, "agente": es[-1].get("agente"),
                    "descripcion": es[-1].get("descripcion", ""), "tiradas": len(es), "media": round(mean(notas), 1),
                    "mejor": max(notas), "peor": min(notas),
                    "integrados": round(mean(e["totales"].get("integrados") or 0 for e in es), 1),
                    "parches": es[-1].get("parches_total"),
                    "minutos": round(mean((e["totales"].get("segundos") or 0) / 60 for e in es), 1),
                    "ultima": max(e.get("inicio") or "" for e in es), "ids": [e["id"] for e in es]})
    return sorted(out, key=lambda g: (g["prueba"], g["modalidad"], -g["media"]))


def estado(path: Path | None = None, datos: Path | None = None, log: Path | None = None) -> dict:
    datos, log = datos or banco.DATOS, log or LOG
    cola = leer(path)
    for t in cola["tandas"]:
        t["resultados"] = [r for r in (ejecucion_corta(i, datos) for i in t["hechas"]) if r]
        notas = [r["nota"] for r in t["resultados"] if r["nota"] is not None]
        t["media"] = round(mean(notas), 1) if notas else None
        t["en_curso"] = ejecucion_corta(t["actual"], datos) if t.get("actual") else None
        if t["en_curso"]:
            try:
                d = json.loads((datos / t["actual"] / "resultado.json").read_text(encoding="utf-8"))
                t["en_curso"]["hechos"] = len(d.get("parches") or [])
            except (OSError, ValueError):
                pass
    try:
        cola["log"] = log.read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        cola["log"] = ""
    cola["corriendo"] = vivo(cola)
    return cola
