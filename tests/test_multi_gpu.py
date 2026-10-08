"""Dos GPU, dos modelos: servidores locales en Ajustes, numeración de llama.cpp y reparto de encargos."""

import json
import socket
import tempfile
import threading
import time
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from localharness import hardware, llama, settings
from localharness.mcp_local import Server, read_log
from localharness.store import Store

try:
    from fastapi.testclient import TestClient

    from localharness.api import create_app, suggest_servers
except ImportError:  # sin el extra [server]
    TestClient = None

LIST_DEVICES = """ggml_cuda_init: found 2 CUDA devices:
Available devices:
  CUDA0: NVIDIA GeForce RTX 3060 (12287 MiB, 11245 MiB free)
  CUDA1: NVIDIA GeForce GTX 1060 6GB (6143 MiB, 5199 MiB free)
"""
DEVICES = llama.parse_devices(LIST_DEVICES)


def fake_llama(model: str, seen: list, delay: float = 0) -> ThreadingHTTPServer:
    """Un llama-server de mentira que contesta sin streaming y apunta qué le piden."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"data": [{"id": model}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            time.sleep(delay)
            body = json.dumps({"model": model, "choices": [{"message": {"content": f"hecho por {model}"},
                                                            "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 3}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(s: Server, name: str, args: dict) -> dict:
    return s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})


class DevicesTests(unittest.TestCase):
    def test_list_devices_is_llama_cpp_numbering(self):
        self.assertEqual([(d["id"], d["name"], d["total_mb"]) for d in DEVICES],
                         [("CUDA0", "NVIDIA GeForce RTX 3060", 12287), ("CUDA1", "NVIDIA GeForce GTX 1060 6GB", 6143)])

    def test_device_budget(self):
        base = {"gpu": "NVIDIA GeForce RTX 3060", "vram_gb": 12.0, "usable_vram_gb": 11.3, "bandwidth_gbs": 360,
                "manual": False}
        small = hardware.device_budget(base, DEVICES, "CUDA1")
        self.assertAlmostEqual(small["vram_gb"], 6.0, places=1)
        self.assertLess(small["bandwidth_gbs"], 360)
        both = hardware.device_budget(base, DEVICES, "CUDA0,CUDA1")
        self.assertAlmostEqual(both["vram_gb"], 18.0, places=1)
        self.assertEqual(both["bandwidth_gbs"], small["bandwidth_gbs"])  # manda la más lenta
        self.assertIs(hardware.device_budget(base, DEVICES, None), base)
        self.assertIs(hardware.device_budget({**base, "manual": True}, DEVICES, "CUDA1")["manual"], True)

    def test_device_and_split_options(self):
        self.assertEqual(llama.option_args({"device": "CUDA0,CUDA1", "tensor_split": "2,1", "split_mode": "layer"}),
                         ["-dev", "CUDA0,CUDA1", "-sm", "layer", "-ts", "2,1"])

    def test_placement_from_real_log_with_lv4(self):
        """Log real de llama.cpp b11379 con -lv 4 (el 4B en la GTX 1060): dónde está cargado."""
        from localharness import usage
        log = """0.01.737.164 I load_tensors: offloaded 34/34 layers to GPU
0.01.737.172 I load_tensors:   CPU_Mapped model buffer size =   497.31 MiB
0.01.737.173 I load_tensors:        CUDA1 model buffer size =  2740.75 MiB
0.03.970.573 I llama_context:  CUDA_Host  output buffer size =     3.79 MiB
0.03.971.157 I llama_kv_cache:      CUDA1 KV buffer size =   128.00 MiB
0.03.994.960 I sched_reserve:      CUDA1 compute buffer size =    68.02 MiB
"""
        p = usage.placement(log)
        self.assertEqual((p["layers_gpu"], p["layers_total"]), (34, 34))
        self.assertEqual({d["device"] for d in p["devices"] if d["gpu"]}, {"CUDA1"})
        self.assertGreater(p["gpu_mb"], 2900)

    def test_serve_command_asks_for_verbose_log(self):
        with unittest.mock.patch.object(llama, "server_binary", return_value="llama-server"):
            cmd = llama.serve_command(Path("m.gguf"), 8081, 4096, 99, ["-dev", "CUDA1"])
            self.assertEqual(cmd[cmd.index("-lv") + 1], "4")
            mine = llama.serve_command(Path("m.gguf"), 8081, 4096, 99, ["-lv", "2"])
            self.assertEqual(mine.count("-lv"), 1)

    def test_keys_by_port(self):
        self.assertEqual(llama.port_of("http://127.0.0.1:8081/v1"), 8081)
        with unittest.mock.patch.dict(llama.KEYS, {8081: "k2"}, clear=True):
            self.assertEqual(llama.key_for_url("http://127.0.0.1:8081"), "k2")


class ServersSettingsTests(unittest.TestCase):
    def test_default_is_one_principal_server(self):
        store = Store(":memory:")
        self.assertEqual(settings.local_servers(store), [{"id": "principal", "name": "Principal", "port": 8080,
                                                          "device": "", "role": "general", "thinking": "normal"}])

    def test_two_servers_and_validation(self):
        store = Store(":memory:")
        two = [{"id": "principal", "name": "Fuerte", "port": 8080, "device": "CUDA0", "role": "fuerte"},
               {"id": "rapido", "name": "Rápido", "port": 8081, "device": "CUDA1", "role": "rapido"}]
        settings.save(store, {"llama": {"servers": two}})
        self.assertEqual([s["id"] for s in settings.local_servers(store)], ["principal", "rapido"])
        # el puerto del principal y llama.port son lo mismo, se cambie por donde se cambie
        settings.save(store, {"llama": {"port": 9090}})
        self.assertEqual(settings.local_servers(store)[0]["port"], 9090)
        settings.save(store, {"llama": {"servers": [{**two[0], "port": 8070}, two[1]]}})
        self.assertEqual(settings.load(store)["llama"]["port"], 8070)
        for bad in ([two[0], {**two[1], "port": 8080}],              # mismo puerto
                    [two[0], {**two[1], "id": "principal"}],          # mismo id
                    [two[0], {**two[1], "device": "CUDA1; rm -rf"}],  # dispositivo raro
                    [two[0], {**two[1], "id": "Con Espacios"}]):
            with self.assertRaises(ValueError):
                settings.save(store, {"llama": {"servers": bad}})
        # sin principal en la lista: se añade solo, el primero
        settings.save(store, {"llama": {"servers": [two[1]]}})
        self.assertEqual([s["id"] for s in settings.local_servers(store)], ["principal", "rapido"])

    @unittest.skipIf(TestClient is None, "falta fastapi (pip install -e .[server])")
    def test_suggest_one_server_per_gpu(self):
        sug = suggest_servers(DEVICES, [])
        self.assertEqual([(s["id"], s["device"], s["role"], s["port"], s["thinking"]) for s in sug],
                         [("principal", "CUDA0", "fuerte", 8080, "normal"), ("rapido", "CUDA1", "rapido", 8081, "apagado")])
        self.assertIsNone(suggest_servers(DEVICES[:1], []))
        self.assertIsNone(suggest_servers(DEVICES, sug))  # ya configurado


@unittest.skipIf(TestClient is None, "falta fastapi (pip install -e .[server])")
class ServersApiTests(unittest.TestCase):
    def test_start_on_each_server_with_its_gpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            gguf = Path(tmp) / "Qwen3.5-4B-Q4_K_M.gguf"
            gguf.write_bytes(b"GGUF")
            p1, p2 = free_port(), free_port()
            with TestClient(create_app(Path(tmp) / "lh.db", web_dist=None)) as c, \
                    unittest.mock.patch.object(llama, "list_devices", return_value=DEVICES):
                r = c.put("/api/settings", json={"llama": {"servers": [
                    {"id": "principal", "name": "Fuerte", "port": p1, "device": "CUDA0", "role": "fuerte"},
                    {"id": "rapido", "name": "Rápido", "port": p2, "device": "CUDA1", "role": "rapido"}]}})
                self.assertEqual(r.status_code, 200, r.text)
                info = c.get("/api/llama").json()
                self.assertEqual([(s["id"], s["status"]["state"]) for s in info["servers"]],
                                 [("principal", "off"), ("rapido", "off")])
                self.assertEqual(info["devices"][1]["id"], "CUDA1")
                self.assertIsNone(info["suggested_servers"])
                with unittest.mock.patch.object(llama.LlamaManager, "start") as start:
                    r = c.post("/api/llama/start", json={"path": str(gguf), "server": "rapido"})
                self.assertEqual(r.status_code, 200, r.text)
                model, port, _ctx, _ngl, extra = start.call_args.args
                self.assertEqual((port, extra[:2]), (p2, ["-dev", "CUDA1"]))
                cfg = c.get("/api/settings").json()["values"]["llama"]
                self.assertEqual(cfg["last_by_server"]["rapido"]["model"], str(gguf))
                self.assertEqual(cfg["last"], {})  # el principal no se tocó
                self.assertEqual(c.post("/api/llama/start", json={"path": str(gguf), "server": "otro"}).status_code,
                                 404)
                self.assertEqual(c.post("/api/llama/stop?server=rapido").json()["state"], "off")
                # la estimación usa la memoria de la GPU de ese servidor
                e = c.post("/api/llama/estimate", json={"path": str(gguf), "server": "rapido"}).json()
                self.assertAlmostEqual(e["budget"]["vram_gb"], 6.0, places=1)
                self.assertIn("-dev", e["command"] or ["-dev"])
                h = c.get("/api/health").json()
                self.assertEqual([x["id"] for x in h["locals"]], ["principal", "rapido"])


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.seen_big, self.seen_small = [], []
        self.big = fake_llama("Qwen3.5-9B-Q4_K_M.gguf", self.seen_big)
        self.small = fake_llama("Qwen3.5-4B-Q4_K_M.gguf", self.seen_small)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        for h in (self.big, self.small):
            h.shutdown()
            h.server_close()
        self.tmp.cleanup()

    def server(self, servers: list[dict]) -> Server:
        return Server({"LH_ROOT": self.tmp.name, "LH_LOG": str(Path(self.tmp.name) / "log.jsonl"),
                       "LH_LOCAL_SERVERS": json.dumps(servers)})

    def endpoints(self, small_url: str | None = None) -> list[dict]:
        return [{"id": "principal", "name": "Fuerte", "role": "fuerte", "device": "CUDA0",
                 "url": f"http://127.0.0.1:{self.big.server_port}", "key": ""},
                {"id": "rapido", "name": "Rápido", "role": "rapido", "device": "CUDA1",
                 "url": small_url or f"http://127.0.0.1:{self.small.server_port}", "key": ""}]

    def test_each_job_goes_to_the_model_of_its_role(self):
        s = self.server(self.endpoints())
        self.assertIn("hecho por Qwen3.5-4B", call(s, "local_ask", {"task": "¿qué hace esto?"})["result"]["content"][0]["text"])
        call(s, "local_write_file", {"path": "a.py", "instructions": "x = 1"})
        self.assertEqual((len(self.seen_small), len(self.seen_big)), (1, 1))
        # Claude puede elegir otro
        call(s, "local_ask", {"task": "piensa a fondo", "server": "principal"})
        self.assertEqual(len(self.seen_big), 2)
        log = read_log(Path(self.tmp.name) / "log.jsonl")
        self.assertEqual([e.get("server") for e in log], ["rapido", "principal", "principal"])
        r = call(s, "local_ask", {"task": "x", "server": "no-existe"})["result"]
        self.assertTrue(r["isError"])

    def test_plan_blocks_split_between_models(self):
        s = self.server(self.endpoints())
        call(s, "local_execute_plan", {"blocks": [{"kind": "ask", "instructions": "explica"},
                                                  {"kind": "write", "path": "b.py", "instructions": "y = 2"},
                                                  {"kind": "ask", "instructions": "otra", "server": "principal"}]})
        self.assertEqual((len(self.seen_small), len(self.seen_big)), (1, 2))

    def test_falls_back_when_one_is_off(self):
        s = self.server(self.endpoints(small_url=f"http://127.0.0.1:{free_port()}"))  # el rápido, apagado
        text = call(s, "local_ask", {"task": "hola"})["result"]["content"][0]["text"]
        self.assertIn("Qwen3.5-9B", text)
        self.assertEqual(read_log(Path(self.tmp.name) / "log.jsonl")[0]["server"], "principal")

    def test_two_models_work_at_the_same_time(self):
        """Claude pide dos encargos a la vez (uno a cada modelo): cada tools/call va en su hilo y no se esperan."""
        slow = [fake_llama("Qwen3.5-9B.gguf", [], delay=1.0), fake_llama("Qwen3.5-4B.gguf", [], delay=1.0)]
        try:
            eps = self.endpoints()
            eps[0]["url"], eps[1]["url"] = (f"http://127.0.0.1:{h.server_port}" for h in slow)
            s = self.server(eps)
            got = {}

            def job(server_id):
                got[server_id] = call(s, "local_ask", {"task": "x", "server": server_id})["result"]["content"][0]["text"]
            t0 = time.monotonic()
            threads = [threading.Thread(target=job, args=(i,)) for i in ("principal", "rapido")]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertLess(time.monotonic() - t0, 1.8)  # en serie serían más de 2 s
            self.assertIn("9B", got["principal"])
            self.assertIn("4B", got["rapido"])  # cada hilo con su servidor, sin pisarse
            self.assertEqual(sorted(e["server"] for e in read_log(Path(self.tmp.name) / "log.jsonl")),
                             ["principal", "rapido"])
        finally:
            for h in slow:
                h.shutdown()
                h.server_close()

    def test_plan_runs_independent_blocks_at_the_same_time(self):
        """Con `after`, los bloques que no dependen entre sí van a la vez (cada uno a su modelo)."""
        slow = [fake_llama("Qwen3.5-9B.gguf", [], delay=0.8), fake_llama("Qwen3.5-4B.gguf", [], delay=0.8)]
        try:
            eps = self.endpoints()
            eps[0]["url"], eps[1]["url"] = (f"http://127.0.0.1:{h.server_port}" for h in slow)
            s = self.server(eps)
            t0 = time.monotonic()
            r = call(s, "local_execute_plan", {"blocks": [
                {"id": "a", "kind": "write", "path": "a.py", "instructions": "x", "after": []},
                {"id": "b", "kind": "write", "path": "b.py", "instructions": "y", "after": []},
                {"id": "c", "kind": "ask", "instructions": "¿qué falta?", "after": []},
                {"id": "d", "kind": "ask", "instructions": "revisa a y b", "after": ["a", "b"]}]})["result"]
            took = time.monotonic() - t0
            text = r["content"][0]["text"]
            self.assertIn("4 de 4 bloques bien", text)
            self.assertIn("a la vez", text)
            self.assertLess(took, 2.6)  # a, b y c juntos (~0,8 s) y luego d (~0,8 s); en serie, más de 3,2 s
            log = read_log(Path(self.tmp.name) / "log.jsonl")
            ends = {e["block"]: e["at"] + e["seconds"] for e in log if e.get("block")}
            starts = {e["block"]: e["at"] for e in log if e.get("block")}
            self.assertGreaterEqual(starts["d"], max(ends["a"], ends["b"]) - 0.05)  # d esperó a a y b
            by = {e["block"]: e["server"] for e in log if e.get("block")}
            self.assertNotEqual(by["a"], by["b"])  # los dos write a la vez: uno a cada modelo, no en cola en el fuerte
        finally:
            for h in slow:
                h.shutdown()
                h.server_close()

    def test_busy_model_hands_the_job_to_the_free_one(self):
        """Aunque Claude pida el rápido para todo, con el rápido ocupado el bloque va al fuerte libre."""
        s = self.server(self.endpoints())
        self.assertEqual(s.claim("local_execute_plan/write", "rapido")[0]["id"], "rapido")
        self.assertEqual(s.claim("local_execute_plan/write", "rapido")[0]["id"], "principal")
        s.release("rapido")
        s.release("principal")
        self.assertEqual(s.claim("local_ask")[0]["id"], "rapido")  # libres los dos: manda el papel

    def test_plan_dependencies_of_a_failed_block_are_skipped(self):
        s = self.server(self.endpoints())
        text = call(s, "local_execute_plan", {"blocks": [
            {"id": "1", "kind": "write", "path": "../fuera.py", "instructions": "x", "after": []},
            {"id": "2", "kind": "ask", "instructions": "usa lo de 1", "after": ["1"]},
            {"id": "3", "kind": "ask", "instructions": "independiente", "after": []}]})["result"]["content"][0]["text"]
        self.assertIn("1 de 3 bloques bien", text)
        self.assertIn("No se hizo: depende de 1, que falló", text)
        bad = call(s, "local_execute_plan", {"blocks": [{"id": "1", "instructions": "x", "after": ["2"]},
                                                        {"id": "2", "instructions": "y"}]})["result"]
        self.assertTrue(bad["isError"])  # solo se puede depender de bloques anteriores (sin ciclos)

    def test_thinking_off_on_the_fast_server_only(self):
        eps = self.endpoints()
        eps[1]["thinking"] = "apagado"
        s = self.server(eps)
        call(s, "local_ask", {"task": "rápido"})
        call(s, "local_write_file", {"path": "c.py", "instructions": "z = 3"})
        self.assertEqual(self.seen_small[0]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("chat_template_kwargs", self.seen_big[0])

    def test_tools_offer_server_choice_only_with_several(self):
        one = Server({"LH_ROOT": self.tmp.name, "LH_LOCAL_URL": f"http://127.0.0.1:{self.big.server_port}"})
        ask = next(t for t in one.tools() if t["name"] == "local_ask")
        self.assertNotIn("server", ask["inputSchema"]["properties"])
        two = self.server(self.endpoints())
        tools = {t["name"]: t for t in two.tools()}
        self.assertEqual(tools["local_ask"]["inputSchema"]["properties"]["server"]["enum"], ["principal", "rapido"])
        self.assertIn("Qwen3.5-4B", tools["local_ask"]["description"])
        self.assertIn("server", tools["local_execute_plan"]["inputSchema"]["properties"]["blocks"]["items"]["properties"])
        self.assertNotIn("server", tools["run_checks"]["inputSchema"]["properties"])




class AutostartOnTaskTests(unittest.TestCase):
    def test_starts_the_off_servers_with_their_last_model_and_waits(self):
        from localharness import local_servers
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(":memory:")
            gguf = Path(tmp) / "Qwen3.5-4B.gguf"
            gguf.write_bytes(b"GGUF")
            p1, p2 = free_port(), free_port()
            settings.save(store, {"llama": {"servers": [
                {"id": "principal", "name": "Fuerte", "port": p1, "device": "CUDA0", "role": "fuerte"},
                {"id": "rapido", "name": "Rápido", "port": p2, "device": "CUDA1", "role": "rapido"}],
                "last_by_server": {"rapido": {"model": str(gguf), "options": {"ctx": 4096}}}}})
            pool = llama.LlamaPool(Path(tmp) / "llama-server.log")
            said: list[str] = []
            old = llama.POOL
            llama.POOL = pool
            try:
                with unittest.mock.patch.object(llama.LlamaManager, "start") as start,                         unittest.mock.patch.object(llama.LlamaManager, "status", return_value={"state": "ready"}):
                    names = local_servers.ensure_for_task(store, None, 5, said.append)
                self.assertEqual(names, ["Rápido"])  # el principal no tiene último modelo: no se toca
                model, port, ctx, _ngl, extra = start.call_args.args
                self.assertEqual((port, ctx, extra[:2]), (p2, 4096, ["-dev", "CUDA1"]))
                self.assertIn("Arrancando Qwen3.5-4B en Rápido", said[0])
                settings.save(store, {"llama": {"autostart_on_task": False}})
                with unittest.mock.patch.object(llama.LlamaManager, "start") as start:
                    self.assertEqual(local_servers.ensure_for_task(store, None, 5, said.append), [])
                start.assert_not_called()
            finally:
                llama.POOL = old


if __name__ == "__main__":
    unittest.main()
