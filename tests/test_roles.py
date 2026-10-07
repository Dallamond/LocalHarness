"""Objetivo 5: catálogo de roles (roles/*.md) que se sincronizan como agentes."""

import json, tempfile, unittest
from pathlib import Path

from localharness import roles
from localharness.orchestrator import execute_task
from localharness.store import Store
from tests.test_core import FAKES, make_repo

FAKE = str(FAKES / "claude")
ROLE = """---
name: probador
description: Prueba cosas
provider: claude
model: haiku
role: trabajador
read_only: false
max_turns: 7
max_budget_usd: 0.25
skills: [cambios-minimos, tests-primero]
---
Comprueba siempre con tests.
"""


class RolesTests(unittest.TestCase):
    def test_builtin_roles_parse(self):
        got = roles.load_roles([roles.BUILTIN_ROLES])
        self.assertEqual(sorted(got), ["coordinador", "explorador", "programador", "programador-local", "revisor"])
        self.assertEqual((got["explorador"].provider, got["explorador"].config["read_only"]), ("local_agent", True))
        self.assertEqual(got["programador"].config["skills"], ["cambios-minimos"])
        self.assertTrue(got["programador"].config["delegate_local"])
        self.assertTrue(got["coordinador"].config["coordinator"])

    def test_sync_creates_updates_and_respects_own_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "probador.md").write_text(ROLE, encoding="utf-8")
            (d / "roto.md").write_text("sin frontmatter", encoding="utf-8")
            s = Store()
            log = roles.sync_roles(s, roles.load_roles([d]))
            a = s.find_agent("probador")
            cfg = json.loads(a["config"])
            self.assertEqual((a["provider"], a["model"], a["role"]), ("claude", "haiku", "trabajador"))
            self.assertEqual((cfg["max_turns"], cfg["max_budget_usd"], cfg["skills"], cfg["from_role"]),
                             (7, 0.25, ["cambios-minimos", "tests-primero"], "probador"))
            self.assertEqual(cfg["instructions"], "Comprueba siempre con tests.")
            self.assertIs(cfg["read_only"], False)  # los false se guardan (p. ej. web: false apaga internet)
            self.assertEqual(log, ["rol probador: agente creado"])
            self.assertEqual(roles.sync_roles(s, roles.load_roles([d])), [])  # sin cambios: nada que hacer
            (d / "probador.md").write_text(ROLE.replace("model: haiku", "model: sonnet"), encoding="utf-8")
            self.assertIn("actualizado", roles.sync_roles(s, roles.load_roles([d]))[0])
            self.assertEqual(s.find_agent("probador")["model"], "sonnet")
            # un agente tuyo con el mismo nombre no se toca
            s2 = Store()
            s2.add_agent("probador", "local", config={"temperature": 0.5})
            self.assertIn("no se toca", roles.sync_roles(s2, roles.load_roles([d]))[0])
            self.assertEqual(s2.find_agent("probador")["provider"], "local")


class RoleInstructionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_role_instructions_reach_the_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "roles"
            d.mkdir()
            (d / "probador.md").write_text(ROLE, encoding="utf-8")
            repo = make_repo(tmp)
            s = Store()
            roles.sync_roles(s, roles.load_roles([d]))
            a = s.find_agent("probador")
            s.update_agent(a["id"], config={**json.loads(a["config"]), "binary": FAKE})
            p = s.add_project("demo", str(repo))
            t = s.add_task(p["id"], "x", "crea el archivo x.txt", a["id"])
            from localharness import orchestrator
            seen, real = [], orchestrator.run

            async def spy(adapter, spec, *a, **kw):
                seen.append(spec)
                return await real(adapter, spec, *a, **kw)
            orchestrator.run = spy
            try:
                await execute_task(s, t["id"], worktree_root=str(Path(tmp) / "wt"))
            finally:
                orchestrator.run = real
            ctx = [e for e in s.list_events(t["id"]) if e["kind"] == "context"]
            self.assertEqual([x["name"] for x in json.loads(ctx[0]["data"])["skills"]], ["cambios-minimos", "tests-primero"])
            self.assertIn("## Tu rol en el equipo\nComprueba siempre con tests.", seen[0].prompt)
            self.assertEqual((seen[0].model, seen[0].max_turns, seen[0].max_budget_usd), ("haiku", 7, 0.25))
