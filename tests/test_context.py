import json, tempfile, textwrap, unittest
from pathlib import Path

from localharness.context import build_prompt, load_memory, load_skills, parse_skill
from localharness.orchestrator import execute_task
from localharness.store import Store
from tests.test_core import make_repo


class ContextTests(unittest.TestCase):
    def test_builtin_skills_parse(self):
        skills = load_skills()
        self.assertIn("tests-primero", skills)
        self.assertTrue(skills["tests-primero"].description)
        self.assertNotIn("---", skills["tests-primero"].body[:5])  # sin frontmatter

    def test_skill_without_frontmatter_uses_folder_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "mi-skill" / "SKILL.md"
            f.parent.mkdir(); f.write_text("Haz X.", encoding="utf-8")
            self.assertEqual(parse_skill(f).name, "mi-skill")

    def test_build_prompt(self):
        s = load_skills()["cambios-minimos"]
        text, info = build_prompt("arregla X", [("decisiones.md", "Usamos tabs.")], [s])
        self.assertTrue(text.endswith("## Tarea\narregla X"))
        self.assertIn("Usamos tabs.", text); self.assertIn("Skill: cambios-minimos", text)
        self.assertEqual([m["file"] for m in info["memory"]], ["decisiones.md"])
        self.assertEqual([x["name"] for x in info["skills"]], ["cambios-minimos"])
        self.assertEqual(build_prompt("solo", [], [])[0], "solo")  # sin contexto, intacto

    def test_memory_reads_md_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.md").write_text("A", encoding="utf-8")
            (Path(tmp) / "b.txt").write_text("B", encoding="utf-8")
            self.assertEqual(load_memory(tmp), [("a.md", "A")])
            self.assertEqual(load_memory(None), [])


class InjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_task_with_and_without_skill_differs_and_is_logged(self):
        """Aceptación de M5: la misma tarea con y sin skill produce prompts distintos y el registro lo dice."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            probe = Path(tmp) / "probe"  # CLI falsa que guarda el prompt recibido en un archivo del repo
            probe.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json, sys
                sys.stdin.reconfigure(encoding="utf-8")
                open("prompt.txt", "w", encoding="utf-8").write(sys.stdin.read())
                print(json.dumps({"type": "result", "subtype": "success", "result": "ok"}))
            """), encoding="utf-8")
            mem = Path(tmp) / "memoria"; mem.mkdir()
            (mem / "convenciones.md").write_text("Todo en español.", encoding="utf-8")
            store = Store()
            pid = store.add_project("demo", str(repo))["id"]
            store.set_project_memory(pid, str(mem))
            aid = store.add_agent("w", "claude", config={"binary": str(probe)})["id"]
            prompts, contexts = [], []
            for skills in ([], ["tests-primero"]):
                t = store.add_task(pid, "x", "arregla suma", aid, skills=skills)
                await execute_task(store, t["id"], worktree_root=str(Path(tmp) / "wt"))
                wt = Path(store.get_task(t["id"])["worktree"])
                prompts.append((wt / "prompt.txt").read_text(encoding="utf-8"))
                contexts.append([json.loads(e["data"]) for e in store.list_events(t["id"]) if e["kind"] == "context"])
            self.assertNotEqual(prompts[0], prompts[1])
            self.assertIn("Todo en español.", prompts[0]); self.assertNotIn("Skill: tests-primero", prompts[0])
            self.assertIn("Skill: tests-primero", prompts[1])
            self.assertEqual([s["name"] for s in contexts[1][0]["skills"]], ["tests-primero"])
            self.assertEqual(contexts[0][0]["skills"], [])
            store.close()


if __name__ == "__main__":
    unittest.main()
