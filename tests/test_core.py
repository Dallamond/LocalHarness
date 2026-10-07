import subprocess, tempfile, unittest
from pathlib import Path

from localharness import workspace
from localharness.adapters import get_adapter
from localharness.adapters.base import AdapterError, RunSpec
from localharness.orchestrator import execute_task
from localharness.runner import run
from localharness.store import Store

FAKES = Path(__file__).parent / "fakes"
REAL = Path(__file__).parent / "fixtures_reales"


def make_repo(tmp: str) -> Path:
    repo = Path(tmp) / "repo"
    repo.mkdir()
    # autocrlf fijo: si una prueba quita la config de sistema (en Windows suele ser true), el repo no sale «sucio»
    for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["config", "core.autocrlf", "false"]):
        subprocess.run(["git", *a], cwd=repo, check=True)
    (repo / "README.md").write_text("hola\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


class AdapterTests(unittest.TestCase):
    def test_claude_command_and_parse(self):
        a = get_adapter("claude")
        cmd = a.build_command(RunSpec(prompt="hi", cwd=".", max_turns=3, read_only=True))
        self.assertIn("stream-json", cmd); self.assertIn("--max-turns", cmd)
        self.assertEqual(cmd[1], "-p"); self.assertNotIn("hi", cmd)  # el prompt va por stdin
        self.assertEqual(a.stdin_text(RunSpec(prompt="hi", cwd=".")), "hi")
        self.assertIn("--safe-mode", cmd); self.assertIn("--strict-mcp-config", cmd)  # sin MCP/plugins del usuario
        self.assertNotIn("--safe-mode", get_adapter("claude", isolated=False).build_command(RunSpec(prompt="x", cwd=".")))
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "bypassPermissions")
        self.assertEqual(cmd[cmd.index("--allowedTools") + 1], "Read,Glob,Grep")  # solo lectura
        w = a.build_command(RunSpec(prompt="x", cwd=".", allowed_tools=["Edit", "Bash(git status)"], max_budget_usd=2))
        self.assertEqual(w[w.index("--tools") + 1], "Edit,Bash"); self.assertIn("--max-budget-usd", w)
        evs = a.parse('{"type":"result","subtype":"success","result":"ok","total_cost_usd":0.5}')
        self.assertEqual([e.kind for e in evs], ["usage", "result"])

    def test_codex_command_and_parse(self):
        a = get_adapter("codex")
        cmd = a.build_command(RunSpec(prompt="hi", cwd="/x"))
        self.assertEqual(cmd[:3], ["codex", "exec", "--json"]); self.assertEqual(cmd[-1], "-")
        self.assertIn("workspace-write", cmd)
        self.assertEqual(a.parse('{"type":"item.completed","item":{"type":"agent_message","text":"yo"}}')[0].text, "yo")

    def test_claude_failure_shapes(self):
        a = get_adapter("claude")
        e = a.parse('{"type":"result","subtype":"error_during_execution","is_error":true,"errors":["boom"]}')
        self.assertEqual(e[-1].kind, "error"); self.assertIn("boom", e[-1].text)
        e = a.parse('{"type":"result","subtype":"success","is_error":true,"result":"cuota"}')
        self.assertEqual(e[-1].kind, "error")
        self.assertEqual(a.parse('{"type":"stream_event","event":{}}'), [])

    def test_codex_real_shapes(self):
        a = get_adapter("codex")
        cmd = a.build_command(RunSpec(prompt="hi", cwd="/x"))
        self.assertIn('approval_policy="never"', cmd)
        ev = a.parse('{"type":"item.completed","item":{"type":"commandExecution","command":"ls","exitCode":0,"aggregatedOutput":"a"}}')[0]
        self.assertEqual((ev.kind, ev.data["exit_code"], ev.data["output"]), ("tool", 0, "a"))
        self.assertEqual(a.parse('{"type":"item.completed","item":{"type":"error","message":"x"}}')[0].kind, "error")
        self.assertEqual(a.parse('{"type":"turn.failed","error":{"message":"m"}}')[0].text, "m")
        self.assertEqual(a.parse('{"type":"item.completed","item":{"type":"nuevo"}}')[0].kind, "unknown")
        u = a.parse('{"type":"turn.completed","usage":{"input_tokens":100,"cached_input_tokens":40,"output_tokens":5}}')[0]
        self.assertEqual(u.data["input_uncached"], 60)

    def test_non_json_and_unknown(self):
        a = get_adapter("claude")
        self.assertEqual(a.parse("no json")[0].kind, "raw")
        self.assertEqual(a.parse('{"type":"otra-cosa"}'), [])
        with self.assertRaises(AdapterError):
            get_adapter("nope")


class RealFixtureTests(unittest.TestCase):
    """Salidas capturadas de la CLI real (claude 2.1.287, Windows, 05/10/2026)."""

    def _events(self, name: str):
        a = get_adapter("claude")
        return [e for line in (REAL / name).read_text(encoding="utf-8").splitlines() for e in a.parse(line)]

    def test_claude_real_output(self):
        evs = self._events("claude_real.jsonl")
        self.assertEqual([e.kind for e in evs], ["session", "text", "limit", "usage", "result"])
        self.assertEqual(evs[0].data["tools"], ["Glob", "Grep", "Read"])  # aislado: sin herramientas MCP
        self.assertEqual(evs[0].data["api_key_source"], "none")          # suscripción, no API key
        self.assertEqual(evs[-1].text, "ok")
        self.assertGreater(evs[2].data["seven_day"], 0)
        self.assertLess(evs[3].data["cost_usd"], 0.1)

    def test_tools_flag_is_hard_limit(self):
        evs = self._events("claude_limite_tools.jsonl")
        self.assertEqual(evs[0].data["tools"], ["Read"])
        self.assertNotIn("Write", [e.text for e in evs if e.kind == "tool"])


class BinaryResolutionTests(unittest.TestCase):
    def test_npm_shim_resolves_to_exe(self):
        from localharness.binaries import resolve
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "node_modules" / "@x" / "cli" / "bin" / "tool.exe"
            exe.parent.mkdir(parents=True); exe.write_bytes(b"MZ")
            shim = Path(tmp) / "tool.cmd"
            shim.write_text('@ECHO off\r\nSETLOCAL\r\n"%dp0%\\node_modules\\@x\\cli\\bin\\tool.exe"   %*\r\n')
            self.assertEqual(Path(resolve(str(shim))[0]).resolve(), exe.resolve())

    def test_python_script_uses_interpreter(self):
        import sys
        from localharness.binaries import resolve
        self.assertEqual(resolve(str(FAKES / "claude")), [sys.executable, str(FAKES / "claude")])
        self.assertEqual(resolve("no-existe-xyz"), ["no-existe-xyz"])


class WorkspaceTests(unittest.TestCase):
    def test_worktree_diff_merge_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            ws = workspace.create(repo, 7, Path(tmp) / "wt")
            (ws.path / "nuevo.txt").write_text("a\n")
            self.assertIn("nuevo.txt", ws.diff())
            self.assertFalse((repo / "nuevo.txt").exists())  # aislado hasta aprobar
            ws.checkpoint("t")
            ws.merge("main")
            self.assertTrue((repo / "nuevo.txt").exists())
            ws.remove()


class WorkspaceEncodingTests(unittest.TestCase):
    def test_diff_keeps_utf8(self):
        # en Windows git devuelve UTF-8 y text=True lo leía como cp1252 («Ã¡»): el revisor veía texto roto
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            ws = workspace.create(repo, 3, Path(tmp) / "wt")
            (ws.path / "señal.txt").write_text("pequeño café €\n", encoding="utf-8")
            d = ws.diff()
            self.assertIn("pequeño café €", d); self.assertIn("señal.txt", d)


class WorkspaceRobustnessTests(unittest.TestCase):
    def test_stale_leftovers_do_not_block_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp); root = Path(tmp) / "wt"
            ws = workspace.create(repo, 1, root)
            # simula un cuelgue: el directorio desaparece sin `worktree remove`
            import shutil; shutil.rmtree(ws.path)
            ws2 = workspace.create(repo, 1, root)  # misma ruta y rama: debe recuperarse
            self.assertTrue(ws2.path.exists())

    def test_node_modules_symlink_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            (repo / "node_modules").mkdir(); (repo / "node_modules" / "x.js").write_text("1")
            (repo / ".gitignore").write_text("node_modules/\n")  # barra final: NO cubre un symlink
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "ign"], cwd=repo, check=True)
            ws = workspace.create(repo, 2, Path(tmp) / "wt", link_node_modules=True)
            if not (ws.path / "node_modules").is_symlink():
                self.skipTest("symlinks no permitidos")
            self.assertNotIn("node_modules", ws.diff())


class SubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_key_is_removed_for_claude_but_not_if_allowed(self):
        import os, textwrap
        from localharness.adapters.claude import ClaudeAdapter, login_method
        self.assertEqual(login_method(str(FAKES / "claude")), "claude.ai")
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "claude"
            probe.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json, os
                print(json.dumps({"type": "result", "subtype": "success", "result": os.environ.get("ANTHROPIC_API_KEY", "AUSENTE")}))
            """)); probe.chmod(0o755)
            os.environ["ANTHROPIC_API_KEY"] = "sk-test"
            try:
                for allow, expected in ((False, "AUSENTE"), (True, "sk-test")):
                    evs = []
                    await run(ClaudeAdapter(binary=str(probe), allow_api_key=allow), RunSpec(prompt="x", cwd=tmp), evs.append)
                    self.assertEqual([e.text for e in evs if e.kind == "result"], [expected])
            finally:
                del os.environ["ANTHROPIC_API_KEY"]


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_with_shell_metacharacters_arrives_intact(self):
        import textwrap
        prompt = 'a & b | c % PATH % ^ "comillas" <x>\nlínea 2 ñ €'
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "claude"
            probe.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json, sys
                sys.stdin.reconfigure(encoding="utf-8")
                print(json.dumps({"type": "result", "subtype": "success", "result": sys.stdin.read()}))
            """), encoding="utf-8")
            evs = []
            await run(get_adapter("claude", binary=str(probe)), RunSpec(prompt=prompt, cwd=tmp), evs.append)
            self.assertEqual([e.text for e in evs if e.kind == "result"], [prompt])

    async def test_failure_with_exit_zero(self):
        evs = []
        res = await run(get_adapter("claude", binary=str(FAKES / "claude")),
                        RunSpec(prompt="x", cwd=".", extra_args=["--fail-result"]), evs.append)
        self.assertEqual(res["exit_code"], 0); self.assertEqual(res["status"], "failed")

    async def test_failure_exit_code(self):
        evs = []
        res = await run(get_adapter("claude", binary=str(FAKES / "claude")),
                        RunSpec(prompt="x", cwd=".", extra_args=["--boom"]), evs.append)
        self.assertEqual(res["status"], "failed"); self.assertEqual(res["exit_code"], 3)

    async def test_missing_binary(self):
        evs = []
        res = await run(get_adapter("claude", binary="/no/existe"), RunSpec(prompt="x", cwd="."), evs.append)
        self.assertEqual(res["status"], "failed"); self.assertEqual(evs[0].kind, "error")


class EndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, provider: str, fake: str, expect_file: str):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            store = Store()
            p = store.add_project("demo", str(repo))
            ag = store.add_agent(provider, provider, model="fake")
            t = store.add_task(p["id"], "crear archivo", "crea un archivo", ag["id"])
            res = await execute_task(store, t["id"], binaries={provider: str(FAKES / fake)},
                                     worktree_root=str(Path(tmp) / "wt"))
            self.assertEqual(res["status"], "review")
            self.assertIn(expect_file, res["diff"])
            self.assertFalse((repo / expect_file).exists())  # nada en main sin aprobación
            task = store.get_task(t["id"])
            self.assertEqual(task["status"], "review"); self.assertTrue(task["session_id"])
            kinds = [e["kind"] for e in store.list_events(t["id"])]
            self.assertIn("session", kinds); self.assertIn("text", kinds)
            return task

    async def test_claude_e2e(self):
        task = await self._run("claude", "claude", "hola.txt")
        self.assertEqual(task["final"], "Hecho"); self.assertEqual(task["cost_usd"], 0.01)

    async def test_codex_e2e(self):
        await self._run("codex", "codex", "codex.txt")


if __name__ == "__main__":
    unittest.main()
