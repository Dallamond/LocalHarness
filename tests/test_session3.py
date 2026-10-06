"""Sesión 3: subagentes, progreso de carga de llama-server, tokens/s, configuración por modelo y modelo real."""

import json, tempfile, time, unittest
from pathlib import Path

from localharness import llama, settings
from localharness.adapters import get_adapter
from localharness.adapters.base import RunSpec
from localharness.hierarchy import close_pending
from localharness.runner import run
from localharness.store import Store
from tests.test_core import make_repo

try:
    import httpx
    from localharness.adapters import local as local_mod
    from localharness.adapters.local import LocalAdapter
except ImportError:
    httpx = None


def tools_of(cmd: list[str]) -> list[str]:
    return cmd[cmd.index("--tools") + 1].split(",")


class SubagentTests(unittest.TestCase):
    def test_extra_tools_add_agent(self):
        a = get_adapter("claude")
        self.assertNotIn("Agent", tools_of(a.build_command(RunSpec(prompt="x", cwd="."))))
        cmd = a.build_command(RunSpec(prompt="x", cwd=".", extra_tools=["Agent"]))
        self.assertIn("Agent", tools_of(cmd))
        self.assertIn("Agent", cmd[cmd.index("--allowedTools") + 1].split(","))
        self.assertIn("Edit", tools_of(cmd))  # no sustituye las de escritura, se suman


class LoadProgressTests(unittest.TestCase):
    NEW_LOG = ("0.08.788 I srv  llama_server: initializing ...\n"
               "0.08.852 I srv    load_model: loading model 'D:\\m\\qwen.gguf'\n")

    def test_stage_without_history_is_indeterminate(self):
        p = llama.load_progress(self.NEW_LOG, 10, None)
        self.assertEqual((p["pct"], p["stage"]), (None, "leyendo el modelo del disco"))

    def test_time_based_with_previous_load(self):
        p = llama.load_progress(self.NEW_LOG, 30, 60)
        self.assertEqual((p["pct"], p["source"], p["eta_s"]), (50, "tiempo", 30))
        self.assertEqual(llama.load_progress(self.NEW_LOG, 600, 60)["pct"], 95)  # nunca 100 hasta que esté listo

    def test_late_stage_from_log(self):
        log = self.NEW_LOG + "1.12.575 I srv    load_model: initializing, n_slots = 4\n"
        self.assertEqual(llama.load_progress(log, 5, None)["pct"], 92)

    def test_dots_of_old_llama_cpp(self):
        log = "llama_model_load: loading model\nload_tensors: offloading 28 layers\n" + "." * 50 + "\n"
        p = llama.load_progress(log, 1, None)
        self.assertEqual((p["pct"], p["source"]), (50, "log"))

    def test_last_lines_skip_dots(self):
        self.assertEqual(llama.last_lines("a\n\nb\n.....\n  \nc\n"), ["b", "c"])

    def test_load_time_remembered(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = llama.LlamaManager(Path(tmp) / "llama-server.log")
            m._remember_load_time("D:/m/q.gguf", 64.2)
            self.assertEqual(llama.LlamaManager(Path(tmp) / "llama-server.log").load_times(), {"D:/m/q.gguf": 64.2})


class PerModelSettingsTests(unittest.TestCase):
    def test_launch_uses_own_config(self):
        s = Store(":memory:")
        self.assertEqual(settings.llama_launch(s, "a.gguf"), {"ctx": 16384, "ngl": 99, "extra": []})
        settings.save(s, {"llama": {"per_model": {"a.gguf": {"ctx": 8192, "ngl": 0, "extra": "-fa on -t 8"}}}})
        self.assertEqual(settings.llama_launch(s, "a.gguf"), {"ctx": 8192, "ngl": 0, "extra": ["-fa", "on", "-t", "8"]})
        self.assertEqual(settings.llama_launch(s, "b.gguf")["ctx"], 16384)
        self.assertEqual(settings.load(s)["llama"]["port"], 8080)  # el resto de la sección se conserva


class ClosePendingTests(unittest.TestCase):
    def test_pending_subtasks_of_a_dead_plan_are_closed(self):
        s = Store(":memory:")
        p = s.add_project("demo", "/x")
        a = s.add_agent("w", "claude")
        plan = s.add_plan(p["id"], "algo", a["id"], None)
        ids = []
        for seq, st in ((1, "approved"), (2, "pending"), (3, "pending")):
            t = s.add_task(p["id"], f"t{seq}", "p", a["id"])
            s.update_task(t["id"], plan_id=plan["id"], seq=seq, kind="worker", status=st)
            ids.append(t["id"])
        self.assertEqual(close_pending(s, plan["id"]), 2)
        self.assertEqual([s.get_task(i)["status"] for i in ids], ["approved", "cancelled", "cancelled"])

    def test_startup_cleans_old_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store(Path(tmp) / "lh.db")
            p = s.add_project("demo", "/x")
            a = s.add_agent("w", "claude")
            plan = s.add_plan(p["id"], "algo", a["id"], None)
            s.update_plan(plan["id"], status="failed")
            t = s.add_task(p["id"], "t", "p", a["id"])
            s.update_task(t["id"], plan_id=plan["id"], seq=1, kind="worker")
            loose = s.add_task(p["id"], "suelta", "p", a["id"])  # una tarea suelta pendiente no se toca
            s.mark_interrupted()
            self.assertEqual(s.get_task(t["id"])["status"], "cancelled")
            self.assertEqual(s.get_task(loose["id"])["status"], "pending")
            s.close()


def fake_llama(pieces: list[tuple[str, str]], served: str, seen: list, delay: float = 0.0):
    """llama-server simulado; `pieces` = [(campo del delta, texto)], p. ej. reasoning_content y content."""
    def handler(request: "httpx.Request") -> "httpx.Response":
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": served}]})
        seen.append(json.loads(request.content))
        lines = [f"data: {json.dumps({'choices': [{'delta': {k: v}}]})}" for k, v in pieces]
        lines.append("data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}))
        lines.append("data: [DONE]")
        return httpx.Response(200, text="\n\n".join(lines) + "\n\n", headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


@unittest.skipIf(httpx is None, "falta httpx (pip install -e .[server])")
class LocalModelNameAndSpeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_reports_the_served_model(self):
        seen, evs = [], []
        a = LocalAdapter(transport=fake_llama([("content", "hola")], "D:\\modelos\\Qwen3-8B-Q8_0.gguf", seen),
                         repo_context=0)
        await run(a, RunSpec(prompt="x", cwd=".", model="DeepSeek-R1-Distill"), evs.append)
        session = next(e for e in evs if e.kind == "session")
        self.assertEqual(session.data["model"], "Qwen3-8B-Q8_0")  # el arrancado, no la etiqueta del agente
        self.assertEqual(session.data["requested"], "DeepSeek-R1-Distill")
        self.assertTrue(any(e.kind == "warning" and "DeepSeek" in e.text for e in evs))
        self.assertNotIn("model", seen[0])  # no se manda el nombre del agente al servidor

    async def test_no_warning_when_names_match(self):
        evs = []
        a = LocalAdapter(transport=fake_llama([("content", "hola")], "qwen3-8b-q8_0.gguf", []), repo_context=0)
        await run(a, RunSpec(prompt="x", cwd=".", model="Qwen3-8B"), evs.append)
        self.assertFalse(any(e.kind == "warning" for e in evs))

    async def test_speed_events_and_phase(self):
        evs = []
        old = local_mod.SPEED_EVERY_S
        local_mod.SPEED_EVERY_S = 0  # en la prueba, un evento por trozo
        try:
            pieces = [("reasoning_content", "pienso")] * 3 + [("content", "respuesta")] * 2
            a = LocalAdapter(transport=fake_llama(pieces, "m", []), repo_context=0)
            await run(a, RunSpec(prompt="x", cwd="."), evs.append)
        finally:
            local_mod.SPEED_EVERY_S = old
        speed = [e for e in evs if e.kind == "speed"]
        self.assertTrue(speed)
        self.assertEqual(speed[0].data["phase"], "pensando")
        self.assertEqual(speed[-1].data["phase"], "escribiendo")
        self.assertEqual(speed[-1].data["tokens"], 5)
        usage = next(e for e in evs if e.kind == "usage")
        self.assertEqual(usage.data["tokens"], 5)


try:
    from fastapi.testclient import TestClient
    from localharness.api import create_app
except ImportError:
    TestClient = None


@unittest.skipIf(TestClient is None, "faltan fastapi/httpx")
class AgentFieldsApiTests(unittest.TestCase):
    def test_subagents_and_local_settings(self):
        with tempfile.TemporaryDirectory() as tmp, TestClient(create_app(Path(tmp) / "lh.db", web_dist=None)) as c:
            a = c.post("/api/agents", json={"name": "s", "provider": "claude", "subagents": True}).json()
            self.assertTrue(a["config"]["subagents"])
            l = c.post("/api/agents", json={"name": "q", "provider": "local", "temperature": 0.5,
                                            "max_tokens": 2048, "repo_context": 0}).json()
            self.assertEqual((l["config"]["temperature"], l["config"]["max_tokens"], l["config"]["repo_context"]),
                             (0.5, 2048, 0))
            e = c.patch(f"/api/agents/{a['id']}", json={"subagents": False}).json()
            self.assertNotIn("subagents", e["config"])
            e = c.patch(f"/api/agents/{l['id']}", json={"repo_context": 0, "temperature": None}).json()
            self.assertEqual(e["config"]["repo_context"], 0)  # 0 se guarda (sin contexto), null lo quita
            self.assertNotIn("temperature", e["config"])
            h = c.get("/api/health").json()
            self.assertIn("local", h)


if __name__ == "__main__":
    unittest.main()
