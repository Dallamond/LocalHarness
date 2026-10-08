"""Pensamiento activable (DISENO-OFICINA §5): apagado / normal / profundo por agente, rol, paso y conversación."""

import tempfile, unittest
from pathlib import Path

from localharness import orchestrator
from localharness.adapters.base import RunSpec
from localharness.adapters.claude import ClaudeAdapter
from localharness.adapters.local import thinking_body
from localharness.hierarchy import validate_plan
from localharness.store import Store
from tests.test_core import FAKES, make_repo

FAKE = str(FAKES / "claude")


class ThinkingTests(unittest.TestCase):
    def test_claude_effort_flag(self):
        cmd = lambda lvl: ClaudeAdapter().build_command(RunSpec(prompt="x", cwd=".", thinking=lvl))
        self.assertEqual(cmd("profundo")[cmd("profundo").index("--effort") + 1], "high")
        self.assertEqual(cmd("apagado")[cmd("apagado").index("--effort") + 1], "low")
        self.assertNotIn("--effort", cmd("normal")); self.assertNotIn("--effort", cmd(None))  # lo de siempre

    def test_local_template_switch(self):
        self.assertEqual(thinking_body("apagado"),
                         {"chat_template_kwargs": {"enable_thinking": False, "reasoning_effort": "low"}})
        self.assertEqual(thinking_body("profundo"),
                         {"chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "high"}})
        self.assertEqual(thinking_body("normal"), {}); self.assertEqual(thinking_body(None), {})
        # el encargo pide poco razonamiento (gpt-oss) salvo que el servidor diga otra cosa
        self.assertEqual(thinking_body("normal", "low"), {"chat_template_kwargs": {"reasoning_effort": "low"}})
        self.assertEqual(thinking_body("apagado", "medium")["chat_template_kwargs"]["reasoning_effort"], "low")

    def test_plan_step_thinking_is_validated(self):
        agents = [{"id": 1, "name": "w"}]
        steps = [{"title": "a", "prompt": "p", "agent": "w", "risk": "low", "thinking": "profundo"},
                 {"title": "b", "prompt": "p", "agent": "w", "risk": "low", "thinking": "muchísimo"}]
        data = validate_plan({"summary": "", "risk": "low", "subtasks": steps}, agents)
        self.assertEqual(data["subtasks"][0]["thinking"], "profundo"); self.assertNotIn("thinking", data["subtasks"][1])


class ThinkingInTaskTests(unittest.IsolatedAsyncioTestCase):
    async def run_task(self, agent_cfg: dict, task_thinking: str | None):
        seen, real = [], orchestrator.run

        async def spy(adapter, spec, *a, **kw):
            seen.append((adapter, spec))
            return await real(adapter, spec, *a, **kw)
        orchestrator.run = spy
        try:
            with tempfile.TemporaryDirectory() as tmp:
                s = Store()
                p = s.add_project("demo", str(make_repo(tmp)))
                a = s.add_agent("w", "claude", config={"binary": FAKE, **agent_cfg})
                t = s.add_task(p["id"], "x", "crea el archivo x.txt", a["id"])
                if task_thinking:
                    s.update_task(t["id"], thinking=task_thinking)
                await orchestrator.execute_task(s, t["id"], worktree_root=str(Path(tmp) / "wt"))
        finally:
            orchestrator.run = real
        return seen[0][1]

    async def test_task_overrides_agent_and_apagado_sets_env(self):
        spec = await self.run_task({"thinking": "profundo"}, None)
        self.assertEqual(spec.thinking, "profundo"); self.assertNotIn("MAX_THINKING_TOKENS", spec.env)
        spec = await self.run_task({"thinking": "profundo"}, "apagado")  # la conversación manda sobre el agente
        self.assertEqual((spec.thinking, spec.env.get("MAX_THINKING_TOKENS")), ("apagado", "0"))
        spec = await self.run_task({}, None)
        self.assertIsNone(spec.thinking)
