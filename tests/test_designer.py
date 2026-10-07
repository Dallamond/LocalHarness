"""Agentes a medida: el diseñador propone (Claude falso o reglas), se limpia y se guarda como agente generado."""

import json
import tempfile
import unittest

from localharness import designer, roles
from localharness.store import Store
from tests.test_core import FAKES, make_repo

FAKE = str(FAKES / "claude")  # NUNCA la CLI real


class DesignerTests(unittest.IsolatedAsyncioTestCase):
    async def test_claude_proposal_is_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store()
            p = s.add_project("demo", str(make_repo(tmp)))
            spec = await designer.design(s, "arregla la calculadora", p, binary=FAKE, local_ready=True)
            self.assertEqual(spec["designed_by"], "claude")
            self.assertEqual((spec["provider"], spec["model"], spec["coordinator"]), ("claude", "sonnet", True))
            self.assertEqual(spec["skills"], ["cambios-minimos"])        # «no-existe» fuera
            self.assertEqual(spec["local_skills"], ["tests-primero"])
            self.assertEqual(spec["mcps"], [])                           # «inventado» fuera
            self.assertEqual((spec["max_turns"], spec["name"]), (40, "arreglar-calc"))  # topes y nombre limpio
            # sin modelo local no puede coordinar (no tendría a quién encargar)
            off = await designer.design(s, "arregla la calculadora", p, binary=FAKE, local_ready=False)
            self.assertEqual((off["coordinator"], off["local_skills"]), (False, []))

    async def test_without_claude_falls_back_to_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Store()
            p = s.add_project("demo", str(make_repo(tmp)))
            spec = await designer.design(s, "explica qué hace el módulo de pagos", p, binary="/no/existe/claude")
            self.assertEqual(spec["designed_by"], "reglas")
            self.assertEqual((spec["read_only"], spec["model"]), (True, "haiku"))
            fix = await designer.design(s, "arregla el fallo de la suma y añade tests", p, binary="/no/existe",
                                        local_ready=True)
            self.assertTrue(fix["coordinator"])
            self.assertIn("depurar-sistematico", fix["local_skills"] + fix["skills"])

    def test_create_agent_is_generated_and_unique(self):
        s = Store()
        spec = designer.normalize({"name": "arreglar", "provider": "claude", "model": "haiku", "skills": []},
                                  {"skills": {}, "mcps": {}}, False)
        a = designer.create_agent(s, {**spec, "reason": "porque sí", "designed_by": "claude"}, "arregla x")
        b = designer.create_agent(s, spec, "arregla y")
        self.assertEqual((a["name"], b["name"]), ("arreglar", "arreglar-2"))
        cfg = json.loads(a["config"])
        self.assertEqual((cfg["generated"], cfg["designed_for"], cfg["design_reason"]), (True, "arregla x", "porque sí"))


class RetireRolesTests(unittest.TestCase):
    def test_role_agents_are_removed_or_retired(self):
        s = Store()
        p = s.add_project("demo", "/x")
        unused = s.add_agent("revisor", "claude", config={"from_role": "revisor"})
        used = s.add_agent("programador", "claude", config={"from_role": "programador"})
        mine = s.add_agent("mio", "claude")
        s.add_task(p["id"], "t", "t", used["id"])
        log = roles.retire_role_agents(s)
        self.assertEqual(len(log), 2)
        self.assertIsNone(s.get_agent(unused["id"]))                        # sin historial: fuera
        cfg = json.loads(s.get_agent(used["id"])["config"])
        self.assertEqual((cfg["off"], cfg["retired"]), (True, True))        # con historial: fuera de servicio
        self.assertIsNotNone(s.get_agent(mine["id"]))                       # los tuyos no se tocan
        s.update_agent(used["id"], config={**cfg, "off": False})            # si lo vuelves a llamar, se queda
        self.assertEqual(roles.retire_role_agents(s), [])


if __name__ == "__main__":
    unittest.main()
