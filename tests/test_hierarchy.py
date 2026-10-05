import json, tempfile, unittest
from pathlib import Path

from localharness.actions import ActionError
from localharness.hierarchy import Hierarchy, PlanError, inbox, validate_plan
from localharness.policy import N0, N1, N2, FileChange, Policy, assess_changes, parse_numstat
from localharness.store import Store
from localharness.workspace import git
from tests.test_core import FAKES, make_repo

FAKE = str(FAKES / "claude")  # NUNCA la CLI real en pruebas


class PolicyTests(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(assess_changes([]).level, N0)
        self.assertEqual(assess_changes([FileChange("src/a.py", "M", 10, 2)]).level, N1)
        for c in (FileChange("README.md", "D"), FileChange(".env.local", "M", 1),
                  FileChange("web/package.json", "M", 1), FileChange(".github/workflows/ci.yml", "A", 5),
                  FileChange("db/migrations/001.sql", "A", 3)):
            self.assertEqual(assess_changes([c]).level, N2, c.path)
        many = [FileChange(f"f{i}.py", "A", 1) for i in range(9)]
        self.assertEqual(assess_changes(many).level, N2)
        self.assertEqual(assess_changes([FileChange("a.py", "M", 200, 101)]).level, N2)
        self.assertEqual(assess_changes(many, Policy(max_files=20)).level, N1)  # umbral editable

    def test_parse_numstat(self):
        ch = parse_numstat("3\t1\ta.py\n-\t-\timg.png\n0\t5\told.txt\n", "M\ta.py\nA\timg.png\nD\told.txt\n")
        self.assertEqual([(c.path, c.status, c.added, c.deleted) for c in ch],
                         [("a.py", "M", 3, 1), ("img.png", "A", 0, 0), ("old.txt", "D", 0, 5)])

    def test_validate_plan(self):
        agents = [{"id": 1, "name": "w"}]
        ok = validate_plan({"summary": "", "risk": "low",
                            "subtasks": [{"title": "t", "prompt": "p", "agent": "w", "risk": "low"}]}, agents)
        self.assertEqual(ok["subtasks"][0]["agent_id"], 1)
        with self.assertRaises(PlanError):  # el Director solo elige entre agentes registrados
            validate_plan({"risk": "low", "subtasks": [{"title": "t", "prompt": "p", "agent": "otro", "risk": "low"}]}, agents)
        with self.assertRaises(PlanError):
            validate_plan(None, agents)


class HierarchyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(self.tmp.name)
        self.store = Store()
        self.pid = self.store.add_project("demo", str(self.repo))["id"]
        cfg = {"binary": FAKE}
        self.director = self.store.add_agent("director", "claude", role="director", config=cfg)["id"]
        self.worker = self.store.add_agent("trabajador", "claude", role="trabajador", config=cfg)["id"]
        self.jefe = self.store.add_agent("jefe", "claude", role="jefe", config=cfg)["id"]
        self.events = []
        self.h = Hierarchy(self.store, worktree_root=str(Path(self.tmp.name) / "wt"),
                           on_event=lambda tid, ev: self.events.append((tid, ev.kind, ev.text)))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _plan(self, request: str, reviewer: bool = True) -> dict:
        return self.store.add_plan(self.pid, request, self.director, self.jefe if reviewer else None)

    def kinds(self, plan_id):
        return [(t["kind"], t["status"], t["level"], t["approved_by"]) for t in self.store.plan_tasks(plan_id)]

    async def test_small_plan_runs_and_jefe_approves(self):
        p = self._plan("añade dos archivos")
        p = await self.h.plan(p["id"])
        self.assertEqual(p["status"], "approved"); self.assertEqual(p["level"], "N0")
        plan = json.loads(p["plan"])
        self.assertEqual([s["agent"] for s in plan["subtasks"]], ["trabajador", "trabajador"])
        p = await self.h.run(p["id"])
        self.assertEqual(p["status"], "ready", p["error"])
        self.assertEqual(self.kinds(p["id"]), [
            ("director", "done", "N0", None),
            ("worker", "approved", "N1", "jefe"), ("reviewer", "done", "N0", None),
            ("worker", "approved", "N1", "jefe"), ("reviewer", "done", "N0", None)])
        self.assertEqual(inbox(self.store)[0]["type"], "plan_merge")  # integrar: siempre tú
        self.assertFalse((self.repo / "paso1.txt").exists())
        self.h.merge_plan(p["id"])
        self.assertTrue((self.repo / "paso1.txt").exists()); self.assertTrue((self.repo / "paso2.txt").exists())
        self.assertEqual(self.store.get_plan(p["id"])["status"], "merged")
        self.assertNotIn("localharness/plan-", git(self.repo, "branch", "--list"))
        self.assertGreater(self.store.get_plan(p["id"])["cost_usd"], 0)

    async def test_big_plan_needs_your_approval(self):
        p = await self.h.plan(self._plan("refactor GRANDE")["id"])
        self.assertEqual(p["status"], "awaiting_you"); self.assertEqual(p["level"], "N2")
        self.assertIn("plan grande", json.loads(p["level_reasons"])[0])
        self.assertEqual(inbox(self.store)[0]["type"], "plan_approval")
        with self.assertRaises(ActionError):
            await self.h.run(p["id"])  # no arranca sin tu aprobación
        self.h.approve_plan(p["id"])
        self.assertEqual((await self.h.run(p["id"]))["status"], "ready")

    async def test_deleting_files_stops_for_you_and_reject_undoes_commit(self):
        p = await self.h.plan(self._plan("BORRA el readme")["id"])
        self.assertEqual(p["status"], "awaiting_you")  # riesgo alto declarado
        self.h.approve_plan(p["id"])
        p = await self.h.run(p["id"])
        self.assertEqual(p["status"], "paused")
        item = inbox(self.store)[0]
        self.assertEqual((item["type"], item["level"]), ("task_decision", "N2"))
        self.assertTrue(any("borra archivos" in r for r in item["reasons"]))
        # el jefe técnico no llega a revisar: N2 por reglas no se le delega
        self.assertNotIn("reviewer", [k[0] for k in self.kinds(p["id"])])
        self.h.decide_task(item["task_id"], approve=False)
        p = await self.h.run(p["id"])
        self.assertEqual(p["status"], "ready")
        ws_readme = Path(p["worktree"]) / "README.md"
        self.assertTrue(ws_readme.exists())  # el borrado se deshizo

    async def test_reviewer_can_only_raise_the_level(self):
        p = await self.h.plan(self._plan("dos pasos, ESCALA el último")["id"])
        p = await self.h.run(p["id"])
        self.assertEqual(p["status"], "paused")
        tasks = self.store.plan_tasks(p["id"])
        last = [t for t in tasks if t["kind"] == "worker"][-1]
        self.assertEqual((last["status"], last["level"]), ("review", "N2"))
        self.assertEqual(json.loads(last["review"])["verdict"], "escalate")
        self.h.decide_task(last["id"], approve=True)
        self.assertEqual(self.store.get_task(last["id"])["approved_by"], "tú")
        self.assertEqual((await self.h.run(p["id"]))["status"], "ready")

    async def test_without_reviewer_n1_goes_to_you(self):
        p = await self.h.plan(self._plan("un cambio", reviewer=False)["id"])
        p = await self.h.run(p["id"])
        self.assertEqual(p["status"], "paused")
        self.assertIn("no hay jefe técnico", " ".join(inbox(self.store)[0]["reasons"]))

    async def test_reject_plan_cleans_branch(self):
        p = await self.h.plan(self._plan("GRANDE")["id"])
        self.h.reject_plan(p["id"])
        self.assertEqual(self.store.get_plan(p["id"])["status"], "rejected")
        self.assertNotIn("localharness/plan-", git(self.repo, "branch", "--list"))
        self.assertEqual(inbox(self.store), [])


if __name__ == "__main__":
    unittest.main()
