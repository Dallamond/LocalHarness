"""Los casos cortos del banco (banco/casos): cada examen da 100 a la referencia y menos de 100 a la semilla, y la
referencia deja `npm test` pasando (si no, el jefe nunca la integraría)."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from localharness import banco

NODE = shutil.which("node")


def montar(caso: banco.Prueba, destino: Path, referencia: bool) -> None:
    shutil.copytree((caso.dir / caso.base).resolve(), destino)
    shutil.copytree(caso.dir / "semilla", destino, dirs_exist_ok=True)
    if referencia:
        shutil.copytree(caso.dir / "referencia", destino, dirs_exist_ok=True)


@unittest.skipUnless(NODE, "hace falta node")
class CasosTest(unittest.TestCase):
    def test_repertorio_basico(self):
        r = banco.cargar_repertorio("basico")
        self.assertEqual(len(r["casos"]), len(banco.casos()))
        self.assertGreaterEqual(len(r["casos"]), 20)
        grupos = {banco.cargar_prueba(c).grupo for c in r["casos"]}
        self.assertEqual(grupos, {"escribir", "tests", "diagnosticar", "arreglar", "ampliar", "varios", "tangible"})

    def test_cada_caso_tiene_examen_justo(self):
        for caso in banco.casos():
            with self.subTest(caso.nombre), tempfile.TemporaryDirectory() as t:
                self.assertEqual(len(caso.lista("caso")), 1, "un caso es un parche")
                semilla, ref = Path(t) / "s", Path(t) / "r"
                montar(caso, semilla, False)
                montar(caso, ref, True)
                nr = banco.examinar(caso, ref)
                self.assertEqual(nr["nota"], 100, json.dumps(nr["filas"], ensure_ascii=False)[:800])
                self.assertLess(banco.examinar(caso, semilla)["nota"], 100)
                p = subprocess.run(["node", "--test"], cwd=ref, capture_output=True, encoding="utf-8",
                                   errors="replace", env={k: v for k, v in os.environ.items() if k != "NODE_TEST_CONTEXT"})
                self.assertEqual(p.returncode, 0, p.stdout[-800:])

    def test_crear_repo_pone_la_base_debajo(self):
        caso = banco.cargar_prueba("d-off-by-one")
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t) / "repo"
            banco.crear_repo(caso, "caso", repo)
            for f in ("ENCARGO.md", "CHANGELOG.md", "package.json", "tests/proyecto.test.mjs", "src/rango.js"):
                self.assertTrue((repo / f).is_file(), f)
