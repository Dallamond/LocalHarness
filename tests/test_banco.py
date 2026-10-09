import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from localharness import banco

NODE = shutil.which("node")


def prueba_mini(raiz: Path) -> Path:
    """Un banco con una prueba de dos parches: el examen pide src/a.js con x = 1 y src/b.js con y = 2."""
    d = raiz / "banco" / "pruebas" / "mini"
    (d / "semilla").mkdir(parents=True)
    (d / "semilla" / "CHANGELOG.md").write_text("# Changelog\n\n- Parche 000 · semilla\n", encoding="utf-8")
    (d / "semilla-libre").mkdir()
    (d / "semilla-libre" / "CONTRATO.md").write_text("contrato\n", encoding="utf-8")
    (d / "examen").mkdir()
    for nombre, var, val in (("a", "x", 1), ("b", "y", 2)):
        (d / "examen" / f"{nombre}.test.mjs").write_text(
            'import { test } from "node:test"; import assert from "node:assert/strict";\n'
            'import { join } from "node:path"; import { pathToFileURL } from "node:url";\n'
            f'test("{nombre}", async () => {{ const m = await import(pathToFileURL(join(process.env.PROYECTO, '
            f'"src", "{nombre}.js")).href); assert.equal(m.{var}, {val}); }});\n', encoding="utf-8")
    (d / "guiada.md").write_text("- Haz a. Detalle\n- Haz b. Detalle\n", encoding="utf-8")
    (d / "libre.md").write_text("- Todo\n", encoding="utf-8")
    (d / "prueba.json").write_text(json.dumps({"titulo": "Mini", "tipo": "web", "check": "", "modalidades": {
        "guiada": {"parches": "guiada.md"}, "libre": {"parches": "libre.md", "semilla_extra": "semilla-libre"}}}),
        encoding="utf-8")
    (raiz / "banco" / "contendientes").mkdir()
    (raiz / "banco" / "contendientes" / "pareja.json").write_text(json.dumps(
        {"descripcion": "dos", "modelos": {"principal": "Grande-Q4", "rapido": None}}), encoding="utf-8")
    shutil.copy(banco.BANCO / "puntuar.mjs", raiz / "banco" / "puntuar.mjs")
    return raiz / "banco"


class FakeApi:
    """LocalHarness de mentira: cada tarea acaba en revisión y al integrarla escribe un archivo en el repo."""

    def __init__(self, archivos: list[tuple[str, str]]):
        self.archivos = list(archivos)
        self.repo: Path | None = None
        self.tasks: dict[int, dict] = {}
        self.calls: list[tuple] = []
        self.servers = [{"id": "principal", "name": "Fuerte", "status": {"state": "off"}},
                        {"id": "rapido", "name": "Rápido", "status": {"state": "ready", "model": "D:/m/Peque.gguf"}}]

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/projects":
            if method == "POST":
                self.repo = Path(body["repo_path"])
                self.project = {"id": 1, "name": body["name"], "repo_path": body["repo_path"]}
                return self.project
            return [self.project]
        if path == "/api/agents":
            return [{"id": 14, "name": "Jefe local"}]
        if path == "/api/settings":
            return {"values": {"llama": {"autostart_on_task": True, "servers": []}}}
        if path == "/api/llama":
            return {"config": {}, "servers": self.servers, "models": [
                {"name": "Grande-Q4", "file": "Grande-Q4.gguf", "path": "D:/m/Grande-Q4.gguf"}]}
        if path == "/api/llama/start":
            srv = next(s for s in self.servers if s["id"] == body["server"])
            srv["status"] = {"state": "ready", "model": body["path"]}
            return {}
        if path.startswith("/api/llama/stop"):
            self.servers[1]["status"] = {"state": "off"}
            return {}
        if method == "GET" and path == "/api/tasks":
            return list(self.tasks.values())
        if method == "POST" and path == "/api/tasks":
            tid = len(self.tasks) + 1
            self.tasks[tid] = {"id": tid, "status": "review", "cost_usd": 0, "worktree": "/wt", "final": "hecho",
                               "title": body["title"], "project_id": 1}
            return self.tasks[tid]
        tid = int(path.split("/")[3])
        if path.endswith("/events"):
            return [{"kind": "delegate", "data": {"tool": "local_write_file", "server": "principal", "ok": True,
                                                  "completion_tokens": 300, "tps": 30, "model": "Grande"}}]
        if path.endswith("/merge"):
            ruta, texto = self.archivos.pop(0)
            (self.repo / ruta).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / ruta).write_text(texto, encoding="utf-8")
            with open(self.repo / "CHANGELOG.md", "a", encoding="utf-8") as f:
                f.write(f"- Parche {tid:03d} · {ruta}\n")
            banco.git(self.repo, "add", "-A")
            banco.git(self.repo, "commit", "-q", "-m", f"tarea {tid}")
            self.tasks[tid]["status"] = "merged"
        return self.tasks[tid]


class BancoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.banco = prueba_mini(self.tmp)

    def test_lee_pruebas_y_contendientes(self):
        [p] = banco.pruebas(self.banco)
        self.assertEqual(p.ficha()["modalidades"]["guiada"]["parches"], 2)
        c = banco.cargar_contendiente("pareja", self.banco)
        self.assertEqual((c["nombre"], c["agente"], c["horas"]), ("pareja", "Jefe local", 12))
        with self.assertRaisesRegex(ValueError, "hay: pareja"):
            banco.cargar_contendiente("otro", self.banco)

    def test_crear_repo_con_la_semilla_de_la_modalidad(self):
        p = banco.cargar_prueba("mini", self.banco)
        repo = self.tmp / "repo"
        banco.crear_repo(p, "libre", repo)
        self.assertTrue((repo / "CONTRATO.md").is_file())
        self.assertEqual(len(banco.git(repo, "log", "--oneline").splitlines()), 1)
        with self.assertRaises(ValueError):
            banco.crear_repo(p, "libre", repo)

    def test_cargar_modelos(self):
        api = FakeApi([])
        hecho = banco.cargar_modelos(api, {"principal": "Grande-Q4", "rapido": None}, say=lambda _: None)
        self.assertEqual(hecho, "principal: Grande-Q4")
        self.assertIn(("POST", "/api/llama/start", {"path": "D:/m/Grande-Q4.gguf", "server": "principal",
                                                     "options": None}), api.calls)
        n = len(api.calls)
        banco.cargar_modelos(api, {"principal": "Grande-Q4"}, say=lambda _: None)  # ya está: no lo recarga
        self.assertFalse(any(c[1] == "/api/llama/start" for c in api.calls[n:]))
        with self.assertRaisesRegex(ValueError, "No encuentro"):
            banco.cargar_modelos(api, {"principal": "Nada"})

    def test_ajustar_llama(self):
        llama = {"autostart_on_task": True, "servers": [{"id": "principal", "thinking": "normal"},
                                                        {"id": "rapido", "thinking": "apagado"}]}
        calls = []

        def api(method, path, body=None):
            calls.append((method, path, body))
            return {"values": {"llama": llama}}
        self.assertIsNone(banco.ajustar_llama(api, {"modelos": {"principal": "X"}}, say=lambda _: None))
        self.assertEqual(calls, [])
        previo = banco.ajustar_llama(api, {"modelos": {"principal": "X", "rapido": None},
                                           "pensamiento": {"principal": "apagado"}}, say=lambda _: None)
        cambio = calls[-1][2]["llama"]
        self.assertEqual([s["thinking"] for s in cambio["servers"]], ["apagado", "apagado"])
        self.assertIs(cambio["autostart_on_task"], False)
        self.assertEqual(previo, {"servers": llama["servers"], "autostart_on_task": True})

    @unittest.skipUnless(NODE, "hace falta node para el examen")
    def test_ejecucion_completa_con_curva_de_nota(self):
        api = FakeApi([("src/a.js", "export const x = 1;\n"), ("src/b.js", "export const y = 3;\n")])
        p = banco.cargar_prueba("mini", self.banco)
        ej = banco.Ejecucion.nueva(api, p, "guiada", banco.cargar_contendiente("pareja", self.banco),
                                   datos=self.tmp / "datos", proyectos=self.tmp / "proyectos",
                                   ahora=datetime(2026, 10, 9, 20, 0))
        self.assertEqual(ej.carpeta, self.tmp / "datos" / "mini-guiada" / "pareja-20261009-2000")
        d = ej.correr(api, say=lambda _: None, sleep=lambda _: None)
        self.assertEqual(d["estado"], "terminada")
        self.assertEqual(d["modelos_cargados"], "principal: Grande-Q4")
        self.assertEqual([x["examen"]["nota"] for x in d["parches"]], [50, 50])  # b.js tiene y = 3: no pasa
        self.assertEqual(d["parches"][0]["archivos"], [{"estado": "M", "ruta": "CHANGELOG.md"},
                                                       {"estado": "A", "ruta": "src/a.js"}])
        self.assertEqual(d["parches"][1]["changelog"], ["- Parche 002 · src/b.js"])
        self.assertEqual(d["parches"][0]["tokens"], 300)
        self.assertEqual(d["examen_final"]["nota"], 50)
        self.assertEqual((d["totales"]["integrados"], d["totales"]["nota"]), (2, 50))
        self.assertTrue((ej.carpeta / "git-log.txt").is_file() and (ej.carpeta / "CHANGELOG.md").is_file())
        [e] = banco.ejecuciones(self.tmp / "datos")
        self.assertEqual((e["id"], e["contendiente"], e["curva"]),
                         ("mini-guiada/pareja-20261009-2000", "pareja", [[1, 50, "integrado"], [2, 50, "integrado"]]))
        full = banco.ejecucion(e["id"], self.tmp / "datos")
        self.assertIn("src/b.js", full["changelog_md"])
        with self.assertRaises(FileNotFoundError):
            banco.ejecucion("../../etc", self.tmp / "datos")

    @unittest.skipUnless(NODE, "hace falta node para el examen")
    def test_examen_de_las_pruebas_reales(self):
        """La referencia de Cuentas claras saca 100 y la semilla 0: el examen no regala ni pide imposibles."""
        p = banco.cargar_prueba("cuentas-claras")
        ref = self.tmp / "ref"
        shutil.copytree(p.dir / "referencia", ref)
        shutil.copytree(p.dir / "semilla" / "docs", ref / "docs")
        self.assertEqual(banco.examinar(p, ref)["nota"], 100)
        self.assertEqual(banco.examinar(p, p.dir / "semilla")["nota"], 0)

    def test_api_y_pagina(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("faltan fastapi/httpx")
        from unittest import mock

        from localharness.api import create_app
        datos = self.tmp / "datos"
        carpeta = datos / "mini-guiada" / "pareja-20261009-2000"
        repo = self.tmp / "repo"
        (repo / "src").mkdir(parents=True)
        (repo / "index.html").write_text("<h1>hola</h1>", encoding="utf-8")
        (repo / "src" / "main.js").write_text("export {};", encoding="utf-8")
        carpeta.mkdir(parents=True)
        (carpeta / "resultado.json").write_text(json.dumps({"prueba": "mini", "repo": str(repo), "parches": [
            {"n": 1, "resultado": "integrado", "examen": {"nota": 40}}], "contendiente": {"nombre": "pareja"},
            "totales": {"nota": 40}}), encoding="utf-8")
        app = create_app(self.tmp / "lh.db", worktree_root=str(self.tmp / "wt"), web_dist=None)
        with mock.patch.object(banco, "DATOS", datos), TestClient(app) as c:
            r = c.get("/api/banco").json()
            self.assertEqual([e["curva"] for e in r["ejecuciones"]], [[[1, 40, "integrado"]]])
            self.assertIn("cuentas-claras", [p["nombre"] for p in r["pruebas"]])
            self.assertEqual(c.get("/api/banco/ejecucion/mini-guiada/pareja-20261009-2000").json()["totales"]["nota"], 40)
            self.assertEqual(c.get("/api/banco/ejecucion/mini-guiada/nada").status_code, 404)
            self.assertIn("hola", c.get("/banco/abrir/mini-guiada/pareja-20261009-2000/").text)
            js = c.get("/banco/abrir/mini-guiada/pareja-20261009-2000/src/main.js")
            self.assertTrue(js.headers["content-type"].startswith("text/javascript"))
            self.assertEqual(c.get("/banco/abrir/mini-guiada/pareja-20261009-2000/../resultado.json").status_code, 404)
            self.assertEqual(c.get("/banco/abrir/ref/cuentas-claras/src/dinero.js").status_code, 200)
            self.assertIn("<title>", c.get("/banco").text)

    def test_listas_de_las_pruebas_reales(self):
        for p in banco.pruebas():
            for m in p.modalidades:
                self.assertTrue(p.lista(m), f"{p.nombre}/{m} sin parches")
            self.assertTrue((p.dir / "examen").is_dir() and (p.dir / "semilla" / "ENCARGO.md").is_file())


if __name__ == "__main__":
    unittest.main()
