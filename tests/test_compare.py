"""Comparativa: la misma petición con y sin modelos locales, con sus números (con la CLI de Claude falsa)."""

import tempfile
import time
import unittest
from pathlib import Path

from localharness import compare
from localharness.store import Store
from tests.test_core import FAKES, make_repo

try:
    from fastapi.testclient import TestClient

    from localharness.api import create_app
except ImportError:
    TestClient = None

FAKE = str(FAKES / "claude")  # NUNCA la CLI real en pruebas: gastaría tu plan


class CompareUnitTests(unittest.TestCase):
    def test_create_validates(self):
        store = Store(":memory:")
        with tempfile.TemporaryDirectory() as tmp:
            p = store.add_project("demo", str(make_repo(tmp)))
            with self.assertRaises(ValueError):
                compare.create(store, p["id"], "x", ["no-existe"])
            with self.assertRaises(ValueError):
                compare.create(store, p["id"], "x", ["solo"], claude_model="gpt")
            c = compare.create(store, p["id"], "arregla", ["local2", "solo", "solo"], "haiku", "python -m unittest")
            self.assertEqual((c["variants"], c["status"], c["check_cmd"]), (["local2", "solo"], "pending",
                                                                            "python -m unittest"))
            self.assertEqual(c["labels"]["solo"], "Solo Claude")

    def test_measure_from_events(self):
        store = Store(":memory:")
        with tempfile.TemporaryDirectory() as tmp:
            p = store.add_project("demo", str(make_repo(tmp)))
            a = store.add_agent("w", "claude", "sonnet")
            t = store.add_task(p["id"], "x", "y", a["id"])
            store.add_event(t["id"], "status", "running")
            store.add_event(t["id"], "usage", "", {"usage": {"input_tokens": 100, "cache_creation_input_tokens": 50,
                                                             "cache_read_input_tokens": 9000, "output_tokens": 30}})
            store.add_event(t["id"], "delegate", "", {"tool": "local_ask", "ok": True, "prompt_tokens": 400,
                                                      "completion_tokens": 80, "seconds": 2.5, "server": "rapido"})
            store.add_event(t["id"], "delegate", "", {"tool": "local_execute_plan", "ok": True})  # resumen: no cuenta
            store.add_event(t["id"], "tool", "Read")
            store.update_task(t["id"], status="review", finished_at="2026-10-07 10:00:00")
            m = compare.measure(store, t["id"])
            self.assertEqual((m["claude_tokens"], m["claude_cache_read"], m["local_tokens"], m["delegations"],
                              m["by_server"], m["claude_tools"]), (180, 9000, 480, 1, {"rapido": 1}, 1))


@unittest.skipIf(TestClient is None, "faltan fastapi/httpx (pip install -e .[server])")
class CompareApiTests(unittest.TestCase):
    def test_runs_each_variant_and_measures_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            app = create_app(Path(tmp) / "lh.db", worktree_root=str(Path(tmp) / "wt"), web_dist=None,
                             binaries={"claude": FAKE})
            with TestClient(app) as c:
                pid = c.post("/api/projects", json={"name": "demo", "repo_path": str(repo)}).json()["id"]
                r = c.post("/api/compare", json={"project_id": pid, "prompt": "crea el archivo hola.txt",
                                                 "variants": ["solo", "local2"], "claude_model": "haiku",
                                                 "check": "python -m unittest"})
                self.assertEqual(r.status_code, 201, r.text)
                cid = r.json()["id"]
                self.assertEqual(c.post("/api/compare", json={"project_id": pid, "prompt": "otra"}).status_code, 409)
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    got = c.get(f"/api/compare/{cid}").json()
                    if got["status"] not in ("pending", "running"):
                        break
                    time.sleep(0.3)
                self.assertEqual(got["status"], "done", got)
                for v in ("solo", "local2"):
                    res = got["results"][v]
                    self.assertEqual(res["status"], "review", res)
                    self.assertIn("hola.txt", res["files"])
                    self.assertIsNotNone(res["seconds"])
                    self.assertEqual(res["check"]["command"], "python -m unittest")
                tasks = {t["id"]: t for t in c.get("/api/tasks").json()}
                self.assertIn("[Comparativa", tasks[got["results"]["local2"]["task_id"]]["title"])
                listed = c.get("/api/compare").json()
                self.assertEqual(listed["comparisons"][0]["id"], cid)
                self.assertIn("local1", listed["variants"])


if __name__ == "__main__":
    unittest.main()
