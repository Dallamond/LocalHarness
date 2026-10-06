"""Claude delega en el modelo local: servidor MCP (localharness.mcp_local) y su cableado en la tarea."""

import json, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from localharness import llama, settings
from localharness.adapters import get_adapter
from localharness.adapters.base import RunSpec
from localharness.mcp_local import Server, read_log, strip_fence
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
            self.assertEqual(names, ["local_ask", "local_write_file"])
            ro = server(tmp, write=False).handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            self.assertEqual([t["name"] for t in ro["result"]["tools"]], ["local_ask"])  # Director / jefe: solo pensar
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
                self.assertIn("local_ask,local_write_file", res["final"])
                kinds = [e["kind"] for e in store.list_events(t["id"])]
                self.assertIn("delegate", kinds); self.assertIn("delegate_summary", kinds)
                summary = next(e for e in store.list_events(t["id"]) if e["kind"] == "delegate_summary")
                self.assertEqual(json.loads(summary["data"])["local_tokens"], 150)
                self.assertEqual(FakeLlama.auth[-1], "Bearer clave-de-prueba")
        finally:
            llama.API_KEY = old_key
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


if __name__ == "__main__":
    unittest.main()
