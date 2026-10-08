"""Jefe local (modo 100 % local): elige archivos, planifica, ejecuta, arregla si fallan los tests, revisa e informa,
todo con modelos locales (aquí, de mentira) y sin Claude."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from localharness.boss import SYSTEM_PROPOSE, SYSTEM_REVIEW, SYSTEM_SELECT, Boss, detect_check, propose_patches
from localharness.edits import SYSTEM_EDIT
from localharness.mcp_local import SYSTEM_PLAN, Server

CALC = "def suma(a, b):\n    return a - b\n"
TEST = ("import unittest\nfrom calc import suma\n\n\nclass T(unittest.TestCase):\n"
        "    def test_suma(self):\n        self.assertEqual(suma(2, 3), 5)\n")


def reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "gpt-oss.gguf"}


class FakeModels:
    """Contesta según el prompt de sistema; `edits` es la cola de respuestas a los encargos de edición."""

    def __init__(self, edits: list[str], review: list[dict] | None = None):
        self.edits = list(edits)
        self.review = list(review or [{"ok": True, "problems": [], "summary": "suma arreglada"}])
        self.seen: list[str] = []
        self.plans = 0

    def __call__(self, body: dict) -> dict:
        system = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        if system.startswith(SYSTEM_SELECT[:40]):
            self.seen.append("select")
            return reply(json.dumps({"files": ["calc.py", "test_calc.py", "no-existe.py"]}))
        if system.startswith(SYSTEM_PLAN[:40]):
            self.seen.append("plan")
            self.plans += 1
            assert "NORMAS DEL PROYECTO" in user and "Usa siempre unittest" in user
            return reply(json.dumps({"blocks": [{"id": "1", "kind": "edit", "path": "calc.py", "after": [],
                                                 "instructions": "que suma sume", "files": []}]}))
        if system.startswith(SYSTEM_REVIEW[:40]):
            self.seen.append("review")
            assert "diff --git" in user
            return reply(json.dumps(self.review.pop(0)))
        if system.startswith(SYSTEM_EDIT[:40]):
            self.seen.append("edit")
            return reply(self.edits.pop(0))
        raise AssertionError(f"encargo inesperado: {system[:80]}")


def edit(old: str, new: str) -> str:
    return f"<<<<<<< BUSCAR\n{old}\n=======\n{new}\n>>>>>>> REEMPLAZAR"


class BossTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "calc.py").write_text(CALC, encoding="utf-8")
        (self.root / "test_calc.py").write_text(TEST, encoding="utf-8")
        (self.root / "ENCARGO.md").write_text("# Encargo\nUsa siempre unittest.\n", encoding="utf-8")
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                    ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
            subprocess.run(cmd, cwd=self.root, check=True, capture_output=True)
        self.log = self.root.parent / f"{self.root.name}-encargos.jsonl"

    def tearDown(self):
        self.log.unlink(missing_ok=True)
        self.tmp.cleanup()

    def boss(self, models: FakeModels) -> tuple[Boss, list[str]]:
        said: list[str] = []
        s = Server({"LH_ROOT": str(self.root), "LH_LOG": str(self.log)}, transport=models)
        return Boss(s, check="python -m unittest", say=said.append), said

    def test_plans_runs_checks_reviews_and_reports(self):
        models = FakeModels([edit("    return a - b", "    return a + b")])
        boss, said = self.boss(models)
        report = boss.run("Arregla suma: tiene que sumar")
        self.assertEqual((self.root / "calc.py").read_text(encoding="utf-8"), "def suma(a, b):\n    return a + b\n")
        self.assertEqual(models.seen, ["select", "plan", "edit", "review"])
        self.assertIn("pasa", report.split("\n")[0])
        self.assertIn("suma arreglada", report)
        self.assertTrue(any("calc.py, test_calc.py" in t for t in said))  # el archivo inventado no pasa
        tools = [json.loads(line)["tool"] for line in self.log.read_text(encoding="utf-8").splitlines()]
        self.assertIn("jefe_local/elegir_archivos", tools)
        self.assertIn("jefe_local/planificar (Plan)", tools)
        self.assertIn("jefe_local/revisar", tools)

    def test_failing_tests_get_a_fix_round_with_the_output(self):
        # el primer cambio no arregla nada (y el arreglo automático del plan tampoco); el plan de arreglo, sí
        models = FakeModels([edit("    return a - b", "    return a * b"),
                             edit("    return a * b", "    return a * b  # sigue mal"),
                             edit("    return a * b  # sigue mal", "    return a + b")])
        boss, said = self.boss(models)
        report = boss.run("Arregla suma")
        self.assertIn("return a + b", (self.root / "calc.py").read_text(encoding="utf-8"))
        self.assertEqual(models.plans, 2)
        self.assertTrue(any("arreglo 1 de" in t for t in said))
        self.assertIn("Arreglo 1", report)
        self.assertIn("pasa", report.split("\n")[0])

    def test_review_problems_get_one_correction(self):
        models = FakeModels([edit("    return a - b", "    return a + b"),
                             edit("    return a + b", '    """Suma."""\n    return a + b')],
                            review=[{"ok": False, "problems": ["calc.py: falta el docstring"], "summary": ""},
                                    {"ok": True, "problems": [], "summary": "con docstring"}])
        boss, _ = self.boss(models)
        report = boss.run("Arregla suma y ponle docstring")
        self.assertIn('"""Suma."""', (self.root / "calc.py").read_text(encoding="utf-8"))
        self.assertEqual(models.seen.count("review"), 2)
        self.assertIn("con docstring", report)
        self.assertNotIn("Pendiente", report)

    def test_plan_shape_mistakes_are_repaired(self):
        from localharness.mcp_local import normalize_plan, validate_plan
        blocks = normalize_plan([
            {"id": "edit-atajos.js", "kind": "write", "path": "", "instructions": "crea atajos.js", "after": []},
            {"id": "idx", "title": "Enlazar en calc.py", "kind": "edit", "path": "", "instructions": "x",
             "after": ["edit-atajos.js", "no-existe"]},
            {"id": "idx", "kind": "edit", "path": "./tests/atajos.test.mjs", "instructions": "t", "after": ["idx"]},
        ], self.root)
        self.assertEqual([b["path"] for b in blocks], ["atajos.js", "calc.py", "tests/atajos.test.mjs"])
        self.assertEqual([b["kind"] for b in blocks], ["write", "edit", "write"])  # editar lo que no existe = crear
        self.assertEqual(blocks[1]["after"], ["edit-atajos.js"])
        self.assertEqual(blocks[2]["id"], "idx-3")
        self.assertEqual(validate_plan(blocks, self.root), [])

    def test_proposes_new_patches_without_repeating(self):
        def models(body):
            assert body["messages"][0]["content"] == SYSTEM_PROPOSE and "YA HECHO" in body["messages"][1]["content"]
            return reply(json.dumps({"patches": ["- Arregla suma de calc.py",  # ya hecho: fuera
                                                 "Módulo resta.py con resta(a, b) y tests de negativos y ceros",
                                                 "corto"]}))
        s = Server({"LH_ROOT": str(self.root)}, transport=models)
        self.assertEqual(propose_patches(s, ["Arregla suma de calc.py"]),
                         ["Módulo resta.py con resta(a, b) y tests de negativos y ceros"])

    def test_new_file_copies_the_structure_of_its_siblings(self):
        import os
        (self.root / "blog").mkdir()
        for i, name in enumerate(("parche-059.html", "parche-060.html", "index.html")):
            (self.root / "blog" / name).write_text("x", encoding="utf-8")
            os.utime(self.root / "blog" / name, (1000 + i, 1000 + i))
        boss, _ = self.boss(FakeModels([]))
        new = {"kind": "write", "path": "blog/parche-061.html", "instructions": "entrada"}
        boss.add_template(new)
        self.assertEqual(new["files"], ["blog/parche-060.html"])
        self.assertIn("PLANTILLA", new["instructions"])
        for b in ({"kind": "edit", "path": "blog/parche-060.html", "instructions": "x"},  # ya existe
                  {"kind": "write", "path": "tools/nuevo.mjs", "instructions": "x"}):  # carpeta sin hermanos
            boss.add_template(b)
            self.assertNotIn("files", b)

    def test_named_files_and_detect_check(self):
        boss, _ = self.boss(FakeModels([]))
        out = ('File "C:/x/.localharness-worktrees/repo/task-9/test_calc.py", line 7\n'
               "tests\\otro.mjs no existe\n  calc.py:2 AssertionError")
        self.assertEqual(boss.named_files(out), ["test_calc.py", "calc.py"])
        self.assertEqual(detect_check(self.root), "python -m unittest")
        (self.root / "web").mkdir()
        (self.root / "web" / "noche.js").write_text("x", encoding="utf-8")
        self.assertEqual(sorted(boss.mentioned("atajos.js con «n» que llama a noche.js; mira calc.py y ENCARGO.md")),
                         ["ENCARGO.md", "calc.py", "web/noche.js"])
        self.assertEqual(boss.mentioned("recalc.pyx y micalc.py no son calc.py"), ["calc.py"])
        (self.root / "package.json").write_text("{}", encoding="utf-8")
        self.assertEqual(detect_check(self.root), "node --test")


if __name__ == "__main__":
    unittest.main()
