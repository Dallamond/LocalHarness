import json
import tempfile
import unittest
from pathlib import Path

from localharness import autopilot
from localharness.autopilot import ApiError, Autopilot


class FakeApi:
    """LocalHarness de mentira: cada tarea acaba según `script` (lista de estados por tarea creada)."""

    def __init__(self, script):
        self.script = list(script)  # por tarea: estado final ("review", "done", "failed", "hang") y coste
        self.tasks: dict[int, dict] = {}
        self.calls: list[tuple] = []
        self.llama = {"config": {"last": {"model": "D:/m/A.gguf"}}, "servers": [
            {"id": "principal", "name": "Fuerte", "status": {"state": "ready"}}]}

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/projects":
            return [{"id": 3, "name": "poeta"}]
        if path == "/api/agents":
            return [{"id": 13, "name": "Jefe de obra"}]
        if path == "/api/llama":
            return self.llama
        if path == "/api/llama/start":
            return {}
        if method == "POST" and path == "/api/tasks":
            tid = len(self.tasks) + 1
            status, cost = self.script.pop(0)
            self.tasks[tid] = {"id": tid, "status": status, "cost_usd": cost, "worktree": f"/wt/{tid}",
                               "final": "hecho", "_hang": status == "hang"}
            if status == "hang":
                self.tasks[tid]["status"] = "running"
            return self.tasks[tid]
        tid = int(path.split("/")[3]) if path.startswith("/api/tasks/") else None
        if path.endswith("/events"):
            return [{"kind": "delegate", "data": {"tool": "local_write_file", "server": "principal", "ok": True,
                                                  "completion_tokens": 100, "gen_seconds": 4, "model": "Qwen"}},
                    {"kind": "delegate", "data": {"tool": "local_ask", "server": "rapido", "ok": False,
                                                  "completion_tokens": 0, "gen_seconds": 1, "model": "Q4B"}}]
        if path.endswith("/cancel"):
            self.tasks[tid]["status"] = "cancelled"
            return self.tasks[tid]
        if path.endswith("/approve"):
            self.tasks[tid]["status"] = "approved"
        if path.endswith("/merge"):
            self.tasks[tid]["status"] = "merged"
        if path.endswith("/reject"):
            self.tasks[tid]["status"] = "rejected"
        if path.endswith("/reply"):
            self.tasks[tid]["status"] = "review"
        if tid:
            return self.tasks[tid]
        raise ApiError(path)


class AutopilotTests(unittest.TestCase):
    def make(self, api, items, checks=None, **kw):
        tmp = Path(tempfile.mkdtemp())
        t = [0.0]
        results = list(checks or [])

        def clock():
            return t[0]

        def sleep(s):
            t[0] += s
        pilot = Autopilot(api, "poeta", "Jefe de obra", items, state=tmp / "estado.json", report=tmp / "informe.md",
                          say=lambda _: None, sleep=sleep, clock=clock,
                          checker=lambda cmd, cwd: results.pop(0) if results else (True, ""), **kw)
        return pilot, tmp

    def test_read_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.md"
            p.write_text("# Parches\n\nnota suelta\n- modo noche\n* galería\n3. buscador\n-\n", encoding="utf-8")
            self.assertEqual(autopilot.read_list(p), ["modo noche", "galería", "buscador"])

    def test_merges_when_tests_pass_and_reports_models(self):
        api = FakeApi([("review", 0.2), ("done", 0.05)])
        pilot, tmp = self.make(api, ["modo noche", "solo texto"])
        rs = pilot.run()
        self.assertEqual([r.outcome for r in rs], ["integrado", "sin cambios"])
        self.assertIn(("POST", "/api/tasks/1/merge", {"confirm": True}), api.calls)
        self.assertIn("CHANGELOG.md): modo noche", api.calls[[c[1] for c in api.calls].index("/api/tasks")][2]["prompt"])
        self.assertEqual(rs[0].models["principal"]["tokens"], 100)
        self.assertEqual(rs[0].models["rapido"]["fallidos"], 1)
        informe = (tmp / "informe.md").read_text(encoding="utf-8")
        self.assertIn("| 001 modo noche | integrado |", informe)
        self.assertIn("principal (Qwen)", informe)

    def test_failing_tests_get_one_retry_then_discard(self):
        api = FakeApi([("review", 0.1)])
        pilot, _ = self.make(api, ["libro"], checks=[(False, "1 failing"), (False, "sigue fallando")])
        r = pilot.run()[0]
        self.assertTrue(r.retried)
        self.assertEqual(r.outcome, "descartado (tests)")
        reply = next(c for c in api.calls if c[1].endswith("/reply"))
        self.assertIn("1 failing", reply[2]["message"])
        self.assertEqual(api.tasks[1]["status"], "rejected")

    def test_hung_task_is_cancelled_and_three_failures_stop(self):
        api = FakeApi([("hang", 0.0)] * 3 + [("review", 0.1)])
        pilot, _ = self.make(api, ["a", "b", "c", "d"], task_minutes=1)
        rs = pilot.run()
        self.assertEqual([r.outcome for r in rs], ["tiempo agotado"] * 3)  # el 4º no llega a empezar
        self.assertEqual(sum(1 for c in api.calls if c[1].endswith("/cancel")), 3)

    def test_budget_and_resume(self):
        api = FakeApi([("review", 3.0), ("review", 3.0)])
        pilot, tmp = self.make(api, ["a", "b", "c"], budget=5.0)
        self.assertEqual(len(pilot.run()), 2)  # tras 6 $ no empieza el tercero
        st = json.loads((tmp / "estado.json").read_text(encoding="utf-8"))
        self.assertEqual([r["n"] for r in st["results"]], [1, 2])
        # retomar: sigue en el 3 (y con presupuesto nuevo)
        api2 = FakeApi([("review", 0.1)])
        pilot2 = Autopilot(api2, "poeta", "Jefe de obra", ["a", "b", "c"], state=tmp / "estado.json",
                           report=tmp / "informe.md", say=lambda _: None, sleep=lambda s: None,
                           checker=lambda c, w: (True, ""), budget=10)
        self.assertEqual([r.n for r in pilot2.run()], [1, 2, 3])

    def test_restarts_a_fallen_model(self):
        api = FakeApi([("done", 0.0)])
        api.llama["servers"][0]["status"]["state"] = "failed"
        pilot, _ = self.make(api, ["a"])
        pilot.run()
        start = next(c for c in api.calls if c[1] == "/api/llama/start")
        self.assertEqual(start[2]["path"], "D:/m/A.gguf")

    def test_unknown_agent(self):
        with self.assertRaises(ApiError):
            Autopilot(FakeApi([]), "poeta", "nadie", ["a"], state=Path("x"), report=Path("y"))
