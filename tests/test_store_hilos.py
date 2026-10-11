import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from localharness.store import Store


class StoreHilosTest(unittest.TestCase):
    def test_varios_hilos_a_la_vez(self):
        """La conexión se comparte entre hilos (API, to_thread, endpoints síncronos): con el cerrojo, nada se rompe.
        El 11/10 un alta de proyecto a la vez que otros accesos contestó 500 y paró la cola del banco."""
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        s = Store(d / "x.db")
        self.addCleanup(s.close)
        errores: list[str] = []

        def trabajo(k: int) -> None:
            try:
                for i in range(60):
                    p = s.add_project(f"p{k}-{i}", str(d / f"r{k}-{i}"))
                    assert p and p["name"] == f"p{k}-{i}"
                    s.list_projects()
                    s.find_project(f"p{k}-{i}")
            except Exception as e:  # noqa: BLE001
                errores.append(repr(e))

        hilos = [threading.Thread(target=trabajo, args=(k,)) for k in range(6)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(errores, [])
        self.assertEqual(len(s.list_projects()), 360)

    def test_resultado_de_execute(self):
        s = Store()
        self.addCleanup(s.close)
        r = s.db.execute("SELECT 1 AS a UNION SELECT 2 ORDER BY a")
        self.assertEqual(r.fetchone()["a"], 1)
        self.assertEqual([x["a"] for x in r.fetchall()], [2])
        self.assertIsNone(r.fetchone())
        self.assertEqual([x[0] for x in s.db.execute("SELECT 3 UNION SELECT 4 ORDER BY 1")], [3, 4])
