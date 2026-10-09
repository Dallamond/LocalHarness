"""Banco de pruebas: el mismo proyecto desde cero para cada contendiente (modelos + agente + flujo), con nota.

Una **prueba** (banco/pruebas/<nombre>/) es una semilla (encargo, docs, package.json), una o más **modalidades**
(lista de parches: «guiada» = parches detallados, «libre» = hitos grandes + CONTRATO.md) y un **examen oculto**
(examen/*.test.mjs) que los modelos no ven. Un **contendiente** (banco/contendientes/<nombre>.json) es qué modelo va
en cada servidor local, con qué agente y con qué topes:

    {"descripcion": "gpt-oss en la 3060 + Qwen 4B en la 1060", "agente": "Jefe local",
     "modelos": {"principal": "gpt-oss-20b-UD-Q4_K_XL", "rapido": "Qwen_Qwen3.5-4B-Q4_K_M"},
     "horas": 12, "minutos_tarea": 45, "presupuesto": 1}

`modelos` puede faltar (se usa lo que esté cargado, p. ej. con un agente de Claude), un servidor a null se apaga y
un modelo puede llevar opciones: {"modelo": "...", "opciones": {...}}.

Cada ejecución copia la semilla en un repo nuevo, lo da de alta en LocalHarness, carga los modelos y pasa la lista
con el autopiloto. Tras CADA parche pasa el examen oculto (la curva de nota) y apunta el commit, los archivos que
cambió y las líneas nuevas del CHANGELOG. Todo va a data/banco/<prueba>-<modalidad>/<contendiente>-<fecha>/
(resultado.json, informe.md, CHANGELOG.md, git-log.txt), que es lo que enseña la página /banco de LocalHarness.

Uso: python -m localharness banco correr --prueba cuentas-claras --modalidad guiada --contendiente gptoss-qwen4b
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from localharness import autopilot
from localharness.autopilot import ApiError, Result

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "banco"
DATOS = RAIZ / "data" / "banco"
PROYECTOS = Path(os.environ.get("LOCALHARNESS_PROYECTOS") or "D:/LocalHarness-proyectos") / "banco"
EXAMEN_S = 90  # tope por archivo del examen tras cada parche (un bucle infinito no puede comerse la noche)


@dataclass
class Prueba:
    nombre: str
    dir: Path
    titulo: str
    tipo: str
    descripcion: str
    check: str
    abrir: str
    modalidades: dict

    def lista(self, modalidad: str) -> list[str]:
        return autopilot.read_list(self.dir / self.modalidades[modalidad]["parches"])

    def ficha(self) -> dict:
        return {"nombre": self.nombre, "titulo": self.titulo, "tipo": self.tipo, "descripcion": self.descripcion,
                "abrir": self.abrir, "referencia": (self.dir / "referencia").is_dir(),
                "modalidades": {m: {"descripcion": c.get("descripcion", ""), "parches": len(self.lista(m))}
                                for m, c in self.modalidades.items()}}


def pruebas(banco: Path = BANCO) -> list[Prueba]:
    return [cargar_prueba(d.name, banco) for d in sorted((banco / "pruebas").iterdir()) if (d / "prueba.json").is_file()]


def cargar_prueba(nombre: str, banco: Path = BANCO) -> Prueba:
    d = banco / "pruebas" / nombre
    if not (d / "prueba.json").is_file():
        hay = ", ".join(p.name for p in (banco / "pruebas").iterdir() if (p / "prueba.json").is_file())
        raise ValueError(f"No hay ninguna prueba «{nombre}» (hay: {hay})")
    c = json.loads((d / "prueba.json").read_text(encoding="utf-8"))
    return Prueba(nombre, d, c.get("titulo", nombre), c.get("tipo", ""), c.get("descripcion", ""),
                  c.get("check", "npm test"), c.get("abrir", "index.html"), c["modalidades"])


def contendientes(banco: Path = BANCO) -> list[dict]:
    return [cargar_contendiente(f.stem, banco) for f in sorted((banco / "contendientes").glob("*.json"))]


def cargar_contendiente(nombre: str, banco: Path = BANCO) -> dict:
    f = banco / "contendientes" / f"{nombre}.json"
    if not f.is_file():
        hay = ", ".join(p.stem for p in (banco / "contendientes").glob("*.json"))
        raise ValueError(f"No hay ningún contendiente «{nombre}» (hay: {hay})")
    c = json.loads(f.read_text(encoding="utf-8"))
    return {"agente": "Jefe local", "horas": 12, "minutos_tarea": 45, "presupuesto": 1.0, **c, "nombre": nombre}


# --- el repo de cada ejecución
def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[:300]}")
    return p.stdout


def crear_repo(prueba: Prueba, modalidad: str, repo: Path) -> None:
    """Semilla (y la de la modalidad encima) en un repo nuevo con un único commit: el Parche 000."""
    if repo.exists():
        raise ValueError(f"Ya existe {repo}")
    shutil.copytree(prueba.dir / "semilla", repo)
    extra = prueba.modalidades[modalidad].get("semilla_extra")
    if extra:
        shutil.copytree(prueba.dir / extra, repo, dirs_exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Banco LocalHarness")
    git(repo, "config", "user.email", "banco@localharness")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "Parche 000: semilla del banco")


def examinar(prueba: Prueba, repo: Path, por_archivo: float = EXAMEN_S) -> dict:
    """Nota del examen oculto ({pasan, total, nota, filas}); si node falla, nota 0 con el motivo."""
    env = {**os.environ, "EXAMEN_TIMEOUT_S": str(int(por_archivo))}
    try:
        p = subprocess.run(["node", str(BANCO / "puntuar.mjs"), str(prueba.dir / "examen"), str(repo), "banco",
                            "--json"], capture_output=True, encoding="utf-8", errors="replace", env=env,
                           stdin=subprocess.DEVNULL, timeout=por_archivo * 12)
        return json.loads(p.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return {"pasan": 0, "total": 0, "nota": 0, "filas": [], "error": str(e)[:300]}


def cambios(repo: Path, desde: str) -> dict:
    """Commit actual, archivos tocados desde `desde` y líneas nuevas del CHANGELOG."""
    head = git(repo, "rev-parse", "HEAD").strip()
    if head == desde:
        return {"commit": head, "archivos": [], "changelog": []}
    archivos = [line.split("\t") for line in git(repo, "diff", "--name-status", desde, head).splitlines() if line]
    diff = git(repo, "diff", desde, head, "--", "CHANGELOG.md")
    nuevas = [line[1:].strip() for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
              and line[1:].strip()]
    return {"commit": head, "archivos": [{"estado": a[0][0], "ruta": a[-1]} for a in archivos], "changelog": nuevas}


# --- modelos
def cargar_modelos(api: Callable, modelos: dict | None, say: Callable[[str], None] = print) -> str:
    """Deja cada servidor local con el modelo del contendiente (o apagado si es null). Devuelve qué quedó cargado."""
    info = api("GET", "/api/llama")
    servidores = {s["id"]: s for s in info.get("servers") or []}
    disponibles = info.get("models") or []
    for srv, quiere in (modelos or {}).items():
        if srv not in servidores:
            raise ValueError(f"No hay ningún servidor local «{srv}» (hay: {', '.join(servidores)})")
        estado = servidores[srv]["status"]
        if quiere is None:
            if estado.get("state") not in ("off", "failed"):
                say(f"  apago {srv}")
                api("POST", f"/api/llama/stop?server={srv}")
            continue
        nombre, opciones = (quiere, None) if isinstance(quiere, str) else (quiere["modelo"], quiere.get("opciones"))
        m = next((m for m in disponibles if nombre in (m["name"], m["file"], m["path"])), None)
        if not m:
            raise ValueError(f"No encuentro el modelo «{nombre}» en las carpetas de modelos")
        if estado.get("state") not in ("off", "failed") and Path(str(estado.get("model") or "")).stem == Path(m["path"]).stem:
            continue
        say(f"  cargo {m['name']} en {srv}")
        api("POST", "/api/llama/start", {"path": m["path"], "server": srv, "options": opciones})
    return cargados(api)


def cargados(api: Callable) -> str:
    try:
        servers = api("GET", "/api/llama").get("servers") or []
    except ApiError:
        return "?"
    return " · ".join(f"{s['id']}: {Path(str(s['status'].get('model'))).stem}" for s in servers
                      if s["status"].get("state") not in ("off", "failed") and s["status"].get("model")) or "ninguno"


# --- una ejecución
class Ejecucion:
    """Una prueba × modalidad × contendiente. Su carpeta en data/banco guarda todo; `seguir` la retoma."""

    def __init__(self, carpeta: Path):
        self.carpeta = carpeta
        self.datos = json.loads((carpeta / "resultado.json").read_text(encoding="utf-8"))
        self.prueba = cargar_prueba(self.datos["prueba"], Path(self.datos.get("banco") or BANCO))
        self.repo = Path(self.datos["repo"])

    @classmethod
    def nueva(cls, api: Callable, prueba: Prueba, modalidad: str, cont: dict, *, datos: Path = DATOS,
              proyectos: Path = PROYECTOS, ahora: datetime | None = None) -> "Ejecucion":
        if modalidad not in prueba.modalidades:
            raise ValueError(f"«{prueba.nombre}» no tiene la modalidad «{modalidad}» "
                             f"(tiene: {', '.join(prueba.modalidades)})")
        ahora = ahora or datetime.now()
        sello = f"{ahora:%Y%m%d-%H%M}"
        nombre = f"{prueba.nombre}-{modalidad}-{cont['nombre']}-{sello}"
        carpeta = datos / f"{prueba.nombre}-{modalidad}" / f"{cont['nombre']}-{sello}"
        repo = proyectos / nombre
        crear_repo(prueba, modalidad, repo)
        cuerpo = {"name": f"banco-{nombre}", "repo_path": str(repo)}
        api("POST", "/api/projects", cuerpo)
        carpeta.mkdir(parents=True)
        items = prueba.lista(modalidad)
        (carpeta / "resultado.json").write_text(json.dumps({
            "prueba": prueba.nombre, "modalidad": modalidad, "titulo": prueba.titulo, "tipo": prueba.tipo,
            "banco": str(prueba.dir.parent.parent), "contendiente": cont, "agente": cont["agente"],
            "repo": str(repo), "proyecto": cuerpo["name"], "inicio": ahora.isoformat(timespec="seconds"),
            "fin": None, "estado": "preparada", "modelos_cargados": None, "parches_total": len(items),
            "base": git(repo, "rev-parse", "HEAD").strip(), "parches": [], "examen_final": None, "totales": {},
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return cls(carpeta)

    def guardar(self) -> None:
        tmp = self.carpeta / "resultado.json.tmp"
        tmp.write_text(json.dumps(self.datos, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.carpeta / "resultado.json")

    def apuntar(self, r: Result) -> None:
        """Gancho del autopiloto tras cada parche: examen oculto, commit, archivos y CHANGELOG."""
        previo = self.datos["parches"][-1]["commit"] if self.datos["parches"] else self.datos["base"]
        try:
            hecho = cambios(self.repo, previo)
        except RuntimeError as e:
            hecho = {"commit": previo, "archivos": [], "changelog": [], "error": str(e)}
        ex = examinar(self.prueba, self.repo)
        r.extra = {**hecho, "examen": {k: ex.get(k) for k in ("pasan", "total", "nota")}}
        tokens = sum(m.get("tokens", 0) for m in r.models.values())
        self.datos["parches"] = [p for p in self.datos["parches"] if p["n"] != r.n] + [{
            "n": r.n, "titulo": r.text.split(". ")[0][:90], "texto": r.text, "resultado": r.outcome,
            "segundos": r.seconds, "coste": r.cost, "reintento": r.retried, "cerrado_al_limite": r.rescued,
            "tareas": r.task_ids, "modelos": r.models, "tokens": tokens, "final": r.final[:800], **r.extra}]
        self.datos["parches"].sort(key=lambda p: p["n"])
        self.totales()
        self.guardar()

    def totales(self) -> None:
        ps = self.datos["parches"]
        modelos: dict = {}
        for p in ps:
            for srv, m in (p.get("modelos") or {}).items():
                a = modelos.setdefault(srv, {"modelo": None, "encargos": 0, "fallidos": 0, "tokens": 0, "segundos": 0.0})
                for k in ("encargos", "fallidos", "tokens", "segundos"):
                    a[k] += m.get(k) or 0
                a["modelo"] = m.get("modelo") or a["modelo"]
        ultima = next((p["examen"] for p in reversed(ps) if (p.get("examen") or {}).get("total")), None)
        self.datos["totales"] = {
            "hechos": len(ps), "integrados": sum(p["resultado"] == "integrado" for p in ps),
            "segundos": sum(p["segundos"] for p in ps), "coste": round(sum(p["coste"] for p in ps), 4),
            "tokens": sum(p.get("tokens", 0) for p in ps), "reintentos": sum(bool(p["reintento"]) for p in ps),
            "nota": (self.datos.get("examen_final") or ultima or {}).get("nota"), "modelos": modelos}

    def correr(self, api: Callable, *, say: Callable[[str], None] = print, piloto: type = autopilot.Autopilot,
               **kw) -> dict:
        cont = self.datos["contendiente"]
        modalidad = self.datos["modalidad"]
        self.datos["estado"] = "en marcha"
        self.datos["modelos_cargados"] = cargar_modelos(api, cont.get("modelos"), say)
        self.guardar()
        say(f"Modelos: {self.datos['modelos_cargados']}")
        items = self.prueba.lista(modalidad)
        p = piloto(api, self.datos["proyecto"], cont["agente"], items, hours=cont["horas"],
                   budget=cont["presupuesto"], task_minutes=cont["minutos_tarea"], check=self.prueba.check,
                   state=self.carpeta / "estado.json", report=self.carpeta / "informe.md", say=say, after=self.apuntar,
                   **kw)
        try:
            p.run()
        finally:
            self.cerrar(len(self.datos["parches"]) >= len(items))
        return self.datos

    def cerrar(self, completa: bool) -> None:
        ex = examinar(self.prueba, self.repo, por_archivo=300)
        self.datos["examen_final"] = ex
        self.datos["fin"] = datetime.now().isoformat(timespec="seconds")
        self.datos["estado"] = "terminada" if completa else "parada"
        for nombre in ("CHANGELOG.md",):
            if (self.repo / nombre).is_file():
                shutil.copy(self.repo / nombre, self.carpeta / nombre)
        try:
            (self.carpeta / "git-log.txt").write_text(git(self.repo, "log", "--stat", "--date=iso"), encoding="utf-8")
        except RuntimeError:
            pass
        self.totales()
        self.guardar()


def ejecuciones(datos: Path = DATOS) -> list[dict]:
    """Todas las ejecuciones (sin el detalle de cada parche, salvo lo que hace falta para la curva)."""
    out = []
    for f in sorted(datos.glob("*/*/resultado.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": f"{f.parent.parent.name}/{f.parent.name}", **{k: d.get(k) for k in (
            "prueba", "modalidad", "titulo", "tipo", "agente", "inicio", "fin", "estado", "modelos_cargados",
            "parches_total", "totales")},
            "contendiente": d.get("contendiente", {}).get("nombre"),
            "descripcion": d.get("contendiente", {}).get("descripcion", ""),
            "curva": [[p["n"], (p.get("examen") or {}).get("nota"), p["resultado"]] for p in d.get("parches", [])]})
    return out


def ejecucion(id_: str, datos: Path = DATOS) -> dict:
    carpeta = (datos / id_).resolve()
    if not carpeta.is_relative_to(datos.resolve()) or not (carpeta / "resultado.json").is_file():
        raise FileNotFoundError(id_)
    d = json.loads((carpeta / "resultado.json").read_text(encoding="utf-8"))
    for nombre, clave in (("CHANGELOG.md", "changelog_md"), ("informe.md", "informe_md")):
        f = carpeta / nombre
        if not f.is_file() and nombre == "CHANGELOG.md":
            f = Path(d["repo"]) / nombre  # en marcha: el del repo
        d[clave] = f.read_text(encoding="utf-8") if f.is_file() else ""
    return {"id": id_, **d}


# --- para la página /banco: abrir el proyecto de una ejecución (o la referencia) en el navegador
TIPOS = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".csv": "text/csv",
         ".txt": "text/plain", ".md": "text/plain"}  # en Windows el registro puede dar .js como text/plain


def raiz_de(id_: str, datos: Path = DATOS, banco: Path = BANCO) -> Path:
    """Carpeta que se sirve: el repo de una ejecución («grupo/ejecución») o la referencia de una prueba («ref:nombre»)."""
    if id_.startswith("ref:"):
        d = cargar_prueba(id_[4:], banco).dir / "referencia"
        if not d.is_dir():
            raise FileNotFoundError(id_)
        return d
    carpeta = (datos / id_).resolve()
    if not carpeta.is_relative_to(datos.resolve()) or not (carpeta / "resultado.json").is_file():
        raise FileNotFoundError(id_)
    return Path(json.loads((carpeta / "resultado.json").read_text(encoding="utf-8"))["repo"])


def archivo(base: Path, ruta: str) -> tuple[Path, str]:
    f = (base / (ruta or "index.html")).resolve()
    if not f.is_relative_to(base.resolve()) or not f.is_file() or ".git" in f.relative_to(base.resolve()).parts:
        raise FileNotFoundError(ruta)
    return f, TIPOS.get(f.suffix.lower(), "application/octet-stream")
