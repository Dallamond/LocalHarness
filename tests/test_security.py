"""La API no tiene contraseña: solo atiende a esta máquina (Host) y a sus propias páginas (Origin)."""

import tempfile, unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from localharness.api import _hostname, create_app
except ImportError:  # dependencias del servidor no instaladas
    TestClient = None


@unittest.skipIf(TestClient is None, "faltan fastapi/httpx (pip install -e .[server])")
class LocalOnlyTests(unittest.TestCase):
    def test_hostname(self):
        self.assertEqual(_hostname("127.0.0.1:8095"), "127.0.0.1")
        self.assertEqual(_hostname("[::1]:8095"), "::1")
        self.assertEqual(_hostname("http://localhost:5174"), "localhost")
        self.assertEqual(_hostname("https://evil.example"), "evil.example")

    def test_host_and_origin(self):
        with tempfile.TemporaryDirectory() as tmp, \
                TestClient(create_app(Path(tmp) / "lh.db", web_dist=None)) as c:
            self.assertEqual(c.get("/api/health").status_code, 200)
            ok = {"Host": "127.0.0.1:8095", "Origin": "http://127.0.0.1:8095"}
            self.assertEqual(c.get("/api/health", headers=ok).status_code, 200)
            self.assertEqual(c.get("/api/health", headers={"Origin": "http://localhost:5174"}).status_code, 200)
            # DNS rebinding: un dominio ajeno que apunta a 127.0.0.1
            self.assertEqual(c.get("/api/health", headers={"Host": "evil.example:8095"}).status_code, 403)
            # otra web abierta en el navegador intentando añadir un «servidor MCP» que ejecute algo
            bad = c.put("/api/settings", headers={"Origin": "https://evil.example"},
                        json={"mcp_servers": {"x": {"command": "calc"}}})
            self.assertEqual(bad.status_code, 403)
            self.assertEqual(c.post("/api/agents", headers={"Origin": "null"}, json={"name": "x"}).status_code, 403)
            self.assertEqual(c.get("/api/settings").json()["values"]["mcp_servers"], {})

    def test_lan_opt_out(self):
        with tempfile.TemporaryDirectory() as tmp, \
                TestClient(create_app(Path(tmp) / "lh.db", web_dist=None, allowed_hosts=None)) as c:
            self.assertEqual(c.get("/api/health", headers={"Host": "pc-de-lucas:8095"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
