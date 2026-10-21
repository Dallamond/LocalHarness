"""Cerebro 2 del jefe local: mapa de la API, arreglos mecánicos, tests después del código, escalera de arreglo con
diagnóstico, revisión consultiva y pensamiento por papel. Modelos de mentira; Node de verdad para los tests."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from localharness.boss import SYSTEM_REVIEW, SYSTEM_SELECT
from localharness.cerebro import (DEBT, PREV_MARK, SYSTEM_DIAG, Cerebro, api_map, exports_of, first_failure, fix_duplicate_exports,
                                  fix_duplicate_functions, fix_import_clash, fix_imports, fix_jest, fix_missing_imports,
                                  fix_fences, fix_stray_tests, restore_lost_exports,
                                  in_order)
from localharness.mcp_local import SYSTEM_PLAN, SYSTEM_WRITE, Server

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
    def test_tests_estilo_jest(self):
        from localharness.cerebro import JEST_CALL, imported_names
        ok = ("import { test, describe } from 'node:test';\nimport assert from 'node:assert/strict';\n"
              "describe('a', () => {\n  test('b', () => {});\n});\n")
        jest = "import { crearMapa } from '../src/mapa.js';\ndescribe('a', () => {\n  test('b', () => {});\n});\n"
        self.assertEqual({m.group(1) for m in JEST_CALL.finditer(ok)} - imported_names(ok), set())
        self.assertEqual({m.group(1) for m in JEST_CALL.finditer(jest)} - imported_names(jest), {"describe", "test"})

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

    def test_import_de_un_modulo_que_no_existe(self):
        root = repo()
        exported = {"src/dinero.js": {"aCentimos": ""}, "src/fechas.js": {"mesDe": ""}}
        # el mapa.js copiado de un ejemplo: crearMapa no se usa, mesDe está en fechas.js
        text = ("import { crearMapa, mesDe } from './mapa.js';\nexport function f(x) { return mesDe(x); }\n")
        new, notes = fix_imports(root, "src/resumen.js", text, exported)
        self.assertEqual(new, "import { mesDe } from './fechas.js';\nexport function f(x) { return mesDe(x); }\n")
        self.assertIn("mapa.js, que no existe", notes[0])
        # el nombre ya lo define el propio archivo: el import sobra entero
        text = "import { nombreMes } from './mapa.js';\nexport function nombreMes(m) { return m; }\n"
        self.assertEqual(fix_imports(root, "src/fechas.js", text, exported)[0],
                         "\nexport function nombreMes(m) { return m; }\n")
        # se usa y nadie lo exporta: no se toca
        text = "import { nada } from './mapa.js';\nnada();\n"
        self.assertEqual(fix_imports(root, "src/a.js", text, exported), (text, []))

    def test_secciones_citadas_se_pegan_a_la_tarea(self):
        root = repo()
        (root / "CONTRATO.md").write_text("# Contrato\n\nIntro.\n\n## 1. Mapa\n\n- src/mapa.js exporta TILE = 16.\n\n"
                                          "## 2. Física\n\n- src/fisica.js exporta GRAVEDAD = 0.5.\n\n"
                                          "## 3. Cámara\n\n- src/camara.js exporta camaraX.\n", encoding="utf-8")
        c = Cerebro.__new__(Cerebro)
        c.root = root
        task = "Hito 1. Implementa las secciones 1 a 2 del contrato con tus tests."
        out = c.with_sections(task)
        self.assertIn("src/mapa.js exporta TILE = 16", out)
        self.assertIn("GRAVEDAD = 0.5", out)
        self.assertNotIn("camaraX", out)
        self.assertEqual(c.task_paths(out)[-2:], ["src/mapa.js", "src/fisica.js"])
        self.assertEqual(c.with_sections(out), out)  # el reintento no lo pega dos veces
        self.assertEqual(c.with_sections("Relee el contrato sección por sección"),
                         "Relee el contrato sección por sección")

    def test_import_que_falta_en_un_test(self):
        root = repo()
        exported = {"src/dinero.js": {"aCentimos": ""}, "src/fechas.js": {"sumarMeses": "", "nombreMes": ""}}
        # el tests/fechas.test.mjs del 10/10: usa las funciones sin importarlas
        text = ('import { test } from "node:test";\nimport assert from "node:assert/strict";\n\n'
                'test("x", () => { assert.strictEqual(sumarMeses("2026-11", 2), "2027-01"); nombreMes("2026-01"); });\n')
        new, notes = fix_missing_imports(root, "tests/fechas.test.mjs", text, exported)
        self.assertIn("import { sumarMeses, nombreMes } from '../src/fechas.js';", new)
        self.assertTrue(new.index("node:assert") < new.index("../src/fechas.js") < new.index("test(\"x\""))
        self.assertIn("faltaba importar", notes[0])
        # lo que ya está importado, declarado o no exporta nadie: no se toca
        text = "import { sumarMeses } from '../src/fechas.js';\nfunction nombreMes() {}\nsumarMeses(); nombreMes(); otra();\n"
        self.assertEqual(fix_missing_imports(root, "tests/a.test.mjs", text, exported), (text, []))

    def test_funcion_declarada_dos_veces(self):
        text = ("function formatear(c) {\n  const s = '}';\n  return s + c;\n}\n\nexport function aCentimos(v) {"
                " return v; }\n\nexport function formatear(c) {\n  return `${c} €`;\n}\n")
        new, removed = fix_duplicate_functions(text)
        self.assertEqual(removed, ["formatear"])
        self.assertEqual(new.count("function formatear"), 1)
        self.assertIn("export function formatear", new)  # se queda la exportada
        self.assertIn("export function aCentimos", new)
        if NODE:
            ok = subprocess.run([NODE, "--input-type=module", "-e", new], capture_output=True)
            self.assertEqual(ok.returncode, 0, ok.stderr)

    def test_import_y_funcion_local_con_el_mismo_nombre(self):
        # a-modulo-falta: el modelo crea reloj.js y además deja crearReloj escrita dentro de juego.js
        root = Path(tempfile.mkdtemp())
        (root / "src").mkdir()
        (root / "src" / "reloj.js").write_text("export function crearReloj(s) { return { segundos: s }; }\n"
                                               "export function tic(r) { return r; }\n")
        exported = {"src/reloj.js": {"crearReloj": "function", "tic": "function"}, "src/juego.js": {}}
        text = ('import { crearReloj, tic } from "./reloj.js";\n\nfunction crearReloj(s) {\n  return { s: "}" };\n}\n\n'
                'export function crearPartida(s) { return crearReloj(s); }\n')
        new, notes = fix_import_clash(root, "src/juego.js", text, exported)
        self.assertEqual(new.count("function crearReloj"), 0)
        self.assertIn('import { crearReloj, tic } from "./reloj.js";', new)
        self.assertIn("export function crearPartida", new)
        self.assertIn("queda la del módulo", notes[0])
        # el módulo no exporta el nombre: se quita del import y queda la local
        exported["src/reloj.js"] = {"tic": "function"}
        new, notes = fix_import_clash(root, "src/juego.js", text, exported)
        self.assertIn('import { tic } from "./reloj.js";', new)
        self.assertEqual(new.count("function crearReloj"), 1)
        # sin choque: no se toca
        ok = 'import { tic } from "./reloj.js";\nfunction otra() {}\n'
        self.assertEqual(fix_import_clash(root, "src/juego.js", ok, exported), (ok, []))
    def test_jest_a_node_test(self):
        text = ("describe('tareas', () => {\n  test('suma', () => {\n    expect(anadir([], ' a ', 1)).toEqual([{ id: 1 }]);\n"
                "    expect(contar(l).total).toBe(2);\n    expect(() => anadir([], '', 1)).toThrow('texto vacío');\n"
                "    expect(l).not.toContain(3);\n    expect(f(a, b)).toBeGreaterThan(0);\n  });\n});\n")
        new, notes = fix_jest(text)
        self.assertNotIn("expect(", new)
        self.assertIn("import { describe, test } from 'node:test';", new)
        self.assertIn("import assert from 'node:assert/strict';", new)
        self.assertIn("assert.deepStrictEqual(anadir([], ' a ', 1), [{ id: 1 }]);", new)
        self.assertIn("assert.strictEqual(contar(l).total, 2);", new)
        self.assertIn("assert.throws(() => anadir([], '', 1), (e) => e.message.includes('texto vacío'));", new)
        self.assertIn("assert.ok(!l.includes(3));", new)
        self.assertIn("assert.ok((f(a, b)) > 0);", new)
        # ya con node:test importado: se añade lo que falta; un matcher raro deja los expect como están
        mixto = "import { test } from 'node:test';\ndescribe('x', () => { expect(a).toHaveProperty('b'); });\n"
        new, _ = fix_jest(mixto)
        self.assertIn("import { describe, test } from 'node:test';", new)
        self.assertIn("expect(a).toHaveProperty('b')", new)
        # un test que ya importa todo no se toca
        ok = "import { test } from 'node:test';\nimport assert from 'node:assert/strict';\ntest('a', () => assert.ok(1));\n"
        self.assertEqual(fix_jest(ok), (ok, []))

    def test_tests_sueltos_e_inventados(self):
        root = repo()
        (root / "tests").mkdir(exist_ok=True)
        (root / "tests" / "a.test.mjs").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=root, check=True)
        files = ["a.test.mjs", "b.test.mjs", "tests/ejemplo2.test.mjs", "tests/README.md", "tests/c.test.mjs"]
        for rel in files:
            (root / rel).write_text("y\n", encoding="utf-8")
        notes = fix_stray_tests(root, files, "Pide tests/c.test.mjs")
        self.assertFalse((root / "a.test.mjs").exists())
        self.assertFalse((root / "b.test.mjs").exists())
        self.assertTrue((root / "tests" / "b.test.mjs").exists())
        self.assertFalse((root / "tests" / "ejemplo2.test.mjs").exists())
        self.assertFalse((root / "tests" / "README.md").exists())
        self.assertTrue((root / "tests" / "c.test.mjs").exists())
        self.assertEqual(len(notes), 4)

    def test_vallas_pegadas_en_el_codigo(self):
        new, hit = fix_fences("```javascript\nexport function f() {}\n```\n")
        self.assertTrue(hit)
        self.assertEqual(new, "export function f() {}\n")
        self.assertFalse(fix_fences("export const a = 1;\n")[1])

    def test_recupera_exports_perdidos(self):
        old = "export function resumen(a) {\n  return a.map((x) => x);\n}\n\nexport function otra() {}\n"
        text = "export function resumenEn(a) {\n  return a;\n}\n"
        new, back = restore_lost_exports(text, old, {"resumen"})
        self.assertEqual(back, ["resumen"])
        self.assertIn("export function resumen(a) {\n  return a.map((x) => x);\n}", new)
        self.assertNotIn("otra", new)  # nadie la importa
        self.assertEqual(restore_lost_exports(new, old, {"resumen"})[1], [])  # ya está

    def test_orden_de_bloques(self):
        # el plan del parche 2: el CHANGELOG espera a los tests (5, 6), que van detrás del código
        blocks = [{"id": "1", "path": "src/a.js", "after": []}, {"id": "7", "path": "CHANGELOG.md", "after": ["1", "5", "6"]},
                  {"id": "5", "path": "tests/a.test.mjs", "after": ["1"]}, {"id": "6", "path": "tests/b.test.mjs",
                                                                           "after": ["9"]}]
        out = in_order(blocks)
        self.assertEqual([b["id"] for b in out], ["1", "5", "6", "7"])
        self.assertEqual(out[2]["after"], [])  # el 9 no existe
        ciclo = in_order([{"id": "a", "after": ["b"]}, {"id": "b", "after": ["a"]}])
        self.assertEqual([(b["id"], b["after"]) for b in ciclo], [("a", []), ("b", ["a"])])

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

    def test_mecanico_recupera_export_y_quita_vallas(self):
        root = repo()
        (root / "src").mkdir(exist_ok=True)
        (root / "tests").mkdir(exist_ok=True)
        (root / "src" / "resumen.js").write_text("export function resumen(a) {\n  return a.length;\n}\n", encoding="utf-8")
        (root / "src" / "texto.js").write_text("export const t = 1;\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=root, check=True)
        (root / "src" / "resumen.js").write_text("export function resumenEn(a) {\n  return a;\n}\n", encoding="utf-8")
        (root / "src" / "texto.js").write_text("```javascript\nexport const t = 2;\n```\n", encoding="utf-8")
        (root / "tests" / "resumen.test.mjs").write_text(
            "import { resumen, resumenEn } from '../src/resumen.js';\n", encoding="utf-8")
        c = Cerebro(Server({"LH_ROOT": str(root), "LH_LOCAL_SERVERS": json.dumps([{"id": "principal", "url": "http://x",
                                                                                      "role": "fuerte"}])}))
        notes = c.mechanical()
        self.assertIn("export function resumen(a)", (root / "src" / "resumen.js").read_text(encoding="utf-8"))
        self.assertEqual((root / "src" / "texto.js").read_text(encoding="utf-8"), "export const t = 2;\n")
        self.assertTrue(any("recuperadas" in n for n in notes) and any("```" in n for n in notes))

    def test_el_jefe_uno_no_cambia(self):
        self.assertEqual(Cerebro.role_of("planificar (Arreglo 1)"), "planificar")
        self.assertEqual(Cerebro.role_of("proponer_parches"), "planificar")


@unittest.skipUnless(NODE, "hace falta node")
class VueltaCompletaTests(unittest.TestCase):
    def run_cerebro(self, fake: Fake, recetas: str | None = None, task: str = TASK) -> tuple[Cerebro, str, Path]:
        root = repo()
        env = {"LH_ROOT": str(root), "LH_LOG": str(root.parent / f"{root.name}.jsonl"),
               "LH_LOCAL_SERVERS": json.dumps([{"id": "principal", "url": "http://x", "role": "fuerte"},
                                               {"id": "rapido", "url": "http://y", "role": "rapido"}])}
        c = Cerebro(Server(env, transport=fake), check="npm test", recetas=recetas)
        return c, c.run(task), root

    def test_intento_anterior_va_al_depurador_y_no_a_los_obreros(self):
        fake = Fake({"src/dinero.js": [BUGGY, GOOD], "tests/dinero.test.mjs": [TEST]},
                    diag=[{"archivo": "src/dinero.js", "culpable": "codigo", "causa": "por 10", "cambio": "por 100"}])
        task = TASK + "\n\n" + PREV_MARK + " (no salió)\nResultado: descartado (tests).\n- Arreglo 1: QUEMADO"
        c, report, root = self.run_cerebro(fake, task=task)
        writes = [b["messages"][1]["content"] for b in fake.bodies if "ARCHIVO A ESCRIBIR" in b["messages"][1]["content"]]
        self.assertTrue(writes and not any("QUEMADO" in w for w in writes))
        diag_users = [b["messages"][1]["content"] for b in fake.bodies
                      if b["messages"][0]["content"].startswith(SYSTEM_DIAG[:40])]
        self.assertIn("INTENTO ANTERIOR DE ESTE PARCHE", diag_users[0])
        self.assertIn("QUEMADO", diag_users[0])

    def test_receta_de_claude_sustituye_al_plan(self):
        """Con `recetas`, el plan principal es el de Claude tal cual: sin planificar, sin elegir archivos y sin que
        shape_plan añada tareas ni tests; el resto (verificar, revisión) sigue igual."""
        d = Path(tempfile.mkdtemp())
        (d / "otra.json").write_text(json.dumps([{"n": 1, "texto": "Otra cosa.", "blocks": []}]), encoding="utf-8")
        (d / "esta.json").write_text(json.dumps([{"n": 1, "texto": "Dinero. src/dinero.js exporta", "blocks": [
            {"id": "a", "kind": "write", "path": "src/dinero.js", "after": [], "instructions": "receta dinero"},
            {"id": "t", "kind": "write", "path": "tests/dinero.test.mjs", "after": ["a"], "files": ["src/dinero.js"],
             "instructions": "receta test"}]}]), encoding="utf-8")
        fake = Fake({"src/dinero.js": [GOOD], "tests/dinero.test.mjs": [TEST]}, diag=[])
        c, report, root = self.run_cerebro(fake, recetas=str(d))
        self.assertNotIn("plan", fake.order)
        self.assertEqual(fake.order, ["write src/dinero.js", "write tests/dinero.test.mjs", "review"])
        code = next(b for b in fake.bodies if b["messages"][1]["content"].startswith("ARCHIVO A ESCRIBIR: src/"))
        self.assertIn("receta dinero", code["messages"][1]["content"])
        self.assertNotIn("TAREA", code["messages"][1]["content"])
        self.assertIn("la receta de Claude (2 bloques", report)
        self.assertIn("`npm test` pasa", report)

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

    def test_plan_en_bucle_usa_el_plan_de_reserva(self):
        fake = Fake({"src/dinero.js": [GOOD], "tests/dinero.test.mjs": [TEST]}, diag=[])
        original = Fake.__call__

        def call(self, body):  # el planificador entra en bucle siempre (el parche 3 del 10/10)
            if body["messages"][0]["content"].startswith(SYSTEM_PLAN[:40]):
                self.order.append("plan")
                return {"choices": [{"message": {"content": "{\"blocks\": [{\"id\""}, "finish_reason": "loop"}],
                        "usage": {}, "model": "q.gguf"}
            return original(self, body)
        Fake.__call__ = call
        try:
            c, report, root = self.run_cerebro(fake)
        finally:
            Fake.__call__ = original
        self.assertEqual(fake.order.count("plan"), 2)  # dos intentos y luego la reserva
        self.assertIn("plan de reserva desde la tarea", report)
        self.assertIn("`npm test` pasa", report)
        self.assertEqual([o for o in fake.order if o.startswith("write")],
                         ["write src/dinero.js", "write tests/dinero.test.mjs"])

    def test_en_rojo_sube_la_escalera_hasta_reescribir(self):
        bad = [GOOD.replace("* 100)", f"* {n})") for n in (7, 8, 9)]  # cada ronda cambia algo, pero mal
        fake = Fake({"src/dinero.js": [*bad, GOOD], "tests/dinero.test.mjs": [TEST]},
                    diag=[{"archivo": "src/dinero.js", "culpable": "codigo", "causa": "c1", "cambio": "x"},
                          {"archivo": "src/dinero.js", "culpable": "codigo", "causa": "c2", "cambio": "y"}])
        c, report, _ = self.run_cerebro(fake)
        self.assertIn("Arreglo 3 (reescritura entera, desde cero): src/dinero.js", report)
        self.assertIn("`npm test` pasa", report)
        diag_users = [b["messages"][1]["content"] for b in fake.bodies
                      if b["messages"][0]["content"].startswith(SYSTEM_DIAG[:40])]
        self.assertIn("YA PROBADO", diag_users[1])  # el segundo diagnóstico sabe qué no funcionó
        rewrite = [b["messages"][1]["content"] for b in fake.bodies
                   if "ARCHIVO A ESCRIBIR: src/dinero.js" in b["messages"][1]["content"]][-1]
        self.assertNotIn("CONTENIDO ACTUAL", rewrite)  # desde cero: sin la versión mala delante

    def test_rescate_parcial_integra_lo_que_funciona(self):
        # formatear sigue mal tras toda la escalera: 1 de 3 tests nuevos falla → ese pasa a TODO y se integra
        test3 = TEST + ("\ntest('uno', () => {\n  assert.equal(aCentimos(1), 100);\n});\n"
                        "\ntest('formatea', async () => {\n  const { formatear } = await import('../src/dinero.js');\n"
                        "  assert.equal(formatear(5), '0,05 €');\n});\n")
        diag = {"archivo": "src/dinero.js", "culpable": "codigo", "causa": "formatear", "cambio": "x"}
        fake = Fake({"src/dinero.js": [GOOD] * 6, "tests/dinero.test.mjs": [test3]}, diag=[diag] * 3)
        c, report, root = self.run_cerebro(fake)
        self.assertTrue(report.startswith(DEBT), report[:300])
        self.assertFalse(c.rejected)
        text = (root / "tests" / "dinero.test.mjs").read_text(encoding="utf-8")
        self.assertIn("test.todo('formatea'", text)
        self.assertIn("test('uno'", text)  # lo que pasa no se toca
        self.assertIn("tests/dinero.test.mjs: formatea → TODO", report)

    def test_rescate_dentro_de_describe(self):
        # el 11/10 los tests venían en describe(…): la suite sale como fallo propio y el rescate no se hacía
        test3 = ("import { describe, it } from 'node:test';\nimport assert from 'node:assert/strict';\n"
                 "import { aCentimos, formatear } from '../src/dinero.js';\n\ndescribe('DINERO', () => {\n"
                 "  it('doce y medio', () => {\n    assert.equal(aCentimos(12.5), 1250);\n  });\n"
                 "  it('uno', () => {\n    assert.equal(aCentimos(1), 100);\n  });\n"
                 "  it('formatea', () => {\n    assert.equal(formatear(5), '0,05 €');\n  });\n});\n")
        diag = {"archivo": "src/dinero.js", "culpable": "codigo", "causa": "formatear", "cambio": "x"}
        fake = Fake({"src/dinero.js": [GOOD] * 6, "tests/dinero.test.mjs": [test3]}, diag=[diag] * 4)
        c, report, root = self.run_cerebro(fake)
        self.assertTrue(report.startswith(DEBT), report[:300])
        text = (root / "tests" / "dinero.test.mjs").read_text(encoding="utf-8")
        self.assertIn("it.todo('formatea'", text)
        self.assertIn("describe('DINERO'", text)

    def test_arreglo_que_rompe_lo_que_pasaba_se_deshace_y_se_mira_el_test(self):
        # el código está bien y el test espera un valor mal contado; «arreglar» el código rompe el otro test
        wrong = TEST + "\ntest('uno', () => {\n  assert.equal(aCentimos(1), 99);\n});\n"
        right = TEST + "\ntest('uno', () => {\n  assert.equal(aCentimos(1), 100);\n});\n"
        broken = GOOD.replace("Math.round(valor * 100)", "Math.round(valor * 99)")
        fake = Fake({"src/dinero.js": [GOOD, broken], "tests/dinero.test.mjs": [wrong, right]},
                    diag=[{"archivo": "src/dinero.js", "culpable": "codigo", "causa": "da 100", "cambio": "por 99"},
                          {"archivo": "tests/dinero.test.mjs", "culpable": "test", "causa": "1 € son 100",
                           "cambio": "en 'uno' espera 100"}])
        c, report, root = self.run_cerebro(fake)
        self.assertIn("deshecho, rompía 1 test(s) que pasaban (doce y medio)", report)
        self.assertIn("`npm test` pasa", report)
        self.assertIn("valor * 100", (root / "src" / "dinero.js").read_text(encoding="utf-8"))
        diag_users = [b["messages"][1]["content"] for b in fake.bodies
                      if b["messages"][0]["content"].startswith(SYSTEM_DIAG[:40])]
        self.assertNotIn("Mira PRIMERO el test", diag_users[0])
        self.assertIn("Mira PRIMERO el test", diag_users[1])
        self.assertIn("DESHECHO", diag_users[1])

    def test_sin_rescate_si_falla_mas_de_la_mitad(self):
        diag = {"archivo": "src/dinero.js", "culpable": "codigo", "causa": "c", "cambio": "x"}
        fake = Fake({"src/dinero.js": [BUGGY] * 6, "tests/dinero.test.mjs": [TEST]}, diag=[diag] * 4)
        c, report, root = self.run_cerebro(fake)
        self.assertFalse(report.startswith(DEBT))
        self.assertIn("Rescate parcial: no", report)
        self.assertNotIn("todo", (root / "tests" / "dinero.test.mjs").read_text(encoding="utf-8"))

    def test_ronda_que_no_cambia_nada_pasa_a_reescribir(self):
        bad = GOOD.replace("* 100)", "* 7)")
        fake = Fake({"src/dinero.js": [bad, bad, GOOD], "tests/dinero.test.mjs": [TEST]},
                    diag=[{"archivo": "src/dinero.js", "culpable": "codigo", "causa": "c1", "cambio": "x"}])
        c, report, _ = self.run_cerebro(fake)
        self.assertIn("Arreglo 1: no cambió nada; el siguiente reescribe", report)
        self.assertIn("Arreglo 2 (reescritura entera, desde cero): src/dinero.js", report)
        self.assertIn("`npm test` pasa", report)

    def test_dos_rondas_seguidas_sin_cambios_paran_la_escalera(self):
        # 18/10: hasta 4 rondas idénticas («Arreglo N: no cambió nada») y el mismo fallo al final
        bad = GOOD.replace("* 100)", "* 7)")
        fake = Fake({"src/dinero.js": [bad] * 8, "tests/dinero.test.mjs": [TEST]},
                    diag=[{"archivo": "src/dinero.js", "culpable": "codigo", "causa": "c1", "cambio": "x"}])
        c, report, _ = self.run_cerebro(fake)
        self.assertIn("Arreglo 2: no cambió nada; paro la escalera", report)
        self.assertNotIn("Arreglo 3", report)

    def test_los_bloques_de_codigo_llevan_la_tarea(self):
        fake = Fake({"src/dinero.js": [GOOD], "tests/dinero.test.mjs": [TEST]}, diag=[])
        self.run_cerebro(fake)
        code = [b["messages"][1]["content"] for b in fake.bodies
                if b["messages"][1]["content"].startswith("ARCHIVO A ESCRIBIR: src/dinero.js")]
        self.assertTrue(code)
        self.assertIn("TAREA (la especificación", code[0])

    def contrato(self) -> Cerebro:
        root = repo()
        shutil.copy(Path(__file__).parents[1] / "banco" / "pruebas" / "supersalto" / "semilla-libre" / "CONTRATO.md",
                    root / "CONTRATO.md")
        c = Cerebro.__new__(Cerebro)
        c.root, c.notes = root, []
        return c

    def test_cada_bloque_recibe_su_trozo_del_contrato(self):
        c = self.contrato()
        task = c.with_sections("Hito 2 · Jugador. Implementa las secciones 5 a 7 del contrato con tus propios tests.")
        spec = c.spec_for(["src/jugador.js"], task)
        self.assertIn("crearJugador(inicio) = {x: inicio.x + 2", spec)
        self.assertIn("LO QUE USA DE OTROS MÓDULOS", spec)
        self.assertIn("velocidadHorizontal(vx, entrada)", spec)  # la firma del módulo que usa
        self.assertNotIn("golpearBloque", spec)  # lo de otro archivo de la misma sección, no
        self.assertNotIn("camaraX", spec)
        self.assertLess(len(spec), 6000)
        # la introducción de la sección («Un cuerpo es …») va con los módulos de esa sección
        hito1 = c.with_sections("Hito 1 · Motor. Implementa las secciones 1 a 4 del contrato.")
        self.assertIn("Un cuerpo es {x, y, ancho, alto, vx, vy, enSuelo}", c.spec_for(["src/colision-x.js"], hito1))
        # un «Edita» de este hito lleva también el párrafo base del archivo, para no cambiar su firma
        hito4 = c.with_sections("Hito 4 · Juego jugable. Implementa las secciones 11 a 14 del contrato.")
        paso = c.spec_for(["src/paso.js"], hito4)
        self.assertIn("src/paso.js exporta paso(partida, entrada)", paso)
        self.assertIn("Edita src/paso.js (sin cambiar la firma de paso)", paso)
        self.assertEqual(c.spec_for(["src/otro.js"], hito4), "")
        self.assertEqual(c.spec_for(["src/jugador.js"], TASK), "")  # sin secciones citadas, nada

    def test_el_plan_se_completa_con_los_archivos_del_contrato(self):
        c = self.contrato()
        task = c.with_sections("Hito 1 · Motor. Implementa las secciones 1 a 4 del contrato.")
        extra = c.contract_blocks(task, [{"id": "a", "kind": "write", "path": "src/mapa.js"}])
        self.assertEqual([b["path"] for b in extra], ["src/rect.js", "src/fisica.js", "src/camara.js", "src/nivel.js",
                                                      "src/niveles.js", "src/colision-x.js", "src/colision-y.js"])
        self.assertIn("El plan no traía src/rect.js", c.notes[-1])

    def test_modulo_importado_que_no_existe(self):
        c = self.contrato()
        out = (f"- src/partida.js: no carga como módulo: Cannot find module '{c.root / 'src' / 'nivel.js'}' imported "
               f"from {c.root / 'src' / 'partida.js'}\n- Cannot find module 'D:/otro/sitio.js'")
        self.assertEqual(c.missing_modules(out, set()), ["src/nivel.js"])
        self.assertEqual(c.missing_modules(out, {"src/nivel.js"}), [])

    @unittest.skipUnless(NODE, "hace falta node")
    def test_guardia_de_salida_pegada(self):
        c = self.contrato()
        (c.root / "src").mkdir()
        (c.root / "src" / "efectos.js").write_text(
            "export const A = 1;\n```\nimport { test } from 'node:test';\n", encoding="utf-8")
        (c.root / "src" / "bien.js").write_text("export const B = '```no es una valla';\n", encoding="utf-8")
        problems = c.gates()
        self.assertTrue(any(p.startswith("src/efectos.js: lleva salida del modelo pegada") for p in problems))
        self.assertFalse(any(p.startswith("src/bien.js") for p in problems))

    def test_negativa_del_modelo(self):
        from localharness.mcp_local import is_refusal
        self.assertTrue(is_refusal("I’m sorry, but I can’t provide the requested code."))
        self.assertTrue(is_refusal("Lo siento, no puedo ayudar con eso."))
        self.assertFalse(is_refusal("export function sorry() {}\n"))


if __name__ == "__main__":
    unittest.main()
