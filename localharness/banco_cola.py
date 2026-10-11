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
REINTENTOS_API = 2  # fallos pasajeros de la API seguidos que aguanta una tanda
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
           base: Path | None = None, repertorio: str | None = None) -> dict:
    """Una tanda: una prueba larga `repeticiones` veces o, con `repertorio`, `repeticiones` vueltas a sus casos."""
    base = base or banco.BANCO
    if not 1 <= int(repeticiones) <= 50:
        raise ValueError("repeticiones: de 1 a 50")
    extra: dict = {}
    if repertorio:
        r = banco.cargar_repertorio(repertorio, base)
        prueba, modalidad = repertorio, "repertorio"
        extra = {"repertorio": repertorio, "casos": r["casos"], "minutos_caso": r["minutos_tarea"]}
    else:
        p = banco.cargar_prueba(prueba, base)
        if modalidad not in p.modalidades:
            raise ValueError(f"«{prueba}» no tiene la modalidad «{modalidad}» (tiene: {', '.join(p.modalidades)})")
    t = {"id": uuid.uuid4().hex[:8], "prueba": prueba, "modalidad": modalidad, "repeticiones": int(repeticiones),
         "contendiente": contendiente(cont), "estado": "pendiente", "hechas": [], "actual": None,
         "error": None, "creada": datetime.now().isoformat(timespec="seconds"), **extra}
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


def plan(t: dict) -> list[tuple[str, str]]:
    """Las ejecuciones de una tanda, en orden: (prueba, modalidad). Un repertorio: cada vuelta, todos sus casos."""
    if t.get("repertorio"):
        return [(c, "caso") for _ in range(t["repeticiones"]) for c in t["casos"]]
    return [(t["prueba"], t["modalidad"])] * t["repeticiones"]


def contendiente_de(t: dict) -> dict:
    """El contendiente con los topes de la tanda: en un repertorio, cada caso es un parche corto."""
    c = dict(t["contendiente"])
    if t.get("repertorio"):
        c["minutos_tarea"] = min(float(c.get("minutos_tarea") or 45), float(t.get("minutos_caso") or 15))
        c["horas"] = min(float(c.get("horas") or 12), 2.0)
        c.pop("relevo", None)
    return c


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
           espera: Callable[[float], None] = time.sleep, **kw) -> None:
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
                todo = plan(t)
                while len(t["hechas"]) < len(todo) and not parada():
                    i = len(t["hechas"])
                    nombre, modalidad = todo[i]
                    prueba = banco.cargar_prueba(nombre, base)
                    if t.get("actual"):  # se cortó a medias: se retoma esa ejecución
                        ej = banco.Ejecucion(datos / t["actual"])
                        say(f"\n=== Sigo {t['actual']}")
                    else:
                        ej = banco.Ejecucion.nueva(api, prueba, modalidad, contendiente_de(t), datos=datos,
                                                   proyectos=proyectos)
                        vuelta = i // len(t["casos"]) + 1 if t.get("repertorio") else i + 1
                        ej.datos.update(tanda=tid, repeticion=vuelta, repertorio=t.get("repertorio"))
                        ej.guardar()
                        ide = f"{ej.carpeta.parent.name}/{ej.carpeta.name}"
                        editar(lambda c: _tanda(c, tid).update(actual=ide), path)
                        say(f"\n=== {prueba.titulo} ({modalidad}) · {t['contendiente']['nombre']} · "
                            f"{i + 1}/{len(todo)} · {ide}")
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
                        x["fallos"] = 0
                    t = editar(hecha, path)
                    t = _tanda(t, tid)
                fin = "hecha" if len(t["hechas"]) >= len(plan(t)) else "parada"
                editar(lambda c: _tanda(c, tid).update(estado=fin), path)
            except autopilot.ApiError as e:
                # un fallo pasajero de la API (un 500, LocalHarness reiniciándose): se reintenta la misma ejecución
                # hasta 2 veces seguidas antes de dar la tanda por fallida; las hechas se conservan
                fallos = int(_tanda(leer(path), tid).get("fallos") or 0) + 1
                if fallos <= REINTENTOS_API:
                    say(f"=== fallo de la API ({e}); lo reintento ({fallos}/{REINTENTOS_API})")
                    editar(lambda c: _tanda(c, tid).update(fallos=fallos, actual=None), path)
                    espera(30)
                    continue
                say(f"=== la tanda {tid} falló: {e}")
                editar(lambda c: _tanda(c, tid).update(estado="error", error=str(e)[:500], actual=None), path)
            except Exception as e:  # noqa: BLE001 — una tanda que falla no para la cola
                say(f"=== la tanda {tid} falló: {e}")
                # sin `actual`: al reabrirla empieza una ejecución nueva en vez de retomar la que falló
                editar(lambda c: _tanda(c, tid).update(estado="error", error=str(e)[:500], actual=None), path)
    finally:
        editar(lambda c: c.update(proceso=None, parar=None), path)


# --- resultados: por configuración (prueba × modalidad × contendiente), con varias tiradas
def _fila(d: dict) -> dict:
    t = d.get("totales") or {}
    ps = d.get("parches") or []
    return {"nota": t.get("nota"), "integrados": t.get("integrados"), "parches": d.get("parches_total"),
            "minutos": round((t.get("segundos") or 0) / 60, 1), "estado": d.get("estado"), "hechos": len(ps),
            "inicio": d.get("inicio"), "prueba": d.get("prueba"),
            # la nota del examen oculto tras cada parche (la gráfica en vivo de la pestaña Banco)
            "curva": [[x["n"], (x.get("examen") or {}).get("nota"), x.get("resultado")] for x in ps]}


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
        if e.get("estado") != "terminada" or (e.get("totales") or {}).get("nota") is None or e.get("modalidad") == "caso":
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


def matrices(datos: Path | None = None, base: Path | None = None) -> list[dict]:
    """Por repertorio: una fila por caso y una columna por contendiente, con tiradas terminadas, aprobados (nota 100)
    y nota media. Así se ve de un vistazo qué fallo concreto tiene cada configuración."""
    base = base or banco.BANCO
    celdas: dict[tuple[str, str], list[float]] = {}
    for e in banco.ejecuciones(datos or banco.DATOS):
        if e.get("modalidad") == "caso" and e.get("estado") == "terminada" and (e.get("totales") or {}).get("nota") is not None:
            celdas.setdefault((e["prueba"], e["contendiente"]), []).append(e["totales"]["nota"])
    out = []
    for r in banco.repertorios(base):
        conts = sorted({c for (caso, c) in celdas if caso in r["casos"]})
        filas = []
        for nombre in r["casos"]:
            pr = banco.cargar_prueba(nombre, base)
            fila = {"caso": nombre, "titulo": pr.titulo, "grupo": pr.grupo, "celdas": {}}
            for c in conts:
                notas = celdas.get((nombre, c))
                if notas:
                    fila["celdas"][c] = {"tiradas": len(notas), "aprobados": sum(n >= 100 for n in notas),
                                         "media": round(mean(notas), 1)}
            filas.append(fila)
        totales = {}
        for c in conts:
            hechos = [f["celdas"][c] for f in filas if c in f["celdas"]]
            totales[c] = {"casos": len(hechos), "aprobados": sum(h["aprobados"] for h in hechos),
                          "tiradas": sum(h["tiradas"] for h in hechos),
                          "media": round(mean(h["media"] for h in hechos), 1) if hechos else None}
        out.append({"repertorio": r["nombre"], "titulo": r["titulo"], "contendientes": conts, "filas": filas,
                    "totales": totales})
    return out


def estado(path: Path | None = None, datos: Path | None = None, log: Path | None = None) -> dict:
    datos, log = datos or banco.DATOS, log or LOG
    cola = leer(path)
    for t in cola["tandas"]:
        t["total"] = len(plan(t))
        t["resultados"] = [r for r in (ejecucion_corta(i, datos) for i in t["hechas"]) if r]
        notas = [r["nota"] for r in t["resultados"] if r["nota"] is not None]
        t["media"] = round(mean(notas), 1) if notas else None
        t["en_curso"] = ejecucion_corta(t["actual"], datos) if t.get("actual") else None
    try:
        cola["log"] = log.read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        cola["log"] = ""
    cola["corriendo"] = vivo(cola)
    return cola
