"""Biblioteca del Catálogo: skills y MCP preparados, plantillas de agente, importar de GitHub y el asistente."""

import json, tempfile, unittest
from pathlib import Path
from unittest import mock

from localharness import context, library
from localharness.context import load_skills
from localharness.orchestrator import win_shim

try:
    from fastapi.testclient import TestClient
    from localharness.api import create_app
except ImportError:  # dependencias del servidor no instaladas
    TestClient = None

SKILL_GH = "---\nname: pdf\ndescription: Trabaja con PDF\nlicense: x\n---\n\n# PDF\nPasos…\n"


class LibraryContentTests(unittest.TestCase):
    """Lo que viene de serie en biblioteca/ tiene que estar bien formado."""

    def test_skills(self):
        skills = library.skill_library()
        self.assertGreaterEqual(len(skills), 20)
        names = [s["name"] for s in skills]
        self.assertEqual(len(names), len(set(names)))
        for s in skills:
            self.assertTrue(s["description"] and s["category"] != "Otras" and s["chars"] > 100, s["name"])
            self.assertEqual(s["name"], context.import_skill.__globals__["re"].sub(r"[^a-z0-9_-]+", "-", s["name"]))

    def test_mcp_entries_validate(self):
        from localharness import settings
        from localharness.store import Store
        s = Store(":memory:"); self.addCleanup(s.close)
        entries = library.mcp_library()
        self.assertGreaterEqual(len(entries), 15)
        for e in entries:
            vals = {p["key"]: "D:/x" for p in e.get("params", [])}
            cfg = library.fill_mcp(e["id"], vals)
            self.assertIsNone(library._PLACEHOLDER.search(json.dumps(cfg)), e["id"])
            settings.save(s, {"mcp_servers": {e["id"]: cfg}})  # pasa la validación de Ajustes

    def test_templates_reference_existing_things(self):
        skills = {s["name"] for s in library.skill_library()} | set(load_skills())
        mcps = {e["id"] for e in library.mcp_library()}
        for t in library.templates():
            self.assertIn(t["role"], ("director", "jefe", "trabajador", "consultas"), t["id"])
            self.assertIn(t["provider"], ("claude", "local"), t["id"])
            self.assertIn(t["local_provider"], ("local", "local_agent"), t["id"])
            self.assertIn(t["local_use"], ("agente con herramientas", "director", "jefe técnico", "consultas"), t["id"])
            self.assertLessEqual(set(t["skills"]), skills, t["id"])
            self.assertLessEqual(set(t["mcps"]), mcps, t["id"])


class LibraryLogicTests(unittest.TestCase):
    def test_fill_mcp(self):
        cfg = library.fill_mcp("github", {"token": " abc "})
        self.assertEqual(cfg["headers"]["Authorization"], "Bearer abc")
        with self.assertRaisesRegex(ValueError, "Token"):
            library.fill_mcp("github", {})
        with self.assertRaises(LookupError):
            library.fill_mcp("no-existe", {})

    def test_added_as(self):
        e = {x["id"]: x for x in library.mcp_library({"mi-fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
                                                      "c7": {"type": "http", "url": "https://mcp.context7.com/mcp"}})}
        self.assertEqual(e["fetch"]["added_as"], ["mi-fetch"])
        self.assertEqual(e["context7"]["added_as"], ["c7"])
        self.assertEqual(e["git"]["added_as"], [])

    def test_parse_github(self):
        p = library.parse_github
        self.assertEqual(p("anthropics/skills")["repo"], "skills")
        g = p("https://github.com/anthropics/skills/tree/main/skills/pdf")
        self.assertEqual((g["ref"], g["path"], g["file"]), ("main", "skills/pdf", False))
        g = p("https://github.com/o/r/blob/dev/a/SKILL.md")
        self.assertEqual((g["ref"], g["path"], g["file"]), ("dev", "a/SKILL.md", True))
        g = p("https://raw.githubusercontent.com/o/r/main/x/SKILL.md")
        self.assertTrue(g["file"])
        with self.assertRaises(ValueError):
            p("https://gitlab.com/o/r")

    def test_github_skills(self):
        tree = {"tree": [{"type": "blob", "path": "skills/pdf/SKILL.md"}, {"type": "blob", "path": "README.md"},
                         {"type": "blob", "path": "skills/sin-front/SKILL.md"}, {"type": "tree", "path": "skills"}]}

        def fake_get(url, timeout=20):
            if url.endswith("/repos/o/r"):
                return json.dumps({"default_branch": "main"}).encode()
            if "/git/trees/main" in url:
                return json.dumps(tree).encode()
            if url.endswith("skills/pdf/SKILL.md"):
                return SKILL_GH.encode()
            if url.endswith("skills/sin-front/SKILL.md"):
                return b"# sin frontmatter"
            raise AssertionError(url)
        with mock.patch.object(library, "_get", fake_get):
            r = library.github_skills("https://github.com/o/r")
        self.assertEqual(r["ref"], "main")
        self.assertEqual([s["name"] for s in r["skills"]], ["pdf"])
        self.assertEqual(r["skills"][0]["category"], "r")
        self.assertIn("blob/main/skills/pdf/SKILL.md", r["skills"][0]["url"])

    def test_with_source(self):
        t = library.with_source(SKILL_GH, "https://github.com/o/r", "Documentos")
        self.assertIn("source: https://github.com/o/r\ncategory: Documentos\n---", t)
        self.assertEqual(library.with_source(t, "otra"), t)  # no se duplica

    def test_win_shim(self):
        self.assertEqual(win_shim({"command": "npx", "args": ["-y", "x"]}, nt=True),
                         {"command": "cmd", "args": ["/c", "npx", "-y", "x"]})
        self.assertEqual(win_shim({"command": "uvx", "args": ["a"]}, nt=True)["command"], "uvx")
        self.assertEqual(win_shim({"command": "npx", "args": []}, nt=False)["command"], "npx")
        self.assertEqual(win_shim({"type": "http", "url": "u"}, nt=True), {"type": "http", "url": "u"})


@unittest.skipIf(TestClient is None, "faltan fastapi/httpx (pip install -e .[server])")
class LibraryApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old = context.IMPORTED_SKILLS
        context.IMPORTED_SKILLS = Path(self.tmp.name) / "skills"
        self.addCleanup(lambda: setattr(context, "IMPORTED_SKILLS", self.old))

    def client(self):
        return TestClient(create_app(Path(self.tmp.name) / "lh.db", web_dist=None))

    def test_library_and_install(self):
        with self.client() as c:
            lib = c.get("/api/library").json()
            self.assertTrue(lib["skills"] and lib["mcps"] and lib["templates"])
            self.assertFalse(next(s for s in lib["skills"] if s["name"] == "tdd")["installed"])
            r = c.post("/api/library/skills/tdd")
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual(r.json()["category"], "Calidad y tests")
            self.assertEqual(c.post("/api/library/skills/tdd").status_code, 409)
            self.assertEqual(c.post("/api/library/skills/nada").status_code, 404)
            self.assertTrue(next(s for s in c.get("/api/library").json()["skills"] if s["name"] == "tdd")["installed"])
            d = c.get("/api/skills/tdd").json()
            self.assertIn("Rojo", d["content"])
            self.assertEqual(c.get("/api/skills/nada").status_code, 404)
            # de serie con categoría
            self.assertEqual(c.get("/api/skills/tests-primero").json()["category"], "Calidad y tests")

    def test_skill_with_source(self):
        with self.client() as c:
            r = c.post("/api/skills", json={"content": SKILL_GH, "source": "https://github.com/o/r", "category": "r"})
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual((r.json()["source"], r.json()["category"]), ("https://github.com/o/r", "r"))

    def test_add_library_mcp(self):
        with self.client() as c:
            self.assertEqual(c.post("/api/library/mcp/github", json={}).status_code, 422)
            r = c.post("/api/library/mcp/github", json={"params": {"token": "t"}})
            self.assertEqual(r.status_code, 201, r.text)
            self.assertEqual(r.json()["server"]["headers"]["Authorization"], "Bearer t")
            self.assertEqual(c.post("/api/library/mcp/github", json={"params": {"token": "t"}}).status_code, 409)
            r = c.post("/api/library/mcp/github", json={"name": "gh2", "params": {"token": "u"}})
            self.assertEqual(r.status_code, 201)
            self.assertEqual(set(c.get("/api/settings").json()["values"]["mcp_servers"]), {"github", "gh2"})
            gh = next(e for e in c.get("/api/library").json()["mcps"] if e["id"] == "github")
            self.assertEqual(gh["added_as"], ["github", "gh2"])  # gh2 tiene la misma URL
            self.assertEqual(c.post("/api/library/mcp/nada", json={}).status_code, 404)

    def test_github_errors(self):
        with self.client() as c:
            self.assertEqual(c.post("/api/library/github", json={"url": "https://gitlab.com/a/b"}).status_code, 422)
            with mock.patch.object(library, "_get", side_effect=OSError("sin red")):
                r = c.post("/api/library/github", json={"url": "o/r"})
            self.assertEqual(r.status_code, 502)

    def test_wizard_agent(self):
        """El asistente crea con instrucciones y plantilla, y al editar puede cambiar de proveedor."""
        with self.client() as c:
            r = c.post("/api/agents", json={"name": "explorador-1", "provider": "local_agent", "role": "consultas",
                                            "model": "Qwen3-8B-Q4_K_M.gguf", "read_only": True, "web": True,
                                            "skills": ["tdd"], "instructions": "  Solo lees.  ", "template": "explorador"})
            self.assertEqual(r.status_code, 201, r.text)
            a = r.json()
            self.assertEqual((a["config"]["instructions"], a["config"]["template"]), ("Solo lees.", "explorador"))
            r = c.patch(f"/api/agents/{a['id']}", json={"provider": "claude", "model": "haiku", "instructions": "",
                                                       "mcps": ["context7"]})
            self.assertEqual(r.status_code, 200, r.text)
            a = r.json()
            self.assertEqual((a["provider"], a["model"]), ("claude", "haiku"))
            self.assertNotIn("instructions", a["config"])
            self.assertEqual(a["config"]["mcps"], ["context7"])
            self.assertEqual(c.patch(f"/api/agents/{a['id']}", json={"provider": "nada"}).status_code, 422)
            r = c.patch(f"/api/agents/{a['id']}", json={"delegate_local": True, "coordinator": True}).json()
            self.assertEqual((r["config"]["delegate_local"], r["config"]["coordinator"]), (True, True))
            r = c.patch(f"/api/agents/{a['id']}", json={"coordinator": False}).json()
            self.assertNotIn("coordinator", r["config"])
            c.post("/api/agents", json={"name": "otro"})
            self.assertEqual(c.patch(f"/api/agents/{a['id']}", json={"name": "otro"}).status_code, 409)
            self.assertEqual(c.patch(f"/api/agents/{a['id']}", json={"name": "investigador"}).json()["name"], "investigador")


if __name__ == "__main__":
    unittest.main()
