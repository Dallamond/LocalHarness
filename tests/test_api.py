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

    def test_plan_flow_from_api(self):
        with TestClient(self.app) as c:
            pid, director = self._setup(c)
            body = {"project_id": pid, "director_agent_id": director, "reviewer_agent_id": director,
                    "request": "trabajo GRANDE"}
            p = c.post("/api/plans", json=body).json()
            end = time.monotonic() + 15
            while c.get(f"/api/plans/{p['id']}").json()["status"] in ("planning",) and time.monotonic() < end:
                time.sleep(0.05)
            p = c.get(f"/api/plans/{p['id']}").json()
            self.assertEqual(p["status"], "awaiting_you"); self.assertEqual(len(p["plan"]["subtasks"]), 5)
            self.assertEqual(c.get("/api/inbox").json()[0]["type"], "plan_approval")
            # una subtarea del plan no se integra por la vía de tareas sueltas
            sub = [t for t in p["tasks"] if t["kind"] == "worker"][0]
            self.assertEqual(c.post(f"/api/tasks/{sub['id']}/reject").status_code, 409)
            self.assertEqual(c.post(f"/api/plans/{p['id']}/approve").status_code, 200)
            while c.get(f"/api/plans/{p['id']}").json()["status"] in ("approved", "running") and time.monotonic() < end:
                time.sleep(0.05)
            p = c.get(f"/api/plans/{p['id']}").json()
            self.assertEqual(p["status"], "ready", p["error"])
            self.assertEqual(c.post(f"/api/plans/{p['id']}/merge", json={}).status_code, 422)
            self.assertEqual(c.post(f"/api/plans/{p['id']}/merge", json={"confirm": True}).json()["status"], "merged")
            self.assertTrue((self.repo / "paso5.txt").exists())
            self.assertEqual(c.get("/api/inbox").json(), [])

    def test_edit_and_redo_plan_steps_from_api(self):
        with TestClient(self.app) as c:
            pid, director = self._setup(c)
            p = c.post("/api/plans", json={"project_id": pid, "director_agent_id": director, "request": "algo"}).json()
            end = time.monotonic() + 15

            def wait():
                while c.get(f"/api/plans/{p['id']}").json()["status"] == "planning" and time.monotonic() < end:
                    time.sleep(0.05)
                return c.get(f"/api/plans/{p['id']}").json()
            plan = wait()
            self.assertEqual(plan["status"], "awaiting_you")  # pequeño, pero siempre te espera
            steps = plan["plan"]["subtasks"]
            steps[0]["title"] = "Mi paso"
            r = c.put(f"/api/plans/{p['id']}", json={"subtasks": steps})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual([t["title"] for t in r.json()["tasks"] if t["kind"] == "worker"], ["Mi paso", "Paso 2"])
            bad = c.put(f"/api/plans/{p['id']}", json={"subtasks": [{**steps[0], "agent": "nadie"}]})
            self.assertEqual(bad.status_code, 409)
            self.assertEqual(c.post(f"/api/plans/{p['id']}/redo", json={"seq": 7, "comment": "x"}).status_code, 422)
            self.assertEqual(c.post(f"/api/plans/{p['id']}/redo", json={"seq": 2, "comment": "con tests"}).status_code, 200)
            time.sleep(0.1)
            plan = wait()
            self.assertEqual(plan["status"], "awaiting_you", plan["error"])
            self.assertEqual([s["title"] for s in plan["plan"]["subtasks"]], ["Mi paso", "Paso rehecho"])

    def test_validation(self):
        with TestClient(self.app) as c:
            self.assertEqual(c.post("/api/projects", json={"name": "x", "repo_path": self.tmp.name}).status_code, 422)
            self.assertEqual(c.post("/api/agents", json={"name": "x", "provider": "nope"}).status_code, 422)
            self.assertEqual(c.get("/api/tasks/99").status_code, 404)
            self._setup(c)
            self.assertEqual(c.post("/api/projects", json={"name": "demo", "repo_path": str(self.repo)}).status_code, 409)

    def test_conversation_reply(self):
        with TestClient(self.app) as c:
            pid, aid = self._setup(c)
            t = c.post("/api/tasks", json={"project_id": pid, "agent_id": aid, "prompt": "crea hola.txt"}).json()
            wait_status(c, t["id"], ("review", "failed"))
            r = c.post(f"/api/tasks/{t['id']}/reply", json={"message": "ahora crea el archivo otro.txt"})
            self.assertEqual(r.status_code, 200, r.text)
            time.sleep(0.2)
            t2 = wait_status(c, t["id"], ("review", "failed"))
            self.assertEqual(t2["final"], "Hecho (resume)")  # Claude reanuda su sesión
            self.assertAlmostEqual(t2["cost_usd"], 0.02)  # el coste se acumula
            evs = c.get(f"/api/tasks/{t['id']}/events").json()
            self.assertIn("ahora crea el archivo otro.txt", [e["text"] for e in evs if e["kind"] == "user"])
            files = {f["path"] for f in c.get("/api/activity").json()["recent"][0]["files"]}
            self.assertEqual(files, {"hola.txt", "otro.txt"})  # el diff cuenta desde la base original
            c.post(f"/api/tasks/{t['id']}/reject")
            self.assertEqual(c.post(f"/api/tasks/{t['id']}/reply", json={"message": "x"}).status_code, 409)

    def test_link_folder_with_git_init(self):
        with TestClient(self.app) as c:
            folder = Path(self.tmp.name) / "sin_git"
            folder.mkdir()
            (folder / "a.txt").write_text("a", encoding="utf-8")
            body = {"name": "nuevo", "repo_path": str(folder)}
            self.assertEqual(c.post("/api/projects", json=body).status_code, 422)
            r = c.post("/api/projects", json={**body, "init_git": True})
            self.assertEqual(r.status_code, 201, r.text)

    def test_llama_models(self):
        with TestClient(self.app) as c:
            d = Path(self.tmp.name) / "modelos" / "qwen"
            d.mkdir(parents=True)
            (d / "Qwen2.5-Coder-7B-Q8_0.gguf").write_bytes(b"GGUF")
            (d / "mmproj-qwen.gguf").write_bytes(b"GGUF")  # proyector: no es un modelo
            c.put("/api/settings", json={"llama": {"model_dirs": [str(d.parent)], "port": 18999,
                                                   "server": str(Path(self.tmp.name) / "no-existe.exe")}})
            info = c.get("/api/llama").json()
            self.assertEqual([m["quant"] for m in info["models"]], ["Q8_0"])
            self.assertEqual(info["status"]["state"], "off")
            r = c.post("/api/llama/start", json={"path": info["models"][0]["path"]})
            if info["server"] is None:  # sin llama-server en este equipo: error claro, nada lanzado
                self.assertEqual(r.status_code, 409, r.text)
            else:
                c.post("/api/llama/stop")
            self.assertEqual(c.post("/api/llama/start", json={"path": str(d / "x.txt")}).status_code, 422)
            c.post("/api/settings/reset")

    def test_settings_agents_and_activity(self):
        with TestClient(self.app) as c:
            s = c.get("/api/settings").json()
            self.assertEqual(s["values"]["policy"]["max_files"], 8)
            r = c.put("/api/settings", json={"policy": {"max_files": 2}, "task_timeout_min": 5})
            self.assertEqual(r.status_code, 200, r.text)
            v = r.json()["values"]
            self.assertEqual(v["policy"]["max_files"], 2)
            self.assertEqual(v["policy"]["max_lines"], 300)  # lo no enviado se conserva
            self.assertEqual(c.app.state.runner.hier.policy.max_files, 2)
            self.assertEqual(c.put("/api/settings", json={"nope": 1}).status_code, 422)
            self.assertEqual(c.post("/api/settings/reset").json()["values"]["task_timeout_min"], 30)
            self.assertIsInstance(c.get("/api/skills").json(), list)

            pid, aid = self._setup(c)
            a = c.patch(f"/api/agents/{aid}", json={"model": "haiku", "max_turns": None, "skills": ["tests-primero"]})
            self.assertEqual(a.status_code, 200, a.text)
            self.assertEqual(a.json()["model"], "haiku")
            self.assertNotIn("max_turns", a.json()["config"])
            self.assertEqual(a.json()["config"]["skills"], ["tests-primero"])
            self.assertIn("binary", a.json()["config"])  # lo no enviado no se toca
            p = c.patch(f"/api/projects/{pid}", json={"memory_dir": "  "}).json()
            self.assertIsNone(p["memory_dir"])

            t = c.post("/api/tasks", json={"project_id": pid, "agent_id": aid, "prompt": "crea hola.txt"}).json()
            wait_status(c, t["id"], ("review", "failed"))
            act = c.get("/api/activity").json()
            self.assertEqual(act["recent"][0]["id"], t["id"])
            self.assertTrue(act["recent"][0]["files"])
            self.assertEqual(c.delete(f"/api/agents/{aid}").status_code, 409)  # tiene historial
            other = c.post("/api/agents", json={"name": "libre"}).json()
            self.assertEqual(c.delete(f"/api/agents/{other['id']}").status_code, 204)


if __name__ == "__main__":
    unittest.main()
