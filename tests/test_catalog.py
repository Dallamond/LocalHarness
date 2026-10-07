"""Catálogo de la oficina: servidores MCP por agente, herramientas web, importar skills y recursos."""

import json, shutil, tempfile, unittest
from pathlib import Path

from localharness import context, settings
from localharness.adapters import get_adapter
from localharness.adapters.base import RunSpec
from localharness.orchestrator import _mcp_setup, delegate_guide, win_shim
from localharness.store import Store
from tests.test_core import make_repo

try:
    from fastapi.testclient import TestClient
    from localharness.api import create_app
except ImportError:  # dependencias del servidor no instaladas
    TestClient = None

SKILL = "---\nname: resumen-semanal\ndescription: Resume la semana\n---\n\n1. Lee el journal\n2. Resume\n"


class McpCatalogTests(unittest.TestCase):
    def test_validation(self):
        s = Store(":memory:"); self.addCleanup(s.close)
        v = settings.save(s, {"mcp_servers": {
            "memory": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"]},
            "docs": {"url": "https://ejemplo.com/mcp", "description": "docs remotas"}}})["mcp_servers"]
        self.assertEqual(v["memory"]["args"][0], "-y")
        self.assertEqual(v["docs"], {"type": "http", "url": "https://ejemplo.com/mcp", "description": "docs remotas"})
        # se guarda entero: quitar un servidor funciona (no se mezcla con lo anterior)
        v = settings.save(s, {"mcp_servers": {"docs": {"url": "https://ejemplo.com/mcp"}}})["mcp_servers"]
        self.assertEqual(list(v), ["docs"])
        settings.reset(s)  # restablecer los ajustes no borra el catálogo
        self.assertEqual(list(settings.load(s)["mcp_servers"]), ["docs"])
        for bad in ({"local": {"command": "x"}}, {"a b": {"command": "x"}}, {"x": {}}, {"x": "npx"}):
            with self.assertRaises(ValueError):
                settings.save(s, {"mcp_servers": bad})

    def test_agent_mcp_config(self):
        s = Store(":memory:"); self.addCleanup(s.close)
        settings.save(s, {"mcp_servers": {"memory": {"command": "npx", "args": ["m"], "description": "solo GUI"}}})
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_mcp_setup(s, Path(tmp), {}, write=True))
            m = _mcp_setup(s, Path(tmp), {"mcps": ["memory", "nada"]}, write=True)
            try:
                cfg = json.loads(Path(m["config"]).read_text(encoding="utf-8"))["mcpServers"]
                self.assertEqual(cfg, {"memory": win_shim({"command": "npx", "args": ["m"]})})  # sin la descripción
                self.assertEqual(m["tools"], ["mcp__memory"])
                self.assertEqual(m["missing"], ["nada"])
                self.assertFalse(m["delegate"])
            finally:
                shutil.rmtree(m["dir"])
            m = _mcp_setup(s, Path(tmp), {"mcps": ["memory"], "delegate_local": True}, write=False)
            try:
                cfg = json.loads(Path(m["config"]).read_text(encoding="utf-8"))["mcpServers"]
                self.assertEqual(sorted(cfg), ["local", "memory"])
                self.assertEqual(m["tools"], ["mcp__local__local_prepare", "mcp__local__local_ask",
                                              "mcp__local__run_checks", "mcp__local__local_research",
                                              "mcp__memory"])  # solo lectura: sin write_file ni local_agent
            finally:
                shutil.rmtree(m["dir"])

    def test_web_tools_and_guide(self):
        cmd = get_adapter("claude", binary="claude").build_command(
            RunSpec(prompt="x", cwd=".", read_only=True, extra_tools=["WebFetch", "WebSearch"]))
        self.assertIn("Read,Glob,Grep,WebFetch,WebSearch", cmd[cmd.index("--tools") + 1])
        self.assertIn("local_write_file", delegate_guide(True))
        self.assertNotIn("local_write_file` con", delegate_guide(False))


class SkillImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = context.IMPORTED_SKILLS
        context.IMPORTED_SKILLS = Path(self.tmp.name) / "skills"

    def tearDown(self):
        context.IMPORTED_SKILLS = self.old
        self.tmp.cleanup()

    def test_import_and_delete(self):
        sk = context.import_skill(SKILL)
        self.assertEqual(sk.name, "resumen-semanal")
        self.assertTrue(context.load_skills()["resumen-semanal"].summary()["imported"])
        with self.assertRaises(FileExistsError):
            context.import_skill(SKILL)
        context.import_skill(SKILL.replace("Resume\n", "Resume en 5 viñetas\n"), overwrite=True)
        self.assertIn("5 viñetas", context.load_skills()["resumen-semanal"].body)
        with self.assertRaises(FileExistsError):  # una de serie no se pisa
            context.import_skill("---\nname: tests-primero\n---\nx", overwrite=True)
        with self.assertRaises(PermissionError):
            context.delete_skill("tests-primero")
        context.delete_skill("resumen-semanal")
        self.assertNotIn("resumen-semanal", context.load_skills())
        with self.assertRaises(ValueError):
            context.import_skill("sin frontmatter")

    @unittest.skipIf(TestClient is None, "faltan fastapi/httpx (pip install -e .[server])")
    def test_api(self):
        repo = make_repo(self.tmp.name)
        with TestClient(create_app(Path(self.tmp.name) / "lh.db", web_dist=None)) as c:
            r = c.post("/api/skills", json={"content": SKILL})
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual(c.post("/api/skills", json={"content": SKILL}).status_code, 409)
            self.assertEqual(c.delete("/api/skills/tests-primero").status_code, 409)
            self.assertEqual(c.delete("/api/skills/resumen-semanal").status_code, 204)
            a = c.post("/api/agents", json={"name": "web", "provider": "claude", "web": True, "mcps": ["memory"]})
            self.assertEqual(a.json()["config"], {"web": True, "mcps": ["memory"]})
            a = c.patch(f"/api/agents/{a.json()['id']}", json={"web": False, "mcps": []}).json()
            self.assertEqual(a["config"], {"web": False})  # web=False se guarda: en el agente local apaga internet
            c.post("/api/projects", json={"name": "demo", "repo_path": str(repo)})
            res = c.get("/api/resources").json()
            self.assertIsInstance(res["gpus"], list)
            self.assertEqual(res["worktrees"], [])


class OfficeTests(unittest.TestCase):
    def test_layout_setting_and_off_agents(self):
        from localharness import settings
        from localharness.store import Store
        s = Store(":memory:")
        settings.save(s, {"office_layout": {"a3": [2.5, -1, 5], "you": [0, -5, 0]}})
        self.assertEqual(settings.load(s)["office_layout"]["a3"], [2.5, -1.0, 1])  # giro en cuartos de vuelta
        with self.assertRaises(ValueError):
            settings.save(s, {"office_layout": {"../x": [0, 0, 0]}})
        settings.reset(s)
        self.assertIn("a3", settings.load(s)["office_layout"])  # restablecer no deshace tu oficina

    def test_director_skips_agents_out_of_service(self):
        from localharness.hierarchy import Hierarchy
        from localharness.store import Store
        s = Store(":memory:")
        a = s.add_agent("w1", "claude", config={})
        s.add_agent("w2", "claude", config={"off": True})
        h = Hierarchy.__new__(Hierarchy)
        h.store = s
        names = [w["name"] for w in h._workers({"director_agent_id": None, "reviewer_agent_id": None})]
        self.assertEqual(names, ["w1"])
        self.assertTrue(a)

