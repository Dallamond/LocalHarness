import json, tempfile, unittest
from pathlib import Path

from localharness.actions import ActionError
from localharness import hierarchy, settings
from localharness.hierarchy import Hierarchy, PlanError, director_prompt, inbox, validate_plan
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


class ManualTests(unittest.TestCase):
    def test_director_follows_the_editable_manual(self):
        agents = [{"name": "sonnet-w", "provider": "claude", "model": "sonnet", "role": None}]
        self.assertIn("Ciclo que sigues siempre", director_prompt("haz X", agents))  # manual/director.md
        with tempfile.TemporaryDirectory() as tmp:
            old = hierarchy.MANUAL
            try:
                hierarchy.MANUAL = Path(tmp) / "director.md"
                self.assertIn("Reglas del plan", director_prompt("haz X", agents))  # sin manual: reglas de serie
                hierarchy.MANUAL.write_text("Regla única: una subtarea.", encoding="utf-8")
                self.assertIn("Regla única: una subtarea.", director_prompt("haz X", agents))
            finally:
                hierarchy.MANUAL = old


class HierarchyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(self.tmp.name)
        self.store = Store()
        settings.save(self.store, {"plans": {"always_review": False}})  # estas pruebas miden los niveles solos
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
        self.assertFalse((Path(p["worktree"]) / "README.md").exists())
        self.h.decide_task(item["task_id"], approve=False)
        self.assertTrue((Path(p["worktree"]) / "README.md").exists())  # el borrado se deshizo
        p = await self.h.run(p["id"])
        # sin nada aprobado que integrar, el plan se cierra solo y limpia su rama
        self.assertEqual(p["status"], "done")
        self.assertNotIn("localharness/plan-", git(self.repo, "branch", "--list"))
        self.assertEqual(inbox(self.store), [])

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


class PlanReviewTests(unittest.IsolatedAsyncioTestCase):
    """Objetivo 3: el plan te espera y puedes aprobarlo, editar un paso o pedir al Director que rehaga uno."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(self.tmp.name)
        self.store = Store()  # always_review por defecto: True
        self.pid = self.store.add_project("demo", str(self.repo))["id"]
        cfg = {"binary": FAKE}
        self.director = self.store.add_agent("director", "claude", role="director", config=cfg)["id"]
        self.store.add_agent("trabajador", "claude", role="trabajador", config=cfg)
        self.h = Hierarchy(self.store, worktree_root=str(Path(self.tmp.name) / "wt"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def steps(self, pid):
        return [(t["seq"], t["title"], t["status"]) for t in self.store.plan_tasks(pid) if t["kind"] == "worker"]

    async def test_small_plan_waits_for_you_by_default(self):
        p = await self.h.plan(self.store.add_plan(self.pid, "algo pequeño", self.director)["id"])
        self.assertEqual((p["status"], p["level"]), ("awaiting_you", "N0"))
        self.assertIn("revisas siempre el plan", " ".join(json.loads(p["level_reasons"])))
        self.assertEqual(inbox(self.store)[0]["type"], "plan_approval")

    async def test_edit_steps_before_approving(self):
        pid = (await self.h.plan(self.store.add_plan(self.pid, "algo", self.director)["id"]))["id"]
        sub = json.loads(self.store.get_plan(pid)["plan"])["subtasks"]
        sub[0]["prompt"] = "crea el archivo editado.txt"; sub[0]["title"] = "Editado por mí"
        p = self.h.edit_plan(pid, [sub[0]])  # además quito el paso 2
        self.assertEqual(self.steps(pid), [(1, "Editado por mí", "pending")])
        self.assertIn("plan editado por ti", json.loads(p["level_reasons"]))
        with self.assertRaises(ActionError):
            self.h.edit_plan(pid, [{**sub[0], "agent": "inventado"}])  # se valida como el del Director
        self.h.approve_plan(pid)
        with self.assertRaises(ActionError):
            self.h.edit_plan(pid, [sub[0]])  # aprobado: ya no se edita
        p = await self.h.run(pid)
        self.assertEqual(p["status"], "paused")  # N1 sin jefe técnico → te llega a ti
        task = next(t for t in self.store.plan_tasks(pid) if t["kind"] == "worker")
        self.assertEqual(task["prompt"], "crea el archivo editado.txt")

    async def test_redo_one_step_with_a_comment(self):
        pid = (await self.h.plan(self.store.add_plan(self.pid, "algo", self.director)["id"]))["id"]
        p = await self.h.redo_step(pid, 2, "hazlo con tests")
        self.assertEqual(p["status"], "awaiting_you")
        self.assertEqual(self.steps(pid), [(1, "Paso 1", "pending"), (2, "Paso rehecho", "pending")])
        step2 = json.loads(p["plan"])["subtasks"][1]
        self.assertIn("hazlo con tests", step2["prompt"]); self.assertEqual(step2["skills"], ["tests-primero"])
        d = next(t for t in self.store.plan_tasks(pid) if t["kind"] == "director")
        users = [e["text"] for e in self.store.list_events(d["id"]) if e["kind"] == "user"]
        self.assertIn("REHAGAS SOLO el paso 2", users[0])  # sigue la conversación del Director (su sesión)
        self.assertAlmostEqual(p["cost_usd"], 0.009)  # plan + paso rehecho
        with self.assertRaises(ActionError):
            await self.h.redo_step(pid, 9, "x")
