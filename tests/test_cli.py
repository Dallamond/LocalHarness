import contextlib, io, tempfile, unittest
from pathlib import Path

from localharness.cli import main
from tests.test_core import FAKES, make_repo

FAKE = str(FAKES / "claude")  # NUNCA la CLI real en pruebas: gastaría tu plan


class CliTests(unittest.TestCase):
    def test_run_review_merge_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            db = str(Path(tmp) / "lh.db")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["--db", db, "project", "add", "demo", str(repo)]), 0)
                self.assertEqual(main(["--db", db, "agent", "add", "w", "--provider", "claude", "--max-turns", "5", "--binary", FAKE]), 0)
                self.assertEqual(main(["--db", db, "run", "demo", "crea hola.txt & más", "--agent", "w"]), 0)
                self.assertFalse((repo / "hola.txt").exists())  # sigue aislado
                self.assertEqual(main(["--db", db, "show", "1", "--diff"]), 0)
                self.assertEqual(main(["--db", db, "merge", "1", "--yes"]), 0)
                self.assertEqual(main(["--db", db, "tasks"]), 0)
            self.assertTrue((repo / "hola.txt").exists())
            self.assertIn("merged", out.getvalue())
            self.assertIn("+hola", out.getvalue())
            self.assertIn("sesión sess-1", out.getvalue())  # prueba de que respondió la CLI falsa

    def test_merge_refuses_dirty_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            db = str(Path(tmp) / "lh.db")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                main(["--db", db, "project", "add", "demo", str(repo)])
                main(["--db", db, "agent", "add", "w", "--binary", FAKE])
                main(["--db", db, "run", "demo", "x", "--agent", "w"])
                (repo / "README.md").write_text("cambio local sin confirmar\n")
                self.assertEqual(main(["--db", db, "merge", "1", "--yes"]), 1)
            self.assertFalse((repo / "hola.txt").exists())


if __name__ == "__main__":
    unittest.main()
