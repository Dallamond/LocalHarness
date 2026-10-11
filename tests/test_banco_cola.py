import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from localharness import banco, banco_cola
from tests.test_banco import NODE, FakeApi, prueba_mini


class ColaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.banco = prueba_mini(self.tmp)
        self.cola = self.tmp / "datos" / "cola.json"

    def anadir(self, nombre="pareja", reps=1, **extra):
        return banco_cola.anadir("mini", "guiada", reps, {"nombre": nombre, "agente": "Jefe local",
                                                          "modelos": {"principal": "Grande-Q4"}, **extra},
                                 path=self.cola, base=self.banco)

    def test_montar_la_cola(self):
        a = self.anadir("a", 2, linea="1", horas="")
        b = self.anadir("b")
        self.assertEqual(a["contendiente"]["linea"], 1)
        self.assertEqual(a["contendiente"]["horas"], 12)  # vacío = por defecto
        banco_cola.mover(b["id"], -1, path=self.cola)
        self.assertEqual([t["id"] for t in banco_cola.leer(self.cola)["tandas"]], [b["id"], a["id"]])
        banco_cola.quitar(b["id"], path=self.cola)
        self.assertEqual(len(banco_cola.leer(self.cola)["tandas"]), 1)
        for mal in ({"nombre": "Con Espacios"}, {"nombre": "x", "linea": 9}):
            with self.assertRaises(ValueError):
                banco_cola.anadir("mini", "guiada", 1, mal, path=self.cola, base=self.banco)
        with self.assertRaisesRegex(ValueError, "modalidad"):
            banco_cola.anadir("mini", "nada", 1, {"nombre": "x"}, path=self.cola, base=self.banco)

    def test_guardar_contendiente(self):
        f = banco_cola.guardar_contendiente({"nombre": "nuevo", "agente": "Jefe local 2", "linea": 1},
                                            base=self.banco)
        self.assertEqual(json.loads(f.read_text(encoding="utf-8"))["agente"], "Jefe local 2")
        self.assertEqual(banco.cargar_contendiente("nuevo", self.banco)["linea"], 1)
        with self.assertRaises(FileExistsError):
            banco_cola.guardar_contendiente({"nombre": "nuevo"}, base=self.banco)

    @unittest.skipUnless(NODE, "hace falta node para el examen")
    def test_correr_tandas_con_repeticiones_y_resumen(self):
        api = FakeApi([("src/a.js", "export const x = 1;\n"), ("src/b.js", "export const y = 2;\n")] * 2
                      + [("src/a.js", "export const x = 1;\n"), ("src/b.js", "export const y = 3;\n")])
        a = self.anadir("buena", 2)
        b = self.anadir("floja", 1)
        datos = self.tmp / "datos"
        banco_cola.correr(api, say=lambda _: None, path=self.cola, datos=datos, proyectos=self.tmp / "proyectos",
                          base=self.banco, sleep=lambda _: None)
        cola = banco_cola.estado(self.cola, datos, self.tmp / "no.log")
        ta, tb = cola["tandas"]
        self.assertEqual((ta["estado"], len(ta["hechas"]), tb["estado"]), ("hecha", 2, "hecha"))
        self.assertEqual([r["nota"] for r in ta["resultados"]], [100, 100])
        self.assertEqual((ta["media"], tb["media"]), (100, 50))
        self.assertIsNone(cola["proceso"])
        d = json.loads((datos / ta["hechas"][1] / "resultado.json").read_text(encoding="utf-8"))
        self.assertEqual((d["tanda"], d["repeticion"]), (a["id"], 2))
        res = {g["contendiente"]: g for g in banco_cola.resumen(datos)}
        self.assertEqual((res["buena"]["tiradas"], res["buena"]["media"]), (2, 100))
        self.assertEqual((res["floja"]["mejor"], res["floja"]["peor"]), (50, 50))
        self.assertTrue(b["id"])

    def test_api_de_la_cola(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("faltan fastapi/httpx")
        from unittest import mock

        from localharness.api import create_app
        app = create_app(self.tmp / "lh.db", worktree_root=str(self.tmp / "wt"), web_dist=None)
        with mock.patch.object(banco_cola, "COLA", self.cola), mock.patch.object(banco, "DATOS", self.tmp / "datos"), \
                mock.patch.object(banco, "BANCO", self.banco), TestClient(app) as c:
            cuerpo = {"prueba": "mini", "modalidad": "guiada", "repeticiones": 2,
                      "contendiente": {"nombre": "pareja", "agente": "Jefe local"}}
            t = c.post("/api/banco/cola", json=cuerpo)
            self.assertEqual(t.status_code, 201, t.text)
            r = c.get("/api/banco/cola").json()
            self.assertEqual([x["repeticiones"] for x in r["tandas"]], [2])
            self.assertFalse(r["corriendo"])
            self.assertEqual(c.post("/api/banco/cola", json={**cuerpo, "repeticiones": 0}).status_code, 422)
            self.assertEqual(c.post("/api/banco/cola/parar", json={"modo": "despues"}).status_code, 200)
            self.assertEqual(c.delete(f"/api/banco/cola/{t.json()['id']}").status_code, 200)
            self.assertEqual(c.delete("/api/banco/cola/nada").status_code, 404)

    @unittest.skipUnless(NODE, "hace falta node para el examen")
    def test_repertorio_vuelta_a_sus_casos_y_matriz(self):
        # dos casos de un parche cada uno: «ca» (pide src/a.js con x = 1) y «cb» (src/b.js con y = 2)
        comun = self.banco / "casos" / "_comun" / "semilla"
        comun.mkdir(parents=True)
        (comun / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
        mini = self.banco / "pruebas" / "mini"
        for nombre, examen in (("ca", "a"), ("cb", "b")):
            d = self.banco / "casos" / nombre
            (d / "semilla").mkdir(parents=True)
            (d / "examen").mkdir()
            shutil.copy(mini / "examen" / f"{examen}.test.mjs", d / "examen")
            (d / "encargo.md").write_text(f"- Haz {examen}\n", encoding="utf-8")
            (d / "caso.json").write_text(json.dumps({"titulo": nombre, "grupo": "escribir", "base": "../_comun/semilla",
                                                     "check": "", "modalidades": {"caso": {"parches": "encargo.md"}}}),
                                         encoding="utf-8")
        (self.banco / "repertorios").mkdir()
        (self.banco / "repertorios" / "r.json").write_text(json.dumps({"titulo": "R", "casos": ["ca", "cb"]}),
                                                          encoding="utf-8")
        t = banco_cola.anadir("", "", 2, {"nombre": "pareja", "agente": "Jefe local", "minutos_tarea": 45},
                              path=self.cola, base=self.banco, repertorio="r")
        self.assertEqual((t["prueba"], t["casos"], t["minutos_caso"]), ("r", ["ca", "cb"], 15))
        self.assertEqual(banco_cola.plan(t), [("ca", "caso"), ("cb", "caso")] * 2)
        self.assertEqual(banco_cola.contendiente_de(t)["minutos_tarea"], 15)
        bien_a, mal_b = ("src/a.js", "export const x = 1;\n"), ("src/b.js", "export const y = 3;\n")
        api = FakeApi([bien_a, mal_b, bien_a, ("src/b.js", "export const y = 2;\n")])
        datos = self.tmp / "datos"
        with mock.patch.object(banco, "BANCO", self.banco):
            banco_cola.correr(api, say=lambda _: None, path=self.cola, datos=datos, proyectos=self.tmp / "proyectos",
                              base=self.banco, sleep=lambda _: None)
            cola = banco_cola.estado(self.cola, datos, self.tmp / "no.log")
            self.assertEqual((cola["tandas"][0]["estado"], len(cola["tandas"][0]["hechas"]), cola["tandas"][0]["total"]),
                             ("hecha", 4, 4))
            [m] = banco_cola.matrices(datos, self.banco)
        filas = {f["caso"]: f["celdas"]["pareja"] for f in m["filas"]}
        self.assertEqual(filas["ca"], {"tiradas": 2, "aprobados": 2, "media": 100})
        self.assertEqual(filas["cb"], {"tiradas": 2, "aprobados": 1, "media": 50})
        self.assertEqual(m["totales"]["pareja"]["aprobados"], 3)
        self.assertEqual(banco_cola.resumen(datos), [])  # los casos no salen en el resumen de pruebas largas

    @unittest.skipUnless(NODE, "hace falta node para el examen")
    def test_fallo_pasajero_de_la_api_se_reintenta(self):
        from localharness.autopilot import ApiError
        api = FakeApi([("src/a.js", "export const x = 1;\n"), ("src/b.js", "export const y = 2;\n")])
        primera = [True]

        def falla_una_vez(method, path, body=None):
            if method == "POST" and path == "/api/projects" and primera[0]:
                primera[0] = False
                raise ApiError("POST /api/projects: HTTP 500 Internal Server Error")
            if method == "GET" and path == "/api/projects" and not hasattr(api, "project"):
                return []  # aún no hay ningún proyecto (el FakeApi solo guarda el último)
            return api(method, path, body)
        self.anadir("x")
        esperas = []
        banco_cola.correr(falla_una_vez, say=lambda _: None, path=self.cola, datos=self.tmp / "datos",
                          proyectos=self.tmp / "proyectos", base=self.banco, espera=esperas.append, sleep=lambda _: None)
        t = banco_cola.leer(self.cola)["tandas"][0]
        self.assertEqual((t["estado"], len(t["hechas"]), t.get("fallos")), ("hecha", 1, 0), t)
        self.assertEqual(esperas, [30])

    def test_reemplazar_y_leer_reintentan_si_windows_deniega_el_acceso(self):
        # 11/10: «[WinError 5] Acceso denegado» al reemplazar resultado.json mientras el servidor lo leía
        destino, tmp = self.tmp / "r.json", self.tmp / "r.json.tmp"
        destino.write_text("{}", encoding="utf-8")
        tmp.write_text('{"a": 1}', encoding="utf-8")
        original, veces = Path.replace, [0]

        def a_veces(self_, otro):
            veces[0] += 1
            if veces[0] <= 2:
                raise PermissionError(5, "Acceso denegado")
            return original(self_, otro)
        with mock.patch.object(Path, "replace", a_veces), mock.patch("time.sleep"):
            banco.reemplazar(tmp, destino)
        self.assertEqual((veces[0], banco.leer_json(destino)), (3, {"a": 1}))
        self.assertEqual(banco_cola.leer(self.tmp / "no-existe.json")["tandas"], [])
        (self.tmp / "roto.json").write_text("{roto", encoding="utf-8")
        with self.assertRaises(ValueError):  # una cola ilegible es un error, nunca una cola vacía
            banco_cola.leer(self.tmp / "roto.json")

    def test_parar_antes_no_corre_nada(self):
        self.anadir("x")
        banco_cola.editar(lambda c: c.update(parar="despues"), self.cola)
        banco_cola.correr(FakeApi([]), say=lambda _: None, path=self.cola, datos=self.tmp / "datos",
                          proyectos=self.tmp / "proyectos", base=self.banco)
        cola = banco_cola.leer(self.cola)
        self.assertEqual(cola["tandas"][0]["estado"], "pendiente")
        self.assertIsNone(cola["parar"])  # al salir se limpia: la próxima vez empieza

    def test_tanda_que_falla_no_para_la_cola(self):
        self.anadir("mal", modelos={"principal": "NoExiste"})
        banco_cola.correr(FakeApi([]), say=lambda _: None, path=self.cola, datos=self.tmp / "datos",
                          proyectos=self.tmp / "proyectos", base=self.banco)
        t = banco_cola.leer(self.cola)["tandas"][0]
        self.assertEqual(t["estado"], "error")
        self.assertIn("NoExiste", t["error"])
        banco_cola.reabrir(t["id"], path=self.cola)
        self.assertEqual(banco_cola.leer(self.cola)["tandas"][0]["estado"], "pendiente")
