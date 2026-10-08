"""Armario de modelos (perfiles), cambio en caliente, GPU unidas, banco de pruebas, planificador local, documentos,
revisión visual y RAG (docs/PLAN-MODELOS-LOCALES.md). Sin GPU ni llama-server: todo con dobles."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from localharness import bench, local_servers, profiles, rag, settings
from localharness.mcp_local import Server, validate_plan
from localharness.store import Store


def reply(text: str) -> dict:
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "qwen.gguf"}


def call(s: Server, name: str, args: dict) -> dict:
    return s.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": args}})


class CapsTests(unittest.TestCase):
    def test_caps_from_name_meta_and_mmproj(self):
        coder = profiles.auto_caps("Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf",
                                   {"params_b": 14.8, "tools_in_template": True}, 9.0, None, False)
        self.assertEqual(coder, ["code", "review", "tools"])
        small = profiles.auto_caps("Qwen3.5-4B-Q4_K_M.gguf", {"params_b": 4, "thinking": True,
                                                              "tools_in_template": True}, 2.7, None, True)
        for c in ("vision", "ocr", "fast", "thinking", "tools"):
            self.assertIn(c, small)
        self.assertNotIn("plan", small)  # razona, pero 4B es poco para planificar
        self.assertIn("plan", profiles.auto_caps("gpt-oss-20b-MXFP4.gguf", {"params_b": 21, "thinking": True},
                                                  12.1, None, False))
        self.assertIn("draft", profiles.auto_caps("Qwen2.5-Coder-0.5B-Q8_0.gguf", {"params_b": 0.5}, 0.5, None, False))
        self.assertEqual(profiles.auto_caps("Qwen3-Embedding-0.6B-Q8_0.gguf", {}, 0.6, None, False), ["embed"])

    def test_mmproj_is_the_closest_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "Qwen3.5-4B-Q4_K_M.gguf"
            m.write_bytes(b"x")
            (Path(d) / "mmproj-Qwen3.5-9B-F16.gguf").write_bytes(b"x")
            (Path(d) / "mmproj-Qwen3.5-4B-F16.gguf").write_bytes(b"x")
            self.assertEqual(profiles.mmproj_for(m).name, "mmproj-Qwen3.5-4B-F16.gguf")

    def test_draft_needs_the_same_tokenizer(self):
        with mock.patch.object(profiles, "tokenizer_of", side_effect=[("gpt2", 152064), ("gpt2", 151936)]):
            self.assertIsNone(profiles.draft_problem(Path("a"), Path("b")))
        with mock.patch.object(profiles, "tokenizer_of", side_effect=[("gpt2", 151936), ("llama", 32000)]):
            self.assertIn("tokenizadores distintos", profiles.draft_problem(Path("a"), Path("b")))

    def test_launch_extra_brings_mmproj_and_draft(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(":memory:")
            main, draft, proj = (Path(d) / n for n in ("main.gguf", "draft.gguf", "mmproj.gguf"))
            for p in (main, draft, proj):
                p.write_bytes(b"x")
            settings.save(store, {"llama": {"profiles": {str(main): {
                "mmproj": str(proj), "draft": {"model": str(draft), "ngl": 99, "device": "CUDA1", "max": 16}}}}})
            extra = settings.llama_launch(store, str(main))["extra"]
            self.assertEqual(extra[:2], ["--mmproj", str(proj)])
            self.assertIn("-md", extra)
            self.assertEqual(extra[extra.index("-devd") + 1], "CUDA1")
            self.assertEqual(extra[extra.index("--draft-max") + 1], "16")

    def test_pick_prefers_what_is_loaded_then_what_fits(self):
        profs = [{"path": "/m/coder14.gguf", "name": "coder14", "size_gb": 9, "caps": ["code"],
                  "fits": {"CUDA0": {"fit": "gpu"}, "CUDA1": {"fit": "no"}}},
                 {"path": "/m/vl4b.gguf", "name": "vl4b", "size_gb": 3, "caps": ["vision", "fast"],
                  "fits": {"CUDA0": {"fit": "gpu"}, "CUDA1": {"fit": "gpu"}}},
                 {"path": "/m/vl9b.gguf", "name": "vl9b", "size_gb": 6, "caps": ["vision"],
                  "fits": {"CUDA0": {"fit": "gpu"}, "CUDA1": {"fit": "no"}}}]
        servers = [{"id": "principal", "device": "CUDA0", "status": {"model": "/m/coder14.gguf"}},
                   {"id": "rapido", "device": "CUDA1", "status": {"model": "/m/otro.gguf"}}]
        p, s = profiles.pick("code", profs, servers)
        self.assertEqual((p["name"], s["id"]), ("coder14", "principal"))  # ya cargado: sin cambiar nada
        p, s = profiles.pick("vision", profs, servers)
        self.assertEqual(p["name"], "vl9b")  # el más capaz que cabe entero (en la 3060)
        p, s = profiles.pick("vision", profs, servers[1:])
        self.assertEqual((p["name"], s["id"]), ("vl4b", "rapido"))  # en la 1060 solo cabe el pequeño
        self.assertIsNone(profiles.pick("embed", profs, servers))


class FakeMgr:
    def __init__(self, fail=()):
        self.model, self.state, self.fail, self.started = None, "off", set(fail), []

    def start(self, model, port, ctx, ngl, extra=None):
        self.model, self.extra = str(model), extra
        self.started.append(Path(model).name)
        self.state = "failed" if Path(model).name in self.fail else "ready"

    def stop(self):
        self.state = "off"

    def status(self, port):
        return {"state": self.state, "model": self.model}


class FakePool:
    def __init__(self, fail=()):
        self.mgrs: dict[str, FakeMgr] = {}
        self.fail = fail

    def get(self, sid, port=None):
        return self.mgrs.setdefault(sid, FakeMgr(self.fail))


class SwapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.a, self.b, self.big = d / "a.gguf", d / "b.gguf", d / "big.gguf"
        for p in (self.a, self.b, self.big):
            p.write_bytes(b"x")
        self.store = Store(":memory:")
        settings.save(self.store, {"llama": {"servers": [
            {"id": "principal", "name": "Fuerte", "port": 8080, "device": "CUDA0", "role": "fuerte"},
            {"id": "rapido", "name": "Rápido", "port": 8081, "device": "CUDA1", "role": "rapido"}]}})
        self.srv = next(s for s in settings.local_servers(self.store) if s["id"] == "rapido")

    def tearDown(self):
        self.tmp.cleanup()

    def test_swap_waits_until_idle_and_remembers(self):
        pool = FakePool()
        busy = iter([True, True, False])
        with mock.patch.object(local_servers.time, "sleep"):
            st = local_servers.swap(self.store, pool, self.srv, self.b, busy=lambda _: next(busy))
        self.assertEqual(st["state"], "ready")
        self.assertEqual(local_servers.last_of(self.store, self.srv)["model"], str(self.b))
        self.assertIn("-dev", pool.get("rapido").extra)  # en su GPU

    def test_swap_goes_back_when_the_new_one_fails(self):
        pool = FakePool(fail={"b.gguf"})
        local_servers.remember(self.store, self.srv, self.a, {})
        with self.assertRaises(RuntimeError):
            local_servers.swap(self.store, pool, self.srv, self.b, busy=lambda _: False)
        self.assertEqual(pool.get("rapido").started, ["b.gguf", "a.gguf"])
        self.assertEqual(local_servers.last_of(self.store, self.srv)["model"], str(self.a))

    def test_topology_join_and_split(self):
        pool = FakePool()
        main = next(s for s in settings.local_servers(self.store) if s["id"] == "principal")
        local_servers.remember(self.store, main, self.a, {})
        local_servers.remember(self.store, self.srv, self.b, {})
        devices = [{"id": "CUDA0", "total_mb": 12288, "free_mb": 11500},
                   {"id": "CUDA1", "total_mb": 6144, "free_mb": 2900}]
        r = local_servers.set_topology(self.store, pool, "unido", self.big, devices)
        self.assertEqual(r["options"]["device"], "CUDA0,CUDA1")
        self.assertEqual(r["options"]["tensor_split"], "8,2")  # según la VRAM libre
        extra = pool.get("principal").extra
        self.assertEqual(extra[extra.index("-dev") + 1], "CUDA0,CUDA1")
        self.assertEqual(pool.get("rapido").state, "off")
        from localharness.orchestrator import local_endpoints
        from unittest import mock
        with mock.patch("localharness.orchestrator.llama_up", return_value=False):
            self.assertEqual([e["id"] for e in local_endpoints(self.store)], ["principal"])  # el MCP solo ve uno
        with mock.patch("localharness.orchestrator.llama_up", return_value=True):  # el pequeño sigue arrancado al lado
            # medido el 08/10: en este equipo comparte la 1060 con gpt-oss y los dos se arrastran → no, salvo ajuste
            self.assertEqual([e["id"] for e in local_endpoints(self.store)], ["principal"])
            settings.save(self.store, {"llama": {"joined_helpers": True}})
            self.assertEqual([e["id"] for e in local_endpoints(self.store)], ["principal", "rapido"])
        r = local_servers.set_topology(self.store, pool, "separado")
        self.assertEqual(r["started"], ["Fuerte", "Rápido"])
        self.assertEqual(pool.get("rapido").model, str(self.b))
        extra = pool.get("principal").extra
        self.assertEqual(extra[extra.index("-dev") + 1], "CUDA0")  # cada uno en su GPU otra vez
        self.assertEqual(len(local_endpoints(self.store)), 2)


class BenchTests(unittest.TestCase):
    def test_run_and_save(self):
        def post(url, body, key, timeout):
            self.assertTrue(url.endswith("/v1/chat/completions"))
            self.assertGreater(len(body["messages"][0]["content"]), 8000)
            return {"model": "q.gguf", "usage": {"prompt_tokens": 3900, "completion_tokens": 512},
                    "timings": {"prompt_per_second": 812.3, "predicted_per_second": 28.44, "draft_n": 100,
                                "draft_n_accepted": 71}}
        r = bench.run("http://x", None, post)
        self.assertEqual((r["read_tps"], r["write_tps"], r["draft_accept"]), (812.3, 28.4, 0.71))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bench.json"
            bench.save(path, "/m/q.gguf", "CUDA0", r)
            bench.save(path, "/m/q.gguf", "unido CUDA0,CUDA1", {**r, "write_tps": 19.0})
            rows = bench.load(path)
            self.assertEqual([x["topology"] for x in rows], ["CUDA0", "unido CUDA0,CUDA1"])  # el más rápido arriba
        self.assertEqual(bench.topology_of({"device": "CUDA0"}, {"device": "CUDA0,CUDA1", "draft": True}),
                         "unido CUDA0,CUDA1 + borrador")


class LocalPlanTests(unittest.TestCase):
    def test_plan_is_validated_retried_and_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "mapa.html").write_text("<li>uno</li>\n", encoding="utf-8")
            # un fallo que no tiene arreglo automático (editar lo que no existe ya se convierte en `write`)
            bad = {"blocks": [{"id": "1", "kind": "write", "path": "../fuera.html", "instructions": "x", "after": []}]}
            good = {"blocks": [
                {"id": "1", "kind": "edit", "path": "mapa.html", "instructions": "añade dos", "after": []},
                {"id": "2", "kind": "write", "path": "dos.html", "instructions": "página dos", "after": ["1"]}]}
            seen = []

            def fake(body):
                user = body["messages"][1]["content"]
                seen.append(body)
                if user.startswith("TAREA:"):
                    return reply(json.dumps(bad if len([b for b in seen if "TAREA:" in str(b)]) == 1 else good))
                if user.startswith("ARCHIVO A CAMBIAR"):
                    return reply("<<<<<<< BUSCAR\n<li>uno</li>\n=======\n<li>uno</li>\n<li>dos</li>\n>>>>>>> REEMPLAZAR")
                return reply("```html\n<h1>Dos</h1>\n```")
            s = Server({"LH_ROOT": tmp, "LH_LOG": str(Path(tmp) / "log.jsonl")}, transport=fake)
            r = call(s, "local_plan", {"task": "página dos y enlazarla en el mapa", "execute": True})
            text = r["result"]["content"][0]["text"]
            self.assertIn("2 de 2 bloques bien", text)
            plans = [b for b in seen if b["messages"][1]["content"].startswith("TAREA:")]
            self.assertEqual(len(plans), 2)
            self.assertIn("no tiene una ruta válida dentro del repo: '../fuera.html'", plans[1]["messages"][1]["content"])
            self.assertEqual(plans[0]["response_format"]["type"], "json_schema")  # JSON garantizado (P9)
            self.assertIn("MAPA DEL REPO", plans[0]["messages"][1]["content"])
            self.assertIn("<li>dos</li>", (Path(tmp) / "mapa.html").read_text(encoding="utf-8"))

    def test_validate_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            errs = validate_plan([{"id": "a", "kind": "write", "path": "../fuera.txt", "instructions": "x", "after": []},
                                  {"id": "a", "kind": "ask", "instructions": "", "after": ["z"]}], Path(tmp).resolve())
            self.assertEqual(len(errs), 4)


class VisionToolTests(unittest.TestCase):
    def test_documents_send_images_and_reduce(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.png").write_bytes(b"\x89PNG fake")
            (Path(tmp) / "b.md").write_text("# Notas\nLa gubia se afila a 25 grados.", encoding="utf-8")
            seen = []

            def fake(body):
                seen.append(body["messages"][1]["content"])
                return reply("respuesta")
            s = Server({"LH_ROOT": tmp}, transport=fake)
            r = call(s, "local_read_documents", {"paths": ["a.png", "b.md"], "question": "¿a cuántos grados?"})
            self.assertNotIn("isError", r["result"])
            parts = seen[0]
            self.assertEqual(parts[1]["type"], "image_url")
            self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))
            self.assertIn("25 grados", seen[1])
            self.assertIn("RESPUESTAS POR DOCUMENTO", seen[2])

    def test_look_takes_desktop_and_mobile_shots(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("<h1>Hola</h1>", encoding="utf-8")
            sizes = []

            def shot(page, out, size, exe=None, timeout=60):
                sizes.append(size)
                out.write_bytes(b"\x89PNG")
                return out
            seen = []

            def fake(body):
                seen.append(body["messages"][1]["content"])
                return reply("Se ve bien.")
            with mock.patch("localharness.vision.screenshot", side_effect=shot):
                r = call(Server({"LH_ROOT": tmp}, transport=fake), "local_look",
                         {"pages": ["index.html"], "question": "un título grande"})
            self.assertIn("Se ve bien", r["result"]["content"][0]["text"])
            self.assertEqual(sizes, [(1280, 1600), (390, 1400)])
            self.assertEqual(sum(1 for p in seen[0] if p["type"] == "image_url"), 2)

    def test_no_vision_model_says_what_to_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.png").write_bytes(b"x")

            def fake(body):
                from localharness.mcp_local import ToolError
                raise ToolError("llama-server HTTP 500: image input is not supported - hint: needs mmproj")
            r = call(Server({"LH_ROOT": tmp}, transport=fake), "local_read_documents",
                     {"paths": ["a.png"], "question": "¿qué pone?"})
            self.assertIn("local_use", r["result"]["content"][0]["text"])


class ModelsToolTests(unittest.TestCase):
    def test_models_and_use_go_through_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def api(method, path, body):
                calls.append((method, path, body))
                if path == "/api/llama/profiles":
                    return {"topology": "separado", "profiles": [
                        {"name": "Qwen3.5-4B", "size_gb": 2.7, "caps": ["vision", "fast"], "load_s": 9,
                         "fits": {"CUDA1": {"fit": "gpu"}}}]}
                if path == "/api/llama":
                    return {"servers": [{"id": "rapido", "device": "CUDA1", "model_name": "Qwen3.5-4B",
                                         "status": {"state": "ready"}}]}
                return {"server": "rapido", "model": "Qwen3.5-4B", "changed": False}
            s = Server({"LH_ROOT": tmp, "LH_API": "http://127.0.0.1:8095"}, transport=reply)
            s.api_call = api
            names = [t["name"] for t in s.tools()]
            self.assertIn("local_use", names)
            text = call(s, "local_models", {})["result"]["content"][0]["text"]
            self.assertIn("Qwen3.5-4B (2.7 GB): vision, fast · CUDA1 · 9 s", text)
            text = call(s, "local_use", {"capability": "vision"})["result"]["content"][0]["text"]
            self.assertIn("Ya estaba cargado Qwen3.5-4B", text)
            self.assertEqual(calls[-1], ("POST", "/api/llama/use", {"capability": "vision", "server": None}))


class RagTests(unittest.TestCase):
    def test_search_finds_by_meaning_and_caches_vectors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            (root / "noche.js").write_text("// modo noche: guarda en localStorage\nfunction alternar() {}\n",
                                           encoding="utf-8")
            (root / "pie.js").write_text("// pie de página con el último parche\nfunction pie() {}\n",
                                         encoding="utf-8")
            words = ["noche", "pie"]
            sent = []

            def post(url, body):
                sent.append(len(body["input"]))
                return {"data": [{"index": i, "embedding": [float(w in t) for w in words] + [0.1]}
                                 for i, t in enumerate(body["input"])]}
            db = Path(tmp) / "rag.sqlite"
            hits = rag.search(root, "dónde se guarda el modo noche", "http://e", 1, db, post)
            self.assertEqual(hits[0]["path"], "noche.js")
            rag.search(root, "el pie", "http://e", 1, db, post)
            self.assertEqual(sent, [2, 1, 1])  # la segunda vez solo se calcula la pregunta

    def test_search_tool_only_with_embed_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotIn("local_search", [t["name"] for t in Server({"LH_ROOT": tmp}, transport=reply).tools()])
            s = Server({"LH_ROOT": tmp, "LH_EMBED_URL": "http://e"}, transport=reply)
            self.assertIn("local_search", [t["name"] for t in s.tools()])


if __name__ == "__main__":
    unittest.main()


class AutoSwapTests(unittest.TestCase):
    def test_auto_swap_loads_a_vision_model_and_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.png").write_bytes(b"x")
            answers = iter(["error", "Pone: gubia"])

            def fake(body):
                from localharness.mcp_local import ToolError
                if next(answers) == "error":
                    raise ToolError("llama-server HTTP 500: image input is not supported")
                return reply("Pone: gubia")
            used = []
            s = Server({"LH_ROOT": tmp, "LH_API": "http://x", "LH_AUTO_SWAP": "1"}, transport=fake)
            s.api_call = lambda m, p, b: used.append(b) or {"server": "principal", "model": "VL", "changed": True}
            r = call(s, "local_read_documents", {"paths": ["a.png"], "question": "¿qué pone?"})
            self.assertIn("gubia", r["result"]["content"][0]["text"])
            self.assertEqual(used, [{"capability": "vision", "server": None}])
