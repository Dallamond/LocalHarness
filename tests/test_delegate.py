"""Claude delega en el modelo local: servidor MCP (localharness.mcp_local) y su cableado en la tarea."""

import json, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from localharness import llama, settings
from localharness.adapters import get_adapter
from localharness.adapters.base import RunSpec
from localharness.adapters.local_agent import LocalAgentAdapter
from localharness.mcp_local import Server, page_text, parse_ddg, read_log, strip_fence
from localharness.orchestrator import execute_task
from localharness.store import Store
from tests.test_core import FAKES, make_repo

FAKE = str(FAKES / "claude")  # NUNCA la CLI real en pruebas


def reply(text: str, reasoning: str = "") -> dict:
    return {"model": "D:\\m\\Qwen3.5-9B-Q4_K_M.gguf",
            "choices": [{"message": {"content": text, "reasoning_content": reasoning}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}, "timings": {"predicted_per_second": 41.7}}


def server(tmp: str, answer: str = "respuesta local", write: bool = True, seen: list | None = None) -> Server:
    def fake(body):
        if seen is not None:
            seen.append(body)
        return reply(answer)
    return Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl"), "LH_WRITE": "1" if write else "0"},
                  transport=fake)


def call(s: Server, name: str, args: dict) -> dict:
    return s.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": args}})


class McpServerTests(unittest.TestCase):
    def test_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = server(tmp)
            init = s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2025-03-26"}})
            self.assertEqual(init["result"]["protocolVersion"], "2025-03-26")  # se adapta al cliente
            self.assertIsNone(s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
            names = [t["name"] for t in s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
            self.assertEqual(names, ["local_map", "local_ask", "local_edit_file", "local_write_file",
                                     "local_execute_plan", "local_plan", "local_agent", "run_checks",
                                     "local_research", "local_read_documents", "local_look"])
            ro = server(tmp, write=False).handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            # Director / jefe: pensar e investigar, nunca escribir
            self.assertEqual([t["name"] for t in ro["result"]["tools"]],
                             ["local_map", "local_ask", "run_checks", "local_research", "local_read_documents",
                              "local_look"])
            self.assertIn("error", s.handle({"jsonrpc": "2.0", "id": 3, "method": "otra/cosa"}))

    def test_ask_reads_files_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.py").write_text("def suma(a, b):\n    return a - b\n")
            seen = []
            r = call(server(tmp, "suma resta en vez de sumar", seen=seen), "local_ask",
                     {"task": "¿Qué fallo hay?", "files": ["a.py"]})
            self.assertEqual(r["result"]["content"][0]["text"], "suma resta en vez de sumar")
            self.assertIn("return a - b", seen[0]["messages"][1]["content"])  # lo leyó el servidor, no Claude
            log = read_log(Path(tmp) / "log.jsonl")[0]
            self.assertEqual((log["ok"], log["completion_tokens"], log["model"], log["files"]),
                             (True, 30, "Qwen3.5-9B-Q4_K_M", ["a.py"]))

    def test_write_file_and_confinement(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = server(tmp, "Aquí va:\n```python\ndef hola():\n    return 1\n```\nListo.")
            r = call(s, "local_write_file", {"path": "src/nuevo.py", "instructions": "función hola"})
            self.assertNotIn("isError", r["result"])
            self.assertEqual((Path(tmp) / "src" / "nuevo.py").read_text(), "def hola():\n    return 1\n")
            for bad in ("../fuera.py", ".git/config"):
                r = call(s, "local_write_file", {"path": bad, "instructions": "x"})
                self.assertTrue(r["result"]["isError"], bad)
            self.assertFalse((Path(tmp).parent / "fuera.py").exists())
            ro = call(server(tmp, write=False), "local_write_file", {"path": "x.py", "instructions": "x"})
            self.assertTrue(ro["result"]["isError"])

    def test_failures_tell_claude_to_do_it_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            off = Server({"LH_ROOT": tmp, "LH_LOCAL_URL": "http://127.0.0.1:9"})  # nadie escucha
            r = call(off, "local_ask", {"task": "hola"})
            self.assertTrue(r["result"]["isError"]); self.assertIn("hazlo tú", r["result"]["content"][0]["text"])
            think = Server({"LH_ROOT": tmp}, transport=lambda b: reply("", reasoning="mmm"))
            r = call(think, "local_ask", {"task": "hola"})
            self.assertIn("se quedó pensando", r["result"]["content"][0]["text"])

    def test_execute_plan_does_every_block_and_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "calc.py").write_text("def suma(a, b):\n    return a - b\n")
            seen = []
            answers = iter(["```python\ndef suma(a, b):\n    return a + b\n```",
                            "```python\nimport unittest\nfrom calc import suma\n\n\nclass T(unittest.TestCase):\n"
                            "    def test_suma(self):\n        self.assertEqual(suma(2, 3), 5)\n```",
                            "Todo bien"])

            def fake(body):
                seen.append(body)
                return reply(next(answers))
            s = Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl")}, transport=fake)
            r = call(s, "local_execute_plan", {"blocks": [
                {"id": "1", "title": "arreglar suma", "kind": "write", "path": "calc.py", "instructions": "suma"},
                {"id": "2", "title": "tests", "kind": "write", "path": "test_calc.py", "instructions": "tests",
                 "files": ["calc.py"]},
                {"id": "3", "title": "revisión", "kind": "ask", "instructions": "¿algo más?", "files": ["calc.py"]}],
                "check": "python -m unittest test_calc"})
            text = r["result"]["content"][0]["text"]
            self.assertNotIn("isError", r["result"])
            self.assertIn("3 de 3 bloques bien", text)
            self.assertIn("Todo bien", text)                       # la respuesta del bloque ask llega entera
            self.assertIn("código de salida 0", text)              # la comprobación la ejecutó el servidor
            self.assertIn("return a + b", (Path(tmp) / "calc.py").read_text())
            self.assertIn("return a + b", seen[1]["messages"][1]["content"])  # el bloque 2 ve lo que escribió el 1
            log = read_log(Path(tmp) / "log.jsonl")
            self.assertEqual([e["tool"] for e in log], ["local_execute_plan/write", "local_execute_plan/write",
                                                        "local_execute_plan/ask", "local_execute_plan"])
            self.assertEqual(log[-1]["task"], "plan: 3 de 3 bloques")

    def plan_with_wrong_test(self, tmp: str, fix: str) -> tuple[str, list]:
        """calc.py bien y un test que se equivoca: el plan lo intenta arreglar solo, cambiando solo el trozo."""
        good = "```python\ndef suma(a, b):\n    return a + b\n```"
        bad = ("```python\nimport unittest\nfrom calc import suma\n\n\nclass T(unittest.TestCase):\n"
               "    def test_suma(self):\n        self.assertEqual(suma(2, 3), 6)\n```")
        seen = []

        def fake(body):
            user = body["messages"][1]["content"]
            seen.append(user)
            if user.startswith("ARCHIVO A ESCRIBIR: calc.py"):
                return reply(good)
            if user.startswith("ARCHIVO A ESCRIBIR: test_calc.py"):
                return reply(bad)
            if user.startswith("ARCHIVO A CAMBIAR: test_calc.py"):
                return reply(fix)
            return reply("¿?")
        s = Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl")}, transport=fake)
        r = call(s, "local_execute_plan", {"blocks": [
            {"id": "t", "kind": "write", "path": "test_calc.py", "instructions": "test de suma en calc.py",
             "after": []},
            {"id": "c", "kind": "write", "path": "calc.py", "instructions": "suma", "after": []}],
            "check": "python -m unittest test_calc"})
        return r["result"]["content"][0]["text"], seen

    def test_execute_plan_test_waits_for_its_code_and_fixes_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, seen = self.plan_with_wrong_test(tmp, (
                "<<<<<<< BUSCAR\n        self.assertEqual(suma(2, 3), 6)\n=======\n"
                "        self.assertEqual(suma(2, 3), 5)\n>>>>>>> REEMPLAZAR"))
            first_test = next(u for u in seen if u.startswith("ARCHIVO A ESCRIBIR: test_calc.py"))
            self.assertIn("return a + b", first_test)        # el test se escribió viendo calc.py ya escrito
            self.assertIn("test_calc.py → calc.py", text)
            self.assertIn("Ronda 1: corrigió `test_calc.py`", text)
            self.assertIn("Ahora la comprobación pasa", text)
            self.assertIn("código de salida 0", text)
            fix = next(u for u in seen if u.startswith("ARCHIVO A CAMBIAR: test_calc.py"))
            self.assertIn("CORRECCIÓN", fix)
            self.assertIn("5 != 6", fix)  # con el error delante
            log = read_log(Path(tmp) / "log.jsonl")
            # sin la pregunta previa de «qué archivo»: el error ya lo nombra
            self.assertEqual([e["block"] for e in log if str(e.get("block", "")).startswith("arreglo")], ["arreglo1"])
            self.assertTrue(log[-1]["check_ok"])

    def test_execute_plan_auto_fix_is_one_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, _ = self.plan_with_wrong_test(tmp, (
                "<<<<<<< BUSCAR\n        self.assertEqual(suma(2, 3), 6)\n=======\n"
                "        self.assertEqual(suma(2, 2), 5)\n>>>>>>> REEMPLAZAR"))
            self.assertIn("Ronda 1", text)
            self.assertNotIn("Ronda 2", text)
            self.assertIn("Sigue fallando", text)
            self.assertFalse(read_log(Path(tmp) / "log.jsonl")[-1]["check_ok"])

    def test_auto_fix_skips_when_the_error_is_in_another_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "test_otro.py").write_text("import unittest\n\n\nclass T(unittest.TestCase):\n"
                                                    "    def test_x(self):\n        self.fail('falta en el mapa')\n")
            seen = []

            def fake(body):
                seen.append(body["messages"][1]["content"])
                return reply("```python\nX = 1\n```")
            s = Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl")}, transport=fake)
            r = call(s, "local_execute_plan", {"blocks": [
                {"id": "a", "kind": "write", "path": "a.py", "instructions": "X = 1", "after": []}],
                "check": "python -m unittest test_otro"})
            text = r["result"]["content"][0]["text"]
            self.assertIn("Sin arreglo automático", text)
            self.assertEqual(len(seen), 1)  # ni una llamada de más al modelo

    def test_tests_after_code_never_makes_a_cycle(self):
        from localharness.mcp_local import tests_after_code
        items = [{"id": "t", "kind": "write", "path": "tests/a.test.mjs", "b": {"instructions": "mira a.js"},
                  "files": [], "after": []},
                 {"id": "a", "kind": "write", "path": "a.js", "b": {}, "files": [], "after": ["t"]},
                 {"id": "h", "kind": "write", "path": "web/index.html", "b": {}, "files": [], "after": []},
                 {"id": "u", "kind": "write", "path": "tests/b.test.mjs", "b": {"instructions": "x"},
                  "files": ["index.html"], "after": []}]
        self.assertEqual(tests_after_code(items), [("tests/b.test.mjs", ["web/index.html"])])
        self.assertEqual(items[0]["after"], [])  # a.js ya depende del test: esperarlo sería un ciclo
        self.assertEqual(items[3]["after"], ["h"])

    def test_execute_plan_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = server(tmp, "```\nx\n```")
            r = call(s, "local_execute_plan", {"blocks": [
                {"kind": "write", "path": "../fuera.py", "instructions": "x"},
                {"kind": "write", "path": "ok.txt", "instructions": "x"}], "check": "rm -rf ."})
            text = r["result"]["content"][0]["text"]
            self.assertIn("1 de 2 bloques bien", text)   # un bloque malo no para el resto
            self.assertIn("orden no permitida", text)    # la comprobación solo de la lista blanca
            self.assertTrue((Path(tmp) / "ok.txt").exists())
            self.assertTrue(call(s, "local_execute_plan", {"blocks": []})["result"]["isError"])
            self.assertNotIn("local_execute_plan", [t["name"] for t in server(tmp, write=False).tools()])
            off = Server({"LH_ROOT": tmp, "LH_LOCAL_URL": "http://127.0.0.1:9", "LH_COORDINATOR": "1"})
            r = call(off, "local_execute_plan", {"blocks": [{"path": "a.txt", "instructions": "x"}]})
            msg = r["result"]["content"][0]["text"]
            self.assertTrue(r["result"]["isError"])
            self.assertIn("díselo al usuario", msg); self.assertNotIn("hazlo tú", msg)  # coordinador: no puede hacerlo él

    def test_worker_skills_and_chat(self):
        """El trabajador local: Claude elige sus skills (local_prepare) y se aplican a cada encargo siguiente."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "skills.json").write_text(json.dumps({"tests-primero": {"description": "Escribe el test antes",
                                                                         "body": "REGLA: primero el test."}}))
            (d / "worker.json").write_text(json.dumps({"skills": [], "tools": None}))
            seen = []

            def fake(body):
                seen.append(body)
                return reply("hecho", reasoning="primero pienso en el test")
            s = Server({"LH_ROOT": tmp, "LH_LOG": str(d / "log.jsonl"), "LH_WORKER": str(d / "worker.json"),
                        "LH_SKILLS": str(d / "skills.json")}, transport=fake)
            tools = s.tools()
            self.assertEqual(tools[0]["name"], "local_prepare")
            self.assertIn("tests-primero: Escribe el test antes", tools[0]["description"])  # ve lo que hay
            bad = call(s, "local_prepare", {"skills": ["no-existe"]})
            self.assertTrue(bad["result"]["isError"]); self.assertIn("tests-primero", bad["result"]["content"][0]["text"])
            ok = call(s, "local_prepare", {"skills": ["tests-primero"], "tools": ["leer_archivo", "ejecutar"],
                                           "reason": "hay que arreglar un fallo"})
            self.assertNotIn("isError", ok["result"])
            state = json.loads((d / "worker.json").read_text())
            self.assertEqual((state["skills"], state["tools"], state["by"]),
                             (["tests-primero"], ["leer_archivo", "ejecutar"], "Claude"))
            call(s, "local_ask", {"task": "arregla esto"})
            self.assertIn("REGLA: primero el test.", seen[0]["messages"][0]["content"])  # la skill va en el sistema
            log = read_log(d / "log.jsonl")
            self.assertEqual([e["tool"] for e in log], ["local_prepare", "local_prepare", "local_ask"])
            ask = log[2]
            self.assertEqual((ask["request"], ask["answer"], ask["thinking"], ask["skills"]),
                             ("arregla esto", "hecho", "primero pienso en el test", ["tests-primero"]))
            names = LocalAgentAdapter(only_tools=["leer_archivo"]).tool_names(read_only=False)
            self.assertEqual(names, ["leer_archivo", "avisar_progreso", "terminar"])  # las de control, siempre

    def test_streaming_answer_and_live_state(self):
        """llama-server en streaming: la respuesta se arma de los trozos y el directo (LH_LIVE) queda al día."""
        class Streamer(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert body["stream"] is True
                chunks = [{"choices": [{"delta": {"reasoning_content": "Pienso en "}}]},
                          {"choices": [{"delta": {"reasoning_content": "la suma."}}]},
                          {"choices": [{"delta": {"content": "Hay que "}}], "model": "Qwen3-8B.gguf"},
                          {"choices": [{"delta": {"content": "sumar."}, "finish_reason": "stop"}]},
                          {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 7},
                           "timings": {"predicted_per_second": 33.3}}]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for c in chunks:
                    self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

            def log_message(self, *a):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Streamer)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                live = Path(tmp) / "live.json"
                s = Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl"), "LH_LIVE": str(live),
                            "LH_LOCAL_URL": f"http://127.0.0.1:{httpd.server_port}"})
                r = call(s, "local_ask", {"task": "¿qué falla?"})
                self.assertEqual(r["result"]["content"][0]["text"], "Hay que sumar.")
                log = read_log(Path(tmp) / "log.jsonl")[0]
                self.assertEqual((log["thinking"], log["completion_tokens"], log["tps"], log["model"]),
                                 ("Pienso en la suma.", 7, 33.3, "Qwen3-8B"))
                state = json.loads(live.read_text(encoding="utf-8"))
                self.assertEqual((state["tool"], state["task"], state["thinking"], state["text"], state["done"]),
                                 ("local_ask", "¿qué falla?", "Pienso en la suma.", "Hay que sumar.", True))
                # la velocidad final (la de llama-server) va en el directo: la usa el monitor de recursos
                self.assertEqual((state["server"], state["tps"], state["tokens"]), ("principal", 33.3, 7))
                self.assertTrue(state["servers"]["principal"]["done"])
        finally:
            httpd.shutdown()

    def test_live_per_server_and_one_event_each(self):
        """Dos modelos a la vez: cada uno su entrada en el directo y el orquestador emite un `worker_live` por modelo."""
        from localharness.orchestrator import _emit_live
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "live.json"
            s = Server({"LH_ROOT": tmp, "LH_LIVE": str(live), "LH_LOCAL_SERVERS": json.dumps([
                {"id": "principal", "url": "http://127.0.0.1:1", "role": "fuerte"},
                {"id": "rapido", "url": "http://127.0.0.1:2", "role": "rapido"}])})
            s.current = {"tool": "local_write_file", "task": "a.py", "server": "principal"}
            s._live("", "escribo a.py", tps=20.0)
            s.current = {"tool": "local_ask", "task": "¿bugs?", "server": "rapido"}
            s._live("pienso", "")
            evs: list = []
            deleg = {"live": str(live)}
            _emit_live(deleg, evs.append)
            self.assertEqual(sorted((e.data["server"], e.data["tool"]) for e in evs),
                             [("principal", "local_write_file"), ("rapido", "local_ask")])
            evs.clear()
            _emit_live(deleg, evs.append)  # nada nuevo: no repite
            self.assertEqual(evs, [])
            s._live("pienso más", "")
            _emit_live(deleg, evs.append)
            self.assertEqual([e.data["server"] for e in evs], ["rapido"])

    def test_read_only_tools_can_run_together(self):
        """Claude Code solo lanza a la vez herramientas MCP de solo lectura: preguntar e investigar lo son."""
        with tempfile.TemporaryDirectory() as tmp:
            tools = {t["name"]: t for t in Server({"LH_ROOT": tmp}).tools()}
            self.assertTrue(tools["local_ask"]["annotations"]["readOnlyHint"])
            self.assertTrue(tools["local_research"]["annotations"]["readOnlyHint"])
            self.assertNotIn("annotations", tools["local_write_file"])

    def test_strip_fence(self):
        self.assertEqual(strip_fence("```js\nx = 1\n```"), "x = 1")
        self.assertEqual(strip_fence("sin bloque"), "sin bloque")


class AdapterTests(unittest.TestCase):
    def test_mcp_flags(self):
        cmd = get_adapter("claude").build_command(RunSpec(prompt="x", cwd=".", mcp_config="m.json",
                                                          mcp_tools=["mcp__local__local_ask"]))
        self.assertEqual(cmd[cmd.index("--mcp-config") + 1], "m.json")
        self.assertIn("--strict-mcp-config", cmd)  # solo nuestro servidor, nada del usuario
        self.assertNotIn("--safe-mode", cmd)  # bloquea también los servidores de --mcp-config (verificado)
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        self.assertIn("--disable-slash-commands", cmd)
        plain = get_adapter("claude").build_command(RunSpec(prompt="x", cwd="."))
        self.assertIn("--safe-mode", plain)  # sin MCP, el aislamiento barato de siempre
        self.assertIn("mcp__local__local_ask", cmd[cmd.index("--allowedTools") + 1])
        self.assertNotIn("mcp__", cmd[cmd.index("--tools") + 1])  # --tools es solo para las integradas


class FakeLlama(BaseHTTPRequestHandler):
    auth: list = []

    def do_POST(self):
        FakeLlama.auth.append(self.headers.get("Authorization"))
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps(reply("```\nhola desde el modelo local\n```")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


DDG = """
<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2Flibrary%2Ftomllib.html&amp;rut=x">tomllib &mdash; <b>TOML</b></a>
<a class="result__snippet" href="#">Parse <b>TOML</b> files.</a></div>
<div class="result"><a class="result__a" href="https://duckduckgo.com/y.js?ad=1">Anuncio</a><a class="result__snippet">ad</a></div>
<div class="result"><a class="result__a" href="https://peps.python.org/pep-0680/">PEP 680</a>
<a class="result__snippet" href="#">tomllib en la stdlib</a></div>
"""
PAGE = "<html><head><style>x{}</style><script>var a</script></head><body><nav>menú</nav><h1>tomllib</h1>" \
       "<p>Nuevo en la versión 3.11.</p></body></html>"


class ResearchTests(unittest.TestCase):
    def web(self, tmp, seen_urls, seen_bodies, fail=()):
        def get(url, data):
            seen_urls.append((url, data))
            if url in fail:
                raise OSError("caída")
            return DDG if data else PAGE
        def llm(body):
            seen_bodies.append(body)
            return reply("Desde Python 3.11 [1].")
        return Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl"), "LH_WRITE": "0"},
                      transport=llm, http_get=get)

    def test_parse_ddg(self):
        r = parse_ddg(DDG)
        self.assertEqual([x["url"] for x in r], ["https://docs.python.org/3/library/tomllib.html",
                                                 "https://peps.python.org/pep-0680/"])  # sin anuncio, sin redirección
        self.assertEqual((r[0]["title"], r[0]["snippet"]), ("tomllib — TOML", "Parse TOML files."))

    def test_page_text_drops_scripts_and_menus(self):
        self.assertEqual(page_text(PAGE), "tomllib\nNuevo en la versión 3.11.")

    def test_research_reads_pages_and_cites_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            urls, bodies = [], []
            s = self.web(tmp, urls, bodies, fail={"https://peps.python.org/pep-0680/"})
            r = call(s, "local_research", {"question": "¿Desde qué versión hay tomllib?", "query": "python tomllib"})
            text = r["result"]["content"][0]["text"]
            self.assertIn("Desde Python 3.11 [1].", text)
            self.assertIn("[1] tomllib — TOML — https://docs.python.org/3/library/tomllib.html", text)
            self.assertEqual(urls[0][1], {"q": "python tomllib"})
            prompt = bodies[0]["messages"][1]["content"]
            self.assertIn("Nuevo en la versión 3.11.", prompt)       # leyó la página
            self.assertIn("tomllib en la stdlib", prompt)            # la caída se sustituye por el resumen del buscador
            log = read_log(Path(tmp) / "log.jsonl")[0]
            self.assertEqual((log["tool"], log["ok"], len(log["sources"])), ("local_research", True, 2))

    def test_research_without_results_tells_claude_to_do_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Server({"LH_ROOT": tmp}, transport=lambda b: reply("x"), http_get=lambda u, d: "<html></html>")
            r = call(s, "local_research", {"question": "algo"})
            self.assertTrue(r["result"]["isError"])
            self.assertIn("hazlo tú", r["result"]["content"][0]["text"])
            off = Server({"LH_ROOT": tmp, "LH_WEB": "0"}, transport=lambda b: reply("x"))
            self.assertNotIn("local_research", [t["name"] for t in off.tools()])


class EndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def test_claude_delegates_a_file_to_the_local_model(self):
        """CLI falsa → lanza nuestro servidor MCP → llama-server falso escribe el archivo en el worktree."""
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlama)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        old_key, llama.API_KEY = llama.API_KEY, "clave-de-prueba"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repo = make_repo(tmp)
                store = Store()
                settings.save(store, {"local_base_url": f"http://127.0.0.1:{httpd.server_port}"})
                p = store.add_project("demo", str(repo))
                ag = store.add_agent("sonnet", "claude", config={"delegate_local": True})
                t = store.add_task(p["id"], "delegar", "DELEGA el saludo", ag["id"])
                res = await execute_task(store, t["id"], binaries={"claude": FAKE},
                                         worktree_root=str(Path(tmp) / "wt"))
                self.assertEqual(res["status"], "review")
                self.assertIn("delegado.txt", res["diff"]); self.assertIn("hola desde el modelo local", res["diff"])
                self.assertIn("local_ask,local_edit_file,local_write_file", res["final"])
                kinds = [e["kind"] for e in store.list_events(t["id"])]
                self.assertIn("delegate", kinds); self.assertIn("delegate_summary", kinds)
                summary = next(e for e in store.list_events(t["id"]) if e["kind"] == "delegate_summary")
                self.assertEqual(json.loads(summary["data"])["local_tokens"], 150)
                self.assertEqual(FakeLlama.auth[-1], "Bearer clave-de-prueba")
        finally:
            llama.API_KEY = old_key
            httpd.shutdown()

    async def test_coordinator_plans_and_the_local_model_writes_everything(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlama)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repo = make_repo(tmp)
                store = Store()
                settings.save(store, {"local_base_url": f"http://127.0.0.1:{httpd.server_port}"})
                p = store.add_project("demo", str(repo))
                ag = store.add_agent("coord", "claude", config={"coordinator": True})  # sin marcar delegate_local
                t = store.add_task(p["id"], "coordinar", "COORDINA los cambios", ag["id"])
                res = await execute_task(store, t["id"], binaries={"claude": FAKE},
                                         worktree_root=str(Path(tmp) / "wt"))
                self.assertEqual(res["status"], "review")
                self.assertIn("a.txt", res["diff"]); self.assertIn("b.txt", res["diff"])
                self.assertIn("local_execute_plan", res["final"])
                self.assertIn("Integradas: Read,Glob,Grep.", res["final"])  # sin Edit/Write: no lo hace él
                self.assertIn("Coordinador: True", res["final"])
                evs = store.list_events(t["id"])
                summary = next(e for e in evs if e["kind"] == "delegate_summary")
                self.assertEqual(json.loads(summary["data"])["calls"], 3)  # los bloques, no el plan ni local_prepare
                worker = next(e for e in evs if e["kind"] == "worker")  # Claude equipó al trabajador local
                self.assertEqual((json.loads(worker["data"])["skills"], json.loads(worker["data"])["by"]),
                                 (["cambios-minimos"], "Claude"))
                block = next(json.loads(e["data"]) for e in evs if e["kind"] == "delegate"
                             and json.loads(e["data"]).get("block") == "1")
                self.assertIn("un saludo", block["request"])  # su chat: lo que se le pidió y lo que contestó
                self.assertEqual((block["answer"], block["skills"]), ("```\nhola desde el modelo local\n```",
                                                                      ["cambios-minimos"]))
        finally:
            httpd.shutdown()

    async def test_without_option_no_mcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            store = Store()
            p = store.add_project("demo", str(repo))
            ag = store.add_agent("sonnet", "claude")
            t = store.add_task(p["id"], "x", "DELEGA el saludo", ag["id"])
            res = await execute_task(store, t["id"], binaries={"claude": FAKE}, worktree_root=str(Path(tmp) / "wt"))
            self.assertNotIn("delegado.txt", res["diff"])  # sin la casilla, Claude no tiene la herramienta




def tool_call(name: str, args: dict, i: int = 0) -> dict:
    return {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]},
        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 50, "completion_tokens": 10}}


class LocalAgentToolTests(unittest.TestCase):
    """`local_agent`: Claude encarga una tarea entera al agente local con herramientas, en el mismo worktree."""

    def test_agent_does_the_work_and_reports_changed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            script = [tool_call("leer_archivo", {"ruta": "README.md"}, 0),
                      tool_call("escribir_archivo", {"ruta": "suma.py", "contenido": "def suma(a, b):\n    return a + b\n"}, 1),
                      tool_call("terminar", {"resumen": "Creada suma()", "comprobacion": "leído"}, 2)]
            bodies = []

            def llm(body):
                bodies.append(body)
                return script[len(bodies) - 1]
            s = Server({"LH_ROOT": str(repo), "LH_LOG": str(Path(tmp) / "log.jsonl"), "LH_WRITE": "1"}, transport=llm)
            r = call(s, "local_agent", {"task": "crea suma.py", "files": ["README.md"]})["result"]
            text = r["content"][0]["text"]
            self.assertFalse(r.get("isError"), text)
            self.assertIn("Creada suma()", text)
            self.assertIn("Archivos que cambió: suma.py", text)
            self.assertTrue((repo / "suma.py").is_file())
            self.assertIn("Empieza leyendo: README.md", bodies[0]["messages"][1]["content"])
            log = read_log(Path(tmp) / "log.jsonl")
            self.assertEqual([e["text"].split()[0] for e in log if e.get("progress")], ["leer_archivo", "escribir_archivo"])
            final = [e for e in log if not e.get("progress")][-1]
            self.assertEqual((final["tool"], final["files"], final["ok"]), ("local_agent", ["suma.py"], True))

    def test_agent_without_llama_tells_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Server({"LH_ROOT": tmp, "LH_LOCAL_URL": "http://127.0.0.1:9", "LH_WRITE": "1"})
            r = call(s, "local_agent", {"task": "x"})["result"]
            self.assertTrue(r["isError"])
            self.assertIn("llama-server", r["content"][0]["text"])

    def test_read_only_has_no_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            names = [x["name"] for x in server(tmp, write=False).tools()]
            self.assertNotIn("local_agent", names)
            self.assertIn("run_checks", names)

    def test_run_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Server({"LH_ROOT": tmp, "LH_COMMANDS": json.dumps(["python -c"])})
            out = call(s, "run_checks", {"command": "python -c \"print('tests ok')\""})["result"]["content"][0]["text"]
            self.assertIn("código de salida 0", out); self.assertIn("tests ok", out)
            bad = call(s, "run_checks", {"command": "rm -rf /"})["result"]
            self.assertTrue(bad["isError"]); self.assertIn("no permitida", bad["content"][0]["text"])
            off = Server({"LH_ROOT": tmp, "LH_COMMANDS": "[]"})
            self.assertNotIn("run_checks", [x["name"] for x in off.tools()])


class BossModeTests(unittest.IsolatedAsyncioTestCase):
    """Modo jefe: Claude sin Edit/Write (solo puede cambiar archivos delegando) y la guía en el prompt de sistema."""

    async def run_task(self, cfg: dict, prompt: str, llama_url: str | None):
        d = tempfile.TemporaryDirectory()  # enterContext es de 3.11: se soporta 3.10
        self.addCleanup(d.cleanup)
        tmp = d.name
        repo = make_repo(tmp)
        store = Store()
        if llama_url:
            settings.save(store, {"local_base_url": llama_url})
        else:
            settings.save(store, {"local_base_url": "http://127.0.0.1:9"})
        p = store.add_project("demo", str(repo))
        ag = store.add_agent("sonnet", "claude", config=cfg)
        t = store.add_task(p["id"], "x", prompt, ag["id"])
        res = await execute_task(store, t["id"], binaries={"claude": FAKE}, worktree_root=str(Path(tmp) / "wt"))
        return res, store.list_events(t["id"])

    async def test_boss_mode(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeLlama)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        res, events = await self.run_task({"coordinator": True}, "DELEGA el saludo",
                                          f"http://127.0.0.1:{httpd.server_port}")
        session = json.loads(next(e for e in events if e["kind"] == "session")["data"])
        self.assertEqual(session["tools"], ["Read", "Glob", "Grep"])  # sin Edit ni Write: tiene que delegar
        self.assertIn("delegado.txt", res["diff"])
        self.assertIn("Modo coordinador", " ".join(e["text"] or "" for e in events if e["kind"] == "progress"))

    async def test_boss_mode_without_local_model_falls_back(self):
        res, events = await self.run_task({"coordinator": True}, "crea el archivo a.txt",
                                          None)
        session = json.loads(next(e for e in events if e["kind"] == "session")["data"])
        self.assertIn("Write", session["tools"])
        warnings = " ".join(e["text"] for e in events if e["kind"] == "warning")
        self.assertIn("Claude trabaja solo", warnings)

    def test_guide_goes_to_system_prompt(self):
        cmd = get_adapter("claude").build_command(RunSpec(prompt="x", cwd=".", system_append="REGLAS"))
        self.assertEqual(cmd[cmd.index("--append-system-prompt") + 1], "REGLAS")
        from localharness.orchestrator import delegate_guide
        self.assertIn("local_agent", delegate_guide(True, coordinator=True))
        self.assertIn("No tienes Edit, Write ni Bash", delegate_guide(True, coordinator=True))
        self.assertNotIn("local_agent", delegate_guide(False, coordinator=True))  # solo lectura: no encarga cambios


if __name__ == "__main__":
    unittest.main()


class ScriptedLlama(BaseHTTPRequestHandler):
    """llama-server falso con guion: responde a /health y a /v1/models, y en el chat sigue `script` en orden."""
    script: list = []

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"status": "ok"} if self.path == "/health" else {"data": [{"id": "Qwen3-8B.gguf"}]})

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self._send(ScriptedLlama.script.pop(0))

    def log_message(self, *a):
        pass


class DelegationTestCommandTests(unittest.TestCase):
    def test_probar_delegacion(self):
        """`localharness probar-delegacion`: el modelo local contesta, arregla calc.py y el test pasa."""
        import contextlib, io
        from localharness.cli import main
        ScriptedLlama.script = [
            reply("Resta en vez de sumar."),
            tool_call("escribir_archivo", {"ruta": "calc.py", "contenido": "def suma(a, b):\n    return a + b\n"}, 0),
            tool_call("ejecutar", {"comando": "python -m unittest"}, 1),
            tool_call("terminar", {"resumen": "Arreglada suma", "comprobacion": "tests en verde"}, 2),
        ]
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedLlama)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "lh.db")
            s = Store(db); settings.save(s, {"local_base_url": f"http://127.0.0.1:{httpd.server_port}"}); s.close()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--db", db, "probar-delegacion"])
        text = out.getvalue()
        self.assertEqual(code, 0, text)
        self.assertIn("Archivos que cambió: calc.py", text)
        self.assertIn("✔ el modelo local recibe encargos", text)
