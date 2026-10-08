"""Edición por buscar/reemplazar (edits.py), `local_edit_file`, bloques `edit` del plan, mapa del repo, contexto
según el modelo y el agente local que ya no se atasca releyendo."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from localharness.edits import EditError, apply_edits, parse_edits
from localharness.mcp_local import EDIT_OVER_CHARS, Server, read_log
from localharness.repomap import repo_map


def reply(text: str) -> dict:
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "qwen.gguf"}


def call(s: Server, name: str, args: dict) -> dict:
    return s.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": args}})


def block(search: str, replace: str) -> str:
    return f"<<<<<<< BUSCAR\n{search}=======\n{replace}>>>>>>> REEMPLAZAR\n"


class EditsTests(unittest.TestCase):
    def test_parse_and_apply(self):
        text = "Aquí van:\n" + block("b\n", "B\n") + block("d\n", "d\ne\n")
        edits = parse_edits(text)
        self.assertEqual(edits, [("b\n", "B\n"), ("d\n", "d\ne\n")])
        self.assertEqual(apply_edits("a\nb\nc\nd\n", edits), ("a\nB\nc\nd\ne\n", 2))

    def test_markers_without_the_words(self):
        # gpt-oss con poco razonamiento pone el nombre del archivo en vez de BUSCAR/REEMPLAZAR
        text = "<<<<<<< CHANGELOG.md\n- 041\n=======\n- 041\n- 042\n>>>>>>> CHANGELOG.md"
        self.assertEqual(parse_edits(text), [("- 041\n", "- 041\n- 042\n")])

    def test_a_model_stuck_in_a_loop_is_cut(self):
        from localharness.mcp_local import ToolError, looping
        stuck = "Hay que mirar night.js. " + "We can't open file. But we can approximate. Let's open night.js. " * 80
        self.assertTrue(looping(stuck))
        self.assertFalse(looping("".join(f"<li>parche {i:03d}: algo distinto</li>\n" for i in range(300))))
        with tempfile.TemporaryDirectory() as d:
            s = Server({"LH_ROOT": d})
            chunks = [b'data: {"choices":[{"delta":{"reasoning_content":"' + stuck[i:i + 50].encode() + b'"}}]}'
                      for i in range(0, len(stuck), 50)]
            seen = []

            def lines():
                for c in chunks:
                    seen.append(c)
                    yield c
            import localharness.mcp_local as m
            real = m.time.monotonic
            t = [0.0]

            def tick():  # cada trozo «tarda» 1 s: se comprueba en cada uno
                t[0] += 1
                return t[0]
            m.time.monotonic = tick
            try:
                data = s.read_stream(lines())
            finally:
                m.time.monotonic = real
            self.assertEqual(data["choices"][0]["finish_reason"], "loop")
            self.assertLess(len(seen), len(chunks))  # dejó de leer: llama-server para al cerrar
            s.transport = lambda body: data
            with self.assertRaises(ToolError) as e:
                s.complete("sys", "user")
            self.assertIn("bucle", str(e.exception))

    def test_waits_while_the_model_is_loading(self):
        import localharness.mcp_local as m
        from localharness.mcp_local import ToolError
        with tempfile.TemporaryDirectory() as d:
            s = Server({"LH_ROOT": d, "LH_LOCAL_URL": "http://127.0.0.1:9"})
            answers = [ToolError('llama-server HTTP 503: {"message":"Loading model"}')] * 2 + [{"ok": 1}]

            def once(body):
                a = answers.pop(0)
                if isinstance(a, Exception):
                    raise a
                return a
            s._post_once, s._live = once, lambda *a, **k: None
            old = m.LOAD_POLL_S
            m.LOAD_POLL_S = 0
            try:
                self.assertEqual(s._post({}), {"ok": 1})
                answers[:] = [ToolError("llama-server HTTP 500: roto")]
                with self.assertRaises(ToolError):
                    s._post({})
            finally:
                m.LOAD_POLL_S = old

    def test_loose_match_ignores_indentation(self):
        new, _ = apply_edits("def f():\n    return 1\n", [("return 1\n", "    return 2\n")])
        self.assertEqual(new, "def f():\n    return 2\n")

    def test_errors_say_what_is_wrong(self):
        with self.assertRaises(EditError) as e:
            apply_edits("x = 1\nx = 1\n", [("x = 1\n", "x = 2\n")])
        self.assertIn("2 veces", str(e.exception))
        with self.assertRaises(EditError) as e:
            apply_edits("const pieza = 'roble';\n", [("const pieza = 'pino';\n", "")])
        self.assertIn("Lo más parecido", str(e.exception))
        self.assertIn("roble", str(e.exception))
        with self.assertRaises(EditError):
            apply_edits("algo\n", [])

    def test_empty_search_only_creates(self):
        self.assertEqual(apply_edits("", [("", "nuevo\n")])[0], "nuevo\n")
        with self.assertRaises(EditError):
            apply_edits("ya hay algo\n", [("", "nuevo\n")])


class EditFileToolTests(unittest.TestCase):
    def test_edit_file_changes_only_the_piece_and_shows_the_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mapa.html").write_text("<ul>\n  <li>uno</li>\n</ul>\n", encoding="utf-8")
            seen = []

            def fake(body):
                seen.append(body)
                return reply(block("  <li>uno</li>\n", "  <li>uno</li>\n  <li>dos</li>\n"))
            s = Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl")}, transport=fake)
            r = call(s, "local_edit_file", {"path": "mapa.html", "instructions": "añade «dos»"})
            text = r["result"]["content"][0]["text"]
            self.assertIn("1 líneas añadidas y 0 quitadas", text)
            self.assertIn("+  <li>dos</li>", text)
            self.assertEqual((Path(tmp) / "mapa.html").read_text(encoding="utf-8"),
                             "<ul>\n  <li>uno</li>\n  <li>dos</li>\n</ul>\n")
            self.assertTrue(seen[0]["cache_prompt"])
            self.assertIn("BUSCAR", seen[0]["messages"][0]["content"])

    def test_edit_file_retries_once_with_the_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.js").write_text("const a = 1;\n", encoding="utf-8")
            answers = [block("const b = 1;\n", "x\n"), block("const a = 1;\n", "const a = 2;\n")]
            seen = []

            def fake(body):
                seen.append(body["messages"][1]["content"])
                return reply(answers[len(seen) - 1])
            s = Server({"LH_ROOT": tmp}, transport=fake)
            r = call(s, "local_edit_file", {"path": "a.js", "instructions": "a = 2"})
            self.assertNotIn("isError", r["result"])
            self.assertIn("NO SE PUDO APLICAR", seen[1])
            self.assertEqual((Path(tmp) / "a.js").read_text(encoding="utf-8"), "const a = 2;\n")

    def test_edit_file_gives_up_and_leaves_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.js").write_text("const a = 1;\n", encoding="utf-8")
            s = Server({"LH_ROOT": tmp}, transport=lambda body: reply("lo he cambiado, confía"))
            r = call(s, "local_edit_file", {"path": "a.js", "instructions": "a = 2"})
            self.assertTrue(r["result"]["isError"])
            self.assertEqual((Path(tmp) / "a.js").read_text(encoding="utf-8"), "const a = 1;\n")
            r = call(s, "local_edit_file", {"path": "no-existe.js", "instructions": "x"})
            self.assertIn("local_write_file", r["result"]["content"][0]["text"])

    def test_plan_write_on_a_big_file_is_done_as_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            big = "".join(f"<p>verso {i}</p>\n" for i in range(EDIT_OVER_CHARS // 10))
            (Path(tmp) / "antologia.html").write_text(big, encoding="utf-8")
            (Path(tmp) / "corto.css").write_text("a { }\n", encoding="utf-8")
            asked = []

            def fake(body):
                user = body["messages"][1]["content"]
                asked.append(user.split("\n", 1)[0])
                if user.startswith("ARCHIVO A CAMBIAR: antologia.html"):
                    return reply(block("<p>verso 0</p>\n", "<p>verso nuevo</p>\n<p>verso 0</p>\n"))
                return reply("```css\na { color: red; }\n```")
            s = Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl")}, transport=fake)
            r = call(s, "local_execute_plan", {"blocks": [
                {"id": "1", "kind": "write", "path": "antologia.html", "instructions": "añade un verso", "after": []},
                {"id": "2", "kind": "write", "path": "corto.css", "instructions": "rojo", "after": []}]})
            self.assertIn("2 de 2 bloques bien", r["result"]["content"][0]["text"])
            self.assertIn("ARCHIVO A CAMBIAR: antologia.html", asked)  # el grande, por trozos
            self.assertIn("ARCHIVO A ESCRIBIR: corto.css", asked)       # el pequeño, como pidió Claude
            text = (Path(tmp) / "antologia.html").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("<p>verso nuevo</p>\n<p>verso 0</p>\n"))
            self.assertEqual(len(text), len(big) + len("<p>verso nuevo</p>\n"))  # no se perdió nada
            log = read_log(Path(tmp) / "log.jsonl")
            self.assertEqual(next(e for e in log if e.get("block") == "1")["as"], "edit")

    def test_plan_edit_that_fails_on_a_converted_write_falls_back_to_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            big = "x\n" * EDIT_OVER_CHARS
            (Path(tmp) / "big.txt").write_text(big, encoding="utf-8")

            def fake(body):
                user = body["messages"][1]["content"]
                return reply("sin bloques" if user.startswith("ARCHIVO A CAMBIAR") else "```\nnuevo\n```")
            s = Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl")}, transport=fake)
            r = call(s, "local_execute_plan", {"blocks": [
                {"id": "1", "kind": "write", "path": "big.txt", "instructions": "reescríbelo", "after": []}]})
            self.assertIn("1 de 1 bloques bien", r["result"]["content"][0]["text"])
            self.assertEqual((Path(tmp) / "big.txt").read_text(encoding="utf-8"), "nuevo\n")


class BudgetTests(unittest.TestCase):
    def test_input_budget_follows_the_model_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            servers = json.dumps([{"id": "p", "url": "http://x", "role": "fuerte", "n_ctx": 16384}])
            s = Server({"LH_ROOT": tmp, "LH_LOCAL_SERVERS": servers, "LH_MAX_TOKENS": "4096"}, transport=reply)
            self.assertEqual(s.input_budget(), (16384 - 4096 - 1500) * 3)
            s = Server({"LH_ROOT": tmp, "LH_LOCAL_SERVERS": servers.replace("16384", "4096")}, transport=reply)
            self.assertEqual(s.input_budget(), 8000)  # nunca menos que esto
            s = Server({"LH_ROOT": tmp}, transport=reply)
            self.assertEqual(s.input_budget(), 40_000)  # sin datos del servidor: el tope de siempre


class RepoMapTests(unittest.TestCase):
    def test_map_outlines_each_kind_and_folds_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("MAX = 3\n\ndef suma(a, b):\n    return a + b\n\n\nclass Caja:\n"
                                         "    def abrir(self):\n        pass\n", encoding="utf-8")
            (root / "styles.css").write_text(":root { --tinta: #222; }\n.tarjeta h2 { color: var(--tinta); }\n"
                                             "@media (max-width: 480px) {\n  .tarjeta { width: 100%; }\n}\n",
                                             encoding="utf-8")
            (root / "index.html").write_text('<title>Taller</title><h1>El taller</h1><section id="obra">'
                                             '<script src="app.js"></script>', encoding="utf-8")
            (root / "app.js").write_text("export function montar() {}\nconst pinta = (x) => x;\n"
                                         "test('monta la portada', () => {});\n", encoding="utf-8")
            (root / "blog").mkdir()
            for i in range(1, 6):
                (root / "blog" / f"parche-00{i}.html").write_text(f"<h1>Parche {i}</h1>", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "x.js").write_text("function oculto() {}", encoding="utf-8")
            m = repo_map(root)
            for want in ("def suma(a, b)", "class Caja", "abrir", "MAX", ".tarjeta h2", "@media (max-width: 480px)",
                         "--tinta", "<title> Taller", "<h1> El taller", "ids: obra", "carga: app.js", "fn montar",
                         "fn pinta", "test «monta la portada»", "y 4 más con la misma forma"):
                self.assertIn(want, m)
            self.assertNotIn("oculto", m)
            self.assertNotIn("parche-003.html (", m)
            self.assertIn("app.py", repo_map(root, ["app.py"]))
            self.assertNotIn("styles.css", repo_map(root, ["app.py"]))

    def test_map_tool_needs_no_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")

            def no_model(body):
                raise AssertionError("local_map no debe llamar al modelo")
            r = call(Server({"LH_ROOT": tmp}, transport=no_model), "local_map", {})
            self.assertIn("def f()", r["result"]["content"][0]["text"])


class AgentEditTests(unittest.TestCase):
    def run_agent(self, tmp: str, script: list, **kw):
        from localharness.adapters.base import RunSpec
        from localharness.adapters.local_agent import LocalAgentAdapter
        import httpx
        turns = iter(script)

        def handler(request):
            if request.url.path.endswith("/v1/models"):
                return httpx.Response(200, json={"data": [{"id": "qwen.gguf"}]})
            name, args = next(turns)
            return httpx.Response(200, json={"choices": [{"message": {"content": "", "tool_calls": [
                {"id": "c", "function": {"name": name, "arguments": json.dumps(args)}}]}}]})
        events = []
        adapter = LocalAgentAdapter(base_url="http://x", transport=httpx.MockTransport(handler), **kw)
        res = asyncio.run(adapter.execute(RunSpec(prompt="haz algo", cwd=tmp, max_turns=30), events.append, 60))
        return res, events

    def test_editar_archivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.txt").write_text("uno\ndos\n", encoding="utf-8")
            res, _ = self.run_agent(tmp, [("editar_archivo", {"ruta": "a.txt", "buscar": "dos\n",
                                                              "reemplazar": "dos\ntres\n"}),
                                          ("terminar", {"resumen": "hecho"})])
            self.assertEqual(res["status"], "done")
            self.assertEqual((Path(tmp) / "a.txt").read_text(encoding="utf-8"), "uno\ndos\ntres\n")

    def test_stops_when_it_only_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(12):
                (Path(tmp) / f"f{i}.txt").write_text("x", encoding="utf-8")
            script = [("leer_archivo", {"ruta": f"f{i}.txt"}) for i in range(12)]
            res, events = self.run_agent(tmp, script, max_idle_turns=8)
            self.assertEqual(res["status"], "failed")
            self.assertTrue(any("sin escribir nada" in e.text for e in events if e.kind == "error"))

    def test_stops_when_it_rereads_the_same_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            for n in ("a", "b"):
                (Path(tmp) / f"{n}.txt").write_text("x", encoding="utf-8")
            script = [("leer_archivo", {"ruta": "a.txt"}), ("leer_archivo", {"ruta": "b.txt"})] * 3
            res, events = self.run_agent(tmp, script)
            self.assertEqual(res["status"], "failed")
            self.assertTrue(any("repite la misma llamada" in e.text for e in events if e.kind == "error"))


if __name__ == "__main__":
    unittest.main()
