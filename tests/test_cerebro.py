"""Cerebro 2 del jefe local: mapa de la API, arreglos mecánicos, tests después del código, escalera de arreglo con
diagnóstico, revisión consultiva y pensamiento por papel. Modelos de mentira; Node de verdad para los tests."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from localharness.boss import SYSTEM_REVIEW, SYSTEM_SELECT
from localharness.cerebro import (SYSTEM_DIAG, Cerebro, api_map, exports_of, first_failure, fix_duplicate_exports,
                                  fix_imports)
from localharness.mcp_local import SYSTEM_PLAN, SYSTEM_WRITE, Server, ToolError

NODE = shutil.which("node")
TASK = ("Dinero. src/dinero.js exporta aCentimos(valor) = Math.round(valor * 100) y formatear(c). "
        "tests/dinero.test.mjs: aCentimos(12.5) es 1250.")
BUGGY = ("export function aCentimos(valor) {\n  return Math.round(valor * 10);\n}\n\n"
         "export function formatear(c) {\n  return String(c);\n}\n\nexport { aCentimos, formatear };\n")
GOOD = BUGGY.replace("* 10)", "* 100)").replace("export { aCentimos, formatear };\n", "")
TEST = ("import { test } from 'node:test';\nimport assert from 'node:assert/strict';\n"
        "import { aCentimos } from '../src/dinero.js';\n\ntest('doce y medio', () => {\n"
        "  assert.equal(aCentimos(12.5), 1250);\n});\n")


def reply(content: str, reasoning: str = "") -> dict:
    msg = {"content": content}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {"choices": [{"message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "gpt-oss.gguf"}


class Fake:
    def __init__(self, writes: dict[str, list[str]], diag: list[dict], review: list[dict] | None = None):
        self.writes = {k: list(v) for k, v in writes.items()}
        self.diag = list(diag)
        self.review = list(review or [{"ok": True, "problems": [], "summary": "hecho"}])
        self.order: list[str] = []
        self.bodies: list[dict] = []

    def __call__(self, body: dict) -> dict:
        self.bodies.append(body)
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        if system.startswith(SYSTEM_SELECT[:40]):
            return reply(json.dumps({"files": []}))
        if system.startswith(SYSTEM_PLAN[:40]):
            self.order.append("plan")
            # el test va primero, fuera de su carpeta y sin `after`: el cerebro lo pone detrás y en tests/
            return reply(json.dumps({"blocks": [
                {"id": "t", "kind": "write", "path": "dinero.test.mjs", "after": [], "instructions": "tests"},
                {"id": "a", "kind": "write", "path": "src/dinero.js", "after": [], "instructions": "dinero"}]}))
        if system.startswith(SYSTEM_DIAG[:40]):
            self.order.append("diag")
            assert "FALLA ASÍ" in user and "   1 | " in user  # el fallo y los archivos con números de línea
            return reply(json.dumps(self.diag.pop(0)))
        if system.startswith(SYSTEM_REVIEW[:40]):
            self.order.append("review")
            return reply(json.dumps(self.review.pop(0)))
        if system.startswith(SYSTEM_WRITE[:40]):
            path = user.split("\n", 1)[0].removeprefix("ARCHIVO A ESCRIBIR: ").strip()
            self.order.append(f"write {path}")
            if path.startswith("tests/"):  # el test se escribe con el código ya hecho delante
                assert "--- src/dinero.js ---" in user, "el test no vio el código"
            return reply(f"```js\n{self.writes[path].pop(0)}```")
        raise AssertionError(f"encargo inesperado: {system[:60]}")


def repo() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "package.json").write_text(json.dumps({"type": "module", "scripts": {"test": "node --test"}}),
                                       encoding="utf-8")
    (root / "ENCARGO.md").write_text("# Encargo\nMódulos ES.\n", encoding="utf-8")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
        subprocess.run(cmd, cwd=root, check=True, capture_output=True)
    return root


class PiezasTests(unittest.TestCase):
    def test_exports_y_mapa(self):
        self.assertEqual(exports_of("export function a(x, y) {}\nexport const B = 1;\nexport { c, d as e };\n"),
                         {"a": "x, y", "B": "", "c": "", "e": ""})
        root = repo()
        (root / "src").mkdir()
        (root / "src" / "dinero.js").write_text(GOOD, encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests" / "dinero.test.mjs").write_text(TEST, encoding="utf-8")
        self.assertEqual(api_map(root), "- src/dinero.js: aCentimos(valor), formatear(c)")

    def test_export_duplicado(self):
        new, removed = fix_duplicate_exports(BUGGY)
        self.assertEqual(removed, ["aCentimos", "formatear"])
        self.assertNotIn("export {", new)
        new, removed = fix_duplicate_exports("export function a() {}\nfunction b() {}\nexport { a, b };\n")
        self.assertEqual((removed, new.splitlines()[-1]), (["a"], "export { b };"))
        same = "export { x } from './y.js';\n"
        self.assertEqual(fix_duplicate_exports(same), (same, []))

    def test_import_del_modulo_equivocado(self):
        root = repo()
        exported = {"src/dinero.js": {"aCentimos": ""}, "src/fechas.js": {"nombreMes": "", "mesDe": ""}}
        text = "import { aCentimos, nombreMes as nm } from '../src/dinero.js';\n"
        new, notes = fix_imports(root, "tests/dinero.test.mjs", text, exported)
        self.assertEqual(new, "import { aCentimos } from '../src/dinero.js';\n"
                              "import { nombreMes as nm } from '../src/fechas.js';\n")
        self.assertIn("fechas.js", notes[0])
        # extensión cambiada
        new, notes = fix_imports(root, "src/a.js", "import { mesDe } from './fechas.mjs';", exported)
        self.assertEqual(new, "import { mesDe } from './fechas.js';")
        # un nombre que no exporta nadie: no se toca (lo ve el depurador)
        text = "import { nada } from './dinero.js';"
        self.assertEqual(fix_imports(root, "src/a.js", text, exported), (text, []))

    def test_primer_fallo(self):
        out = ("código de salida 1\n✔ uno\n✖ dos\n  AssertionError: 1 !== 2\n" + "x\n" * 2000
               + "✖ failing tests:\n\ntest at tests/a.test.mjs:5:1\n✖ dos\n  AssertionError: 1 !== 2\n")
        self.assertTrue(first_failure(out).startswith("✖ failing tests:"))
        gates = "código de salida 1\nGUARDIAS DEL JEFE LOCAL (fallan aunque los tests pasen):\n- a.js: roto\n\nmás"
        self.assertIn("- a.js: roto", first_failure(gates))


class PensamientoTests(unittest.TestCase):
    def test_papel_fija_razonamiento_y_reintenta_sin_pensar(self):
        root = repo()
        calls = []

        def transport(body):
            calls.append(body)
            if len(calls) == 1:
                return reply("", reasoning="pienso pienso pienso")  # se queda pensando
            return reply(json.dumps({"files": []}))
        env = {"LH_ROOT": str(root), "LH_LOCAL_SERVERS": json.dumps([
            {"id": "principal", "url": "http://x", "role": "fuerte", "thinking": "normal"},
            {"id": "m40", "url": "http://y", "role": "general", "thinking": "normal"}])}
        c = Cerebro(Server(env, transport=transport),
                    roles={"elegir_archivos": {"servidor": "m40", "pensar": "profundo", "effort": "high"}})
        self.assertEqual(c.select_files(TASK, ""), [])
        self.assertEqual(calls[0]["chat_template_kwargs"], {"enable_thinking": True, "reasoning_effort": "high"})
        self.assertEqual(calls[1]["chat_template_kwargs"]["enable_thinking"], False)  # el reintento, sin pensar
        self.assertEqual(c.s.server_id, "m40")
        self.assertEqual(c.s.overrides, {})  # no se queda puesto para los obreros

    def test_el_jefe_uno_no_cambia(self):
        self.assertEqual(Cerebro.role_of("planificar (Arreglo 1)"), "planificar")
        self.assertEqual(Cerebro.role_of("proponer_parches"), "planificar")


@unittest.skipUnless(NODE, "hace falta node")
class VueltaCompletaTests(unittest.TestCase):
    def run_cerebro(self, fake: Fake) -> tuple[Cerebro, str, Path]:
        root = repo()
        env = {"LH_ROOT": str(root), "LH_LOG": str(root.parent / f"{root.name}.jsonl"),
               "LH_LOCAL_SERVERS": json.dumps([{"id": "principal", "url": "http://x", "role": "fuerte"},
                                               {"id": "rapido", "url": "http://y", "role": "rapido"}])}
        c = Cerebro(Server(env, transport=fake), check="npm test")
        return c, c.run(TASK), root

    def test_mecanico_diagnostico_y_verde(self):
        fake = Fake({"src/dinero.js": [BUGGY, GOOD], "tests/dinero.test.mjs": [TEST]},
                    diag=[{"archivo": "src/dinero.js", "culpable": "codigo", "causa": "multiplica por 10",
                           "cambio": "en aCentimos, Math.round(valor * 100)"}])
        c, report, root = self.run_cerebro(fake)
        self.assertIn("`npm test` pasa", report)
        self.assertFalse(c.rejected)
        self.assertTrue((root / "tests" / "dinero.test.mjs").is_file())
        self.assertFalse((root / "dinero.test.mjs").exists())
        writes = [o for o in fake.order if o.startswith("write")]
        self.assertEqual(writes[:2], ["write src/dinero.js", "write tests/dinero.test.mjs"])  # código, luego test
        self.assertIn("Arreglo mecánico (sin modelo): src/dinero.js: fuera el export duplicado", report)
        self.assertIn("Arreglo 1 (diagnóstico): src/dinero.js — multiplica por 10", report)
        self.assertEqual(fake.order[-1], "review")

    def test_revision_cuya_correccion_rompe_se_deshace(self):
        fake = Fake({"src/dinero.js": [GOOD, BUGGY.replace("export { aCentimos, formatear };\n", "")],
                     "tests/dinero.test.mjs": [TEST]}, diag=[],
                    review=[{"ok": False, "problems": ["src/dinero.js: formatear sin €"], "summary": "casi"}])
        original_plan = Fake.__call__

        def call(self, body):  # la corrección replanifica: un solo bloque sobre dinero.js
            if body["messages"][0]["content"].startswith(SYSTEM_PLAN[:40]) and "CORRECCIONES" in \
                    body["messages"][1]["content"]:
                return reply(json.dumps({"blocks": [{"id": "c", "kind": "edit", "path": "src/dinero.js",
                                                     "after": [], "instructions": "€"}]}))
            return original_plan(self, body)
        Fake.__call__ = call
        try:
            c, report, root = self.run_cerebro(fake)
        finally:
            Fake.__call__ = original_plan
        self.assertIn("rompía los tests y se deshizo", report)
        self.assertIn("`npm test` pasa", report)
        self.assertFalse(c.rejected)  # la revisión ya no rechaza con los tests en verde
        self.assertIn("* 100", (root / "src" / "dinero.js").read_text(encoding="utf-8"))

    def test_en_rojo_sube_la_escalera_hasta_reescribir(self):
        bad = GOOD.replace("* 100)", "* 7)")
        fake = Fake({"src/dinero.js": [bad, bad, bad, GOOD], "tests/dinero.test.mjs": [TEST]},
                    diag=[{"archivo": "src/dinero.js", "culpable": "codigo", "causa": "c1", "cambio": "x"},
                          {"archivo": "src/dinero.js", "culpable": "codigo", "causa": "c2", "cambio": "y"}])
        c, report, _ = self.run_cerebro(fake)
        self.assertIn("Arreglo 3 (reescritura entera): src/dinero.js", report)
        self.assertIn("`npm test` pasa", report)
        diag_users = [b["messages"][1]["content"] for b in fake.bodies
                      if b["messages"][0]["content"].startswith(SYSTEM_DIAG[:40])]
        self.assertIn("YA PROBADO", diag_users[1])  # el segundo diagnóstico sabe qué no funcionó


if __name__ == "__main__":
    unittest.main()
