import json, tempfile, unittest
from pathlib import Path

from localharness.adapters.base import RunSpec
from localharness.runner import run
from tests.test_core import make_repo

try:
    import httpx
    from localharness.adapters.local import LocalAdapter, _parse_json, repo_context
except ImportError:
    httpx = None


def fake_llama(reply: str, seen: list):
    """llama-server simulado: /v1/models y /v1/chat/completions en streaming SSE."""
    def handler(request: "httpx.Request") -> "httpx.Response":
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen-falso"}]})
        body = json.loads(request.content)
        seen.append(body)
        pieces = [reply[i:i + 7] for i in range(0, len(reply), 7)]
        lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}" for p in pieces]
        lines.append("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}],
                                            "usage": {"prompt_tokens": 50, "completion_tokens": 9},
                                            "timings": {"predicted_per_second": 42.0}}))
        lines.append("data: [DONE]")
        return httpx.Response(200, text="\n\n".join(lines) + "\n\n",
                              headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


@unittest.skipIf(httpx is None, "falta httpx (pip install -e .[server])")
class LocalAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_text_and_repo_context(self):
        seen, evs = [], []
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            a = LocalAdapter(transport=fake_llama("Primer párrafo.\n\nSegundo párrafo.", seen))
            res = await run(a, RunSpec(prompt="resume el repo", cwd=str(repo)), evs.append)
        self.assertEqual(res["status"], "done")
        self.assertEqual(res["final"], "Primer párrafo.\n\nSegundo párrafo.")
        kinds = [e.kind for e in evs]
        self.assertEqual(kinds[0], "session"); self.assertEqual(evs[0].data["model"], "qwen-falso")
        self.assertIn("usage", kinds); self.assertEqual(kinds[-1], "result")
        usage = next(e for e in evs if e.kind == "usage")
        self.assertEqual((usage.data["cost_usd"], usage.data["tps"]), (0.0, 42.0))  # gratis para el plan
        user = seen[0]["messages"][1]["content"]
        self.assertIn("CONTEXTO DEL REPOSITORIO", user); self.assertIn("--- README.md ---", user)

    async def test_json_schema(self):
        seen, evs = [], []
        schema = {"type": "object", "properties": {"verdict": {"type": "string"}}, "required": ["verdict"]}
        a = LocalAdapter(transport=fake_llama('{"verdict": "approve"}', seen), repo_context=0)
        res = await run(a, RunSpec(prompt="revisa", cwd=".", json_schema=schema), evs.append)
        self.assertEqual(res["structured"], {"verdict": "approve"})
        self.assertEqual(seen[0]["response_format"]["json_schema"]["schema"], schema)
        bad = await run(LocalAdapter(transport=fake_llama("no es json", []), repo_context=0),
                        RunSpec(prompt="x", cwd=".", json_schema=schema), evs.append)
        self.assertEqual(bad["status"], "failed")

    async def test_server_down(self):
        def down(request):
            raise httpx.ConnectError("rechazada")
        evs = []
        res = await run(LocalAdapter(transport=httpx.MockTransport(down)), RunSpec(prompt="x", cwd="."), evs.append)
        self.assertEqual(res["status"], "failed"); self.assertIn("llama serve", evs[0].text)

    def test_parse_json_tolerant(self):
        self.assertEqual(_parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(_parse_json('Aquí va: {"a": 1} y fin'), {"a": 1})
        self.assertIsNone(_parse_json("nada"))

    def test_repo_context_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            self.assertIn("README.md", repo_context(repo, 1000))
            self.assertLessEqual(len(repo_context(repo, 30)), 60)


class LocalCannotWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_director_never_assigns_work_to_local_models(self):
        from localharness.hierarchy import Hierarchy
        from localharness.store import Store
        from tests.test_core import FAKES
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            store = Store()
            pid = store.add_project("demo", str(repo))["id"]
            d = store.add_agent("director", "claude", config={"binary": str(FAKES / "claude")})["id"]
            store.add_agent("qwen", "local")  # aparece primero en la lista si se colase
            store.add_agent("w", "claude", config={"binary": str(FAKES / "claude")})
            p = await Hierarchy(store, worktree_root=str(Path(tmp) / "wt")).plan(store.add_plan(pid, "x", d)["id"])
            self.assertEqual({s["agent"] for s in json.loads(p["plan"])["subtasks"]}, {"w"})
            store.close()


if __name__ == "__main__":
    unittest.main()
