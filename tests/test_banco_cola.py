import json
import shutil
import tempfile
import unittest
from pathlib import Path

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
