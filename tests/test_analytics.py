"""Analíticas: peticiones, tokens de Claude y del modelo local, encargos y uso por agente."""

import unittest

from localharness import analytics
from localharness.store import Store


class AnalyticsTests(unittest.TestCase):
    def test_counts_tokens_requests_and_delegations(self):
        s = Store()
        p = s.add_project("demo", "/x")
        claude = s.add_agent("coord", "claude")
        local = s.add_agent("qwen", "local_agent")
        t1 = s.add_task(p["id"], "a", "a", claude["id"])
        s.update_task(t1["id"], cost_usd=0.05)
        s.add_event(t1["id"], "usage", "", {"cost_usd": 0.05, "usage": {
            "input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 40, "output_tokens": 50}})
        s.add_event(t1["id"], "delegate", "", {"tool": "local_ask", "ok": True, "prompt_tokens": 300,
                                               "completion_tokens": 80, "seconds": 4.5, "model": "Qwen3-8B"})
        s.add_event(t1["id"], "delegate", "", {"tool": "local_execute_plan/write", "ok": False, "prompt_tokens": 20,
                                               "completion_tokens": 0, "model": "Qwen3-8B"})
        s.add_event(t1["id"], "delegate", "", {"tool": "local_prepare", "ok": True})  # equipar: no es un encargo
        s.add_event(t1["id"], "user", "sigue")  # tu respuesta: otra petición
        t2 = s.add_task(p["id"], "b", "b", local["id"])
        s.add_event(t2["id"], "usage", "", {"local": True, "model": "Qwen3-8B",
                                            "usage": {"prompt_tokens": 1000, "completion_tokens": 200}})
        r = analytics.compute(s, days=7)
        t = r["total"]
        self.assertEqual((t["tasks"], t["requests"], t["cost_usd"]), (2, 3, 0.05))
        self.assertEqual((t["claude_in"], t["claude_out"], t["claude_tokens"]), (150, 50, 200))
        self.assertEqual((t["local_in"], t["local_out"], t["local_tokens"]), (1320, 280, 1600))
        self.assertEqual((t["delegations"], t["delegations_ok"]), (2, 1))
        self.assertEqual(t["local_share"], round(1600 / 1800, 3))
        self.assertEqual(r["by_tool"], {"ask": 1, "execute_plan": 1})
        self.assertEqual(r["by_model"], {"Qwen3-8B": 1600})
        rows = {a["agent"]: a for a in r["by_agent"]}
        self.assertEqual((rows["coord"]["requests"], rows["coord"]["delegations"], rows["qwen"]["local_in"]), (2, 2, 1000))
        self.assertEqual(len(r["by_day"]), 7)
        self.assertEqual(r["by_day"][-1]["claude_tokens"] + r["by_day"][-1]["local_tokens"], 1800)  # todo es de hoy


if __name__ == "__main__":
    unittest.main()
