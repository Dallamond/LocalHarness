import tempfile, textwrap, time, unittest
from pathlib import Path

from tests.test_core import FAKES, make_repo

try:
    from fastapi.testclient import TestClient
    from localharness.api import create_app
except ImportError:  # dependencias del servidor no instaladas
    TestClient = None

FAKE = str(FAKES / "claude")  # NUNCA la CLI real en pruebas: gastaría tu plan


def wait_status(c, tid: int, states: tuple[str, ...], timeout: float = 15.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        t = c.get(f"/api/tasks/{tid}").json()
        if t["status"] in states:
            return t
        time.sleep(0.05)
    raise AssertionError(f"la tarea #{tid} no llegó a {states}: {t['status']}")


@unittest.skipIf(TestClient is None, "faltan fastapi/httpx (pip install -e .[server])")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(self.tmp.name)
        self.app = create_app(Path(self.tmp.name) / "lh.db", worktree_root=str(Path(self.tmp.name) / "wt"),
                              web_dist=None)

    def tearDown(self):
        self.tmp.cleanup()

    def _setup(self, c, binary: str = FAKE) -> tuple[int, int]:
        p = c.post("/api/projects", json={"name": "demo", "repo_path": str(self.repo)})
        self.assertEqual(p.status_code, 201, p.text)
        a = c.post("/api/agents", json={"name": "w", "provider": "claude", "max_turns": 5})
        self.assertEqual(a.status_code, 201, a.text)
        # el binario va en la config del agente (la API no lo expone): se fija directamente para la prueba
        c.app.state.store.db.execute("UPDATE agents SET config=json_set(config,'$.binary',?) WHERE id=?",
                                     (binary, a.json()["id"]))
        c.app.state.store.db.commit()
        return p.json()["id"], a.json()["id"]

    def test_full_cycle_from_api(self):
        with TestClient(self.app) as c:
            pid, aid = self._setup(c)
            q = c.app.state.hub.subscribe()  # lo mismo que recibe la GUI por SSE
            t = c.post("/api/tasks", json={"project_id": pid, "agent_id": aid, "prompt": "crea hola.txt"}).json()
            t = wait_status(c, t["id"], ("review", "failed"))
            self.assertEqual(t["status"], "review")
            self.assertEqual(t["cost_usd"], 0.01)
            published = []
            while not q.empty():
                published.append(q.get_nowait()[0])
            self.assertIn("task_event", published); self.assertIn("task", published)

            kinds = [e["kind"] for e in c.get(f"/api/tasks/{t['id']}/events").json()]
            self.assertEqual(kinds[0], "status"); self.assertIn("session", kinds); self.assertIn("text", kinds)
            r = c.get(f"/api/tasks/{t['id']}/review").json()
            self.assertTrue(r["available"]); self.assertIn("+hola", r["diff"]); self.assertEqual(r["target"], "main")

            # integrar exige aprobar antes y confirmar
            self.assertEqual(c.post(f"/api/tasks/{t['id']}/merge", json={"confirm": True}).status_code, 409)
            self.assertEqual(c.post(f"/api/tasks/{t['id']}/approve").json()["status"], "approved")
            self.assertEqual(c.post(f"/api/tasks/{t['id']}/merge", json={}).status_code, 422)
            self.assertFalse((self.repo / "hola.txt").exists())
            m = c.post(f"/api/tasks/{t['id']}/merge", json={"confirm": True})
            self.assertEqual(m.status_code, 200, m.text); self.assertEqual(m.json()["status"], "merged")
            self.assertTrue((self.repo / "hola.txt").exists())

    def test_reject_removes_branch(self):
        with TestClient(self.app) as c:
            pid, aid = self._setup(c)
            t = c.post("/api/tasks", json={"project_id": pid, "agent_id": aid, "prompt": "x"}).json()
            wait_status(c, t["id"], ("review",))
            self.assertEqual(c.post(f"/api/tasks/{t['id']}/reject").json()["status"], "rejected")
            from localharness.workspace import git
            self.assertNotIn("localharness/task-", git(self.repo, "branch", "--list"))

    def test_cancel_running_task(self):
        slow = Path(self.tmp.name) / "slow"
        slow.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json, time
            print(json.dumps({"type": "system", "subtype": "init", "session_id": "s"}), flush=True)
            time.sleep(30)
        """))
        with TestClient(self.app) as c:
            pid, aid = self._setup(c, binary=str(slow))
            t = c.post("/api/tasks", json={"project_id": pid, "agent_id": aid, "prompt": "x"}).json()
            wait_status(c, t["id"], ("running",))
            # una segunda tarea en el mismo repo se rechaza mientras la primera corre
            self.assertEqual(c.post("/api/tasks", json={"project_id": pid, "agent_id": aid, "prompt": "y"}).status_code, 409)
            self.assertEqual(c.post(f"/api/tasks/{t['id']}/cancel").json()["status"], "cancelled")
            self.assertEqual(c.get("/api/health").json()["running"], [])

    def test_validation(self):
        with TestClient(self.app) as c:
            self.assertEqual(c.post("/api/projects", json={"name": "x", "repo_path": self.tmp.name}).status_code, 422)
            self.assertEqual(c.post("/api/agents", json={"name": "x", "provider": "nope"}).status_code, 422)
            self.assertEqual(c.get("/api/tasks/99").status_code, 404)
            self._setup(c)
            self.assertEqual(c.post("/api/projects", json={"name": "demo", "repo_path": str(self.repo)}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
