"""Bucle de agente local (`local_agent`): herramientas confinadas, internet, fallos de modelos pequeños."""

import json, tempfile, unittest
from pathlib import Path

from localharness.adapters.base import RunSpec
from localharness.runner import run
from localharness.store import Store
from tests.test_core import make_repo
from tests.test_delegate import DDG, PAGE

try:
    import httpx
    from localharness.adapters.local_agent import LocalAgentAdapter, _json_call
except ImportError:
    httpx = None


def tool_call(name: str, args: dict | str, i: int = 0) -> dict:
    return {"id": f"c{i}", "type": "function",
            "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


def llama(script: list[dict], seen: list):
    """llama-server falso: devuelve en orden los mensajes de `script` (uno por turno)."""
    def handler(request):
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "D:/m/Qwen3.5-9B-Q4_K_M.gguf"}]})
        seen.append(json.loads(request.content))
        msg = script[min(len(seen), len(script)) - 1]
        return httpx.Response(200, json={"choices": [{"message": msg, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                                         "timings": {"predicted_per_second": 38.5}})
    return httpx.MockTransport(handler)


def web(url, data):
    return DDG if data else PAGE


@unittest.skipIf(httpx is None, "falta httpx (pip install -e .[server])")
class LocalAgentTests(unittest.IsolatedAsyncioTestCase):
    async def go(self, script, prompt="tarea", read_only=False, **kw):
        seen, evs = [], []
        tmp = tempfile.mkdtemp()
        repo = make_repo(tmp)
        a = LocalAgentAdapter(transport=llama(script, seen), http_get=web, **kw)
        res = await run(a, RunSpec(prompt=prompt, cwd=str(repo), read_only=read_only), evs.append)
        return res, evs, seen, repo

    async def test_reads_searches_web_writes_and_finishes(self):
        res, evs, seen, repo = await self.go([
            {"content": "", "tool_calls": [tool_call("leer_archivo", {"ruta": "README.md"})]},
            {"content": "", "tool_calls": [tool_call("buscar_web", {"consulta": "python tomllib"})]},
            {"content": "", "tool_calls": [tool_call("leer_url", {"url": "https://docs.python.org/3/library/tomllib.html"})]},
            {"content": "", "reasoning_content": "Ya sé la versión.",
             "tool_calls": [tool_call("escribir_archivo", {"ruta": "notas/toml.md", "contenido": "Desde 3.11"})]},
            {"content": "", "tool_calls": [tool_call("terminar", {"resumen": "Apuntado en notas/toml.md",
                                                                  "comprobacion": "leí la documentación"})]},
        ])
        self.assertEqual(res["status"], "done")
        self.assertIn("Apuntado en notas/toml.md", res["final"]); self.assertIn("Comprobación: leí", res["final"])
        self.assertEqual((repo / "notas/toml.md").read_text(), "Desde 3.11\n")
        self.assertEqual([e.text for e in evs if e.kind == "tool"],
                         ["leer_archivo", "buscar_web", "leer_url", "escribir_archivo"])
        self.assertIn("thinking", [e.kind for e in evs])
        self.assertEqual(seen[0]["tools"][0]["function"]["name"], "leer_archivo")
        results = [m for m in seen[-1]["messages"] if m["role"] == "tool"]
        self.assertIn("docs.python.org/3/library/tomllib.html", results[1]["content"])  # resultados del buscador
        self.assertIn("Nuevo en la versión 3.11.", results[2]["content"])                # texto de la página
        usage = next(e for e in evs if e.kind == "usage")
        self.assertEqual((usage.data["turns"], usage.data["tps"], usage.data["cost_usd"]), (5, 38.5, 0.0))
        self.assertEqual(evs[0].data["model"], "Qwen3.5-9B-Q4_K_M")

    async def test_confined_to_worktree_and_read_only(self):
        res, evs, seen, repo = await self.go([
            {"content": "", "tool_calls": [tool_call("leer_archivo", {"ruta": "../../etc/passwd"}, 0),
                                           tool_call("leer_archivo", {"ruta": ".git/config"}, 1),
                                           tool_call("escribir_archivo", {"ruta": "x.py", "contenido": "1"}, 2)]},
            {"content": "", "tool_calls": [tool_call("terminar", {"resumen": "no pude"})]},
        ], read_only=True)
        out = [m["content"] for m in seen[1]["messages"] if m["role"] == "tool"]
        self.assertIn("fuera del repositorio", out[0]); self.assertIn("no se toca .git", out[1])
        self.assertIn("herramienta desconocida", out[2])  # en solo lectura no existe escribir_archivo
        self.assertFalse((repo / "x.py").exists())
        self.assertNotIn("escribir_archivo", [t["function"]["name"] for t in seen[0]["tools"]])

    async def test_bad_arguments_get_an_error_and_it_retries(self):
        res, evs, seen, _ = await self.go([
            {"content": "", "tool_calls": [tool_call("leer_archivo", "{ruta: README")]},
            {"content": "", "tool_calls": [tool_call("terminar", {"resumen": "hecho"})]},
        ])
        self.assertEqual(res["status"], "done")
        self.assertIn("no son un JSON válido", [m for m in seen[1]["messages"] if m["role"] == "tool"][0]["content"])

    async def test_repeated_call_is_a_loop(self):
        same = {"content": "", "tool_calls": [tool_call("listar", {"carpeta": "."})]}
        res, evs, seen, _ = await self.go([same] * 5)
        self.assertEqual(res["status"], "failed"); self.assertEqual(len(seen), 3)
        self.assertIn("repite la misma llamada", [e.text for e in evs if e.kind == "error"][0])

    async def test_text_without_tools_is_nudged_then_accepted(self):
        res, evs, seen, _ = await self.go([{"content": "La respuesta es 42."}] * 3)
        self.assertEqual((res["status"], res["final"]), ("done", "La respuesta es 42."))
        self.assertEqual(len(seen), 2)  # un recordatorio y se acepta
        self.assertIn("Usa una herramienta", seen[1]["messages"][-1]["content"])

    async def test_turn_limit_and_long_outputs_are_cut(self):
        script = [{"content": "", "tool_calls": [tool_call("listar", {"carpeta": c})]} for c in (".", "tests", ".")]
        seen, evs = [], []
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            a = LocalAgentAdapter(transport=llama(script, seen), http_get=web, max_tool_chars=5)
            res = await run(a, RunSpec(prompt="t", cwd=str(repo), max_turns=2), evs.append)
        self.assertEqual((res["status"], len(seen)), ("failed", 2))
        self.assertIn("Tope de turnos (2)", [e.text for e in evs if e.kind == "error"][0])
        self.assertIn("[… recortado", [m for m in seen[1]["messages"] if m["role"] == "tool"][0]["content"])

    async def test_json_mode_for_models_without_tool_calls(self):
        res, evs, seen, _ = await self.go([
            {"content": '```json\n{"herramienta": "buscar_texto", "argumentos": {"texto": "resta"}}\n```'},
            {"content": '{"herramienta": "terminar", "argumentos": {"resumen": "encontrado"}}'},
        ], tool_mode="json")
        self.assertEqual((res["status"], res["final"]), ("done", "encontrado"))
        self.assertNotIn("tools", seen[0]); self.assertEqual(seen[0]["response_format"]["type"], "json_schema")
        self.assertIn("FORMATO OBLIGATORIO", seen[0]["messages"][0]["content"])
        self.assertIn("RESULTADO DE buscar_texto", seen[1]["messages"][-1]["content"])

    async def test_ejecutar_only_whitelisted_commands(self):
        res, evs, seen, repo = await self.go([
            {"content": "", "tool_calls": [tool_call("ejecutar", {"comando": "python -m unittest"}, 0),
                                           tool_call("ejecutar", {"comando": "rm -rf ."}, 1),
                                           tool_call("ejecutar", {"comando": "python -c 'print(1)'"}, 2)]},
            {"content": "", "tool_calls": [tool_call("terminar", {"resumen": "tests ejecutados"})]},
        ])
        out = [m["content"] for m in seen[1]["messages"] if m["role"] == "tool"]
        self.assertIn("código de salida", out[0]); self.assertIn("Ran", out[0])  # se ejecutó de verdad (el repo de prueba no tiene tests)
        self.assertIn("orden no permitida", out[1]); self.assertIn("orden no permitida", out[2])
        self.assertTrue((repo / "README.md").exists())
        self.assertIn("Órdenes permitidas", seen[0]["messages"][0]["content"])
        res, evs, seen, _ = await self.go([{"content": "", "tool_calls": [tool_call("terminar", {"resumen": "x"})]}],
                                          commands=[])
        self.assertNotIn("ejecutar", [t["function"]["name"] for t in seen[0]["tools"]])

    async def test_preguntar_director_only_with_a_director_and_limited(self):
        asked = []

        async def director(q):
            asked.append(q)
            return "Usa la opción A", 0.004
        ask = {"content": "", "tool_calls": [tool_call("preguntar_director", {"pregunta": "¿A o B?"})]}
        script = [ask, {**ask, "tool_calls": [tool_call("preguntar_director", {"pregunta": "¿y C?"})]},
                  {**ask, "tool_calls": [tool_call("preguntar_director", {"pregunta": "¿y D?"})]},
                  {**ask, "tool_calls": [tool_call("preguntar_director", {"pregunta": "¿y E?"})]},
                  {"content": "", "tool_calls": [tool_call("terminar", {"resumen": "elegí A"})]}]
        seen, evs = [], []
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(tmp)
            a = LocalAgentAdapter(transport=llama(script, seen), http_get=web)
            res = await run(a, RunSpec(prompt="t", cwd=str(repo), ask_director=director), evs.append)
        self.assertEqual(res["status"], "done")
        self.assertEqual(asked, ["¿A o B?", "¿y C?", "¿y D?"])  # la cuarta ya no llega al Director
        out = [m["content"] for m in seen[-1]["messages"] if m["role"] == "tool"]
        self.assertEqual(out[0], "Usa la opción A"); self.assertIn("Ya has preguntado 3 veces", out[3])
        self.assertEqual(next(e for e in evs if e.kind == "usage").data["cost_usd"], 0.012)  # lo que costó el Director
        self.assertEqual([e.kind for e in evs].count("director_answer"), 3)
        res, evs, seen, _ = await self.go([{"content": "", "tool_calls": [tool_call("terminar", {"resumen": "x"})]}])
        self.assertNotIn("preguntar_director", [t["function"]["name"] for t in seen[0]["tools"]])  # fuera de un plan

    def test_json_call_parser(self):
        self.assertEqual(_json_call('Voy a leer: {"name": "leer_archivo", "arguments": {"ruta": "a"}}')["name"],
                         "leer_archivo")
        self.assertIsNone(_json_call("sin json"))


@unittest.skipIf(httpx is None, "falta httpx (pip install -e .[server])")
class LocalAgentInTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_with_local_agent_ends_in_review_with_its_diff(self):
        from localharness.adapters import local_agent
        from localharness.orchestrator import execute_task
        script = [{"content": "", "tool_calls": [tool_call("escribir_archivo", {"ruta": "hola.txt", "contenido": "hola"})]},
                  {"content": "", "tool_calls": [tool_call("terminar", {"resumen": "creado hola.txt"})]}]
        seen = []
        orig = local_agent.LocalAgentAdapter.__init__

        def patched(self, *a, **kw):
            kw["transport"] = llama(script, seen)
            orig(self, *a, **kw)
        local_agent.LocalAgentAdapter.__init__ = patched
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repo = make_repo(tmp)
                store = Store()
                p = store.add_project("demo", str(repo))
                ag = store.add_agent("qwen-agente", "local_agent", config={"max_turns": 5})
                t = store.add_task(p["id"], "saludo", "crea hola.txt", ag["id"])
                res = await execute_task(store, t["id"], worktree_root=str(Path(tmp) / "wt"))
                self.assertEqual(res["status"], "review")
                self.assertIn("hola.txt", res["diff"])
                self.assertFalse((repo / "hola.txt").exists())  # en su worktree, nunca en el repo
        finally:
            local_agent.LocalAgentAdapter.__init__ = orig


@unittest.skipIf(httpx is None, "falta httpx (pip install -e .[server])")
class LocalAgentInPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_asks_the_director_of_its_plan(self):
        """Director = Claude falso; trabajador = agente local que pregunta y el Director (sesión reanudada) responde."""
        from localharness.adapters import local_agent
        from localharness.hierarchy import Hierarchy
        from tests.test_hierarchy import FAKE
        script = [{"content": "", "tool_calls": [tool_call("preguntar_director", {"pregunta": "¿A o B?"})]},
                  {"content": "", "tool_calls": [tool_call("escribir_archivo", {"ruta": "paso1.txt", "contenido": "A"})]},
                  {"content": "", "tool_calls": [tool_call("terminar", {"resumen": "hecho con A"})]}]
        seen = []
        orig = local_agent.LocalAgentAdapter.__init__

        def patched(self, *a, **kw):
            kw["transport"] = llama(script, seen)
            orig(self, *a, **kw)
        local_agent.LocalAgentAdapter.__init__ = patched
        try:
            with tempfile.TemporaryDirectory() as tmp:
                repo = make_repo(tmp)
                store = Store()
                from localharness import settings
                settings.save(store, {"plans": {"always_review": False}})
                p = store.add_project("demo", str(repo))
                d = store.add_agent("director", "claude", role="director")
                store.add_agent("qwen-agente", "local_agent")
                plan = store.add_plan(p["id"], "haz algo", director_agent_id=d["id"])
                h = Hierarchy(store, binaries={"claude": FAKE}, worktree_root=str(Path(tmp) / "wt"))
                await h.plan(plan["id"])
                await h.run(plan["id"])
                worker = next(t for t in store.plan_tasks(plan["id"]) if t["kind"] == "worker" and t["seq"] == 1)
                evs = store.list_events(worker["id"])
                answer = next(e for e in evs if e["kind"] == "director_answer")
                self.assertIn("Usa la opción A (Director, sesión sess-1)", answer["text"])
                self.assertEqual(store.get_task(worker["id"])["cost_usd"], 0.003)
                tool_out = [m for m in seen[1]["messages"] if m["role"] == "tool"][0]["content"]
                self.assertIn("Usa la opción A", tool_out)
        finally:
            local_agent.LocalAgentAdapter.__init__ = orig
