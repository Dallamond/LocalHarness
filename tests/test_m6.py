"""M6: conflictos de merge sin dejar el repo a medias y limpieza de worktrees/ramas de lo ya cerrado."""

import tempfile, unittest
from pathlib import Path

from localharness import workspace
from localharness.maintenance import cleanup
from localharness.store import Store
from localharness.workspace import MergeConflict, git
from tests.test_core import make_repo


def commit(repo: Path, name: str, text: str, msg: str) -> None:
    (repo / name).write_text(text, newline="\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


class MergeConflictTests(unittest.TestCase):
    def test_conflict_is_detected_and_repo_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            ws = workspace.create(repo, 1, Path(tmp) / "wt")
            commit(ws.path, "README.md", "versión del agente\n", "agente")
            commit(repo, "README.md", "versión tuya\n", "tú")  # la rama principal avanzó por otro lado
            before = git(repo, "rev-parse", "HEAD")
            with self.assertRaises(MergeConflict) as cm:
                ws.merge()
            self.assertEqual(cm.exception.files, ["README.md"])
            self.assertIn("No se ha tocado tu rama", str(cm.exception))
            self.assertEqual(git(repo, "rev-parse", "HEAD"), before)
            self.assertEqual(git(repo, "status", "--porcelain"), "")  # sin marcas de conflicto ni MERGING
            self.assertEqual((repo / "README.md").read_text(), "versión tuya\n")

    def test_clean_merge_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            ws = workspace.create(repo, 1, Path(tmp) / "wt")
            commit(ws.path, "nuevo.txt", "hola\n", "agente")
            commit(repo, "otro.txt", "x\n", "tú")
            self.assertEqual(workspace.conflicts(repo, "main", ws.branch), [])
            ws.merge()
            self.assertTrue((repo / "nuevo.txt").exists())


    def test_merge_without_git_identity(self):
        """PC sin `git config user.email` (instituto): integrar no puede fallar con «Committer identity unknown»."""
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            ws = workspace.create(repo, 1, Path(tmp) / "wt")
            commit(ws.path, "nuevo.txt", "hola\n", "agente")
            git(repo, "config", "user.useConfigOnly", "true")  # git no se inventa identidad: como en ese PC
            git(repo, "config", "--unset", "user.email")
            git(repo, "config", "--unset", "user.name")
            env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_AUTHOR", "GIT_COMMITTER", "EMAIL"))}
            empty = Path(tmp) / "gitconfig-vacio"
            empty.write_text("")
            env.update(GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM="1")
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(workspace.identity(repo), workspace.FALLBACK_IDENTITY)
                ws.merge()
            self.assertTrue((repo / "nuevo.txt").exists())
            self.assertIn("LocalHarness", git(repo, "log", "-1", "--format=%an"))


class CleanupTests(unittest.TestCase):
    def test_only_closed_work_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            s = Store(":memory:")
            p = s.add_project("demo", str(repo))
            a = s.add_agent("w", "claude")
            made = {}
            for status in ("done", "merged", "failed", "approved"):
                t = s.add_task(p["id"], status, "x", a["id"])
                ws = workspace.create(repo, t["id"], Path(tmp) / "wt")
                s.update_task(t["id"], status=status, branch=ws.branch, worktree=str(ws.path))
                made[status] = ws
            workspace.create(repo, 99, Path(tmp) / "wt")  # no está en la base de datos

            dry = cleanup(s, dry_run=True)
            self.assertEqual(sorted(i["status"] for i in dry["removed"]), ["done", "merged"])
            self.assertTrue(made["done"].path.exists())  # simulación: no toca nada

            r = cleanup(s)
            self.assertEqual(sorted(i["status"] for i in r["kept"]), ["approved", "failed"])
            self.assertEqual([i["branch"] for i in r["unknown"]], ["localharness/task-99"])
            left = workspace.localharness_branches(repo)
            self.assertNotIn(made["done"].branch, left); self.assertNotIn(made["merged"].branch, left)
            self.assertIn(made["failed"].branch, left); self.assertIn("localharness/task-99", left)
            self.assertFalse(made["done"].path.exists())


if __name__ == "__main__":
    unittest.main()
