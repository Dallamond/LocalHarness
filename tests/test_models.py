"""Pestaña de modelos locales: lector GGUF, hardware, estimación de memoria, recomendaciones, nota y arranque."""

import json
import unittest.mock
import struct
import tempfile
import unittest
from pathlib import Path

from localharness import catalog, gguf, hardware, llama, settings
from localharness.store import Store

try:
    from fastapi.testclient import TestClient
    from localharness.api import create_app
except ImportError:
    TestClient = None

TEMPLATE_TOOLS = "{% if tools %}<tools>{{ tools }}</tools>{% endif %}<|im_start|>{{ m.content }}<think>"


def write_gguf(path: Path, arch: str = "qwen3", layers: int = 36, ctx: int = 40960, kv_heads: int = 8,
               template: str = TEMPLATE_TOOLS, label: str = "8B", ftype: int = 15, pad_mb: int = 0) -> Path:
    """GGUF v3 mínimo: solo cabecera (sin tensores), con vocabulario de prueba que el lector debe saltarse."""
    def s(x: str) -> bytes:
        b = x.encode()
        return struct.pack("<Q", len(b)) + b

    kv = [
        ("general.architecture", 8, s(arch)), ("general.name", 8, s("Modelo Falso")),
        ("general.size_label", 8, s(label)), ("general.file_type", 4, struct.pack("<I", ftype)),
        (f"{arch}.block_count", 4, struct.pack("<I", layers)),
        (f"{arch}.context_length", 4, struct.pack("<I", ctx)),
        (f"{arch}.embedding_length", 4, struct.pack("<I", 4096)),
        (f"{arch}.attention.head_count", 4, struct.pack("<I", 32)),
        (f"{arch}.attention.head_count_kv", 4, struct.pack("<I", kv_heads)),
        (f"{arch}.attention.key_length", 4, struct.pack("<I", 128)),
        ("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 8, 3) + s("a") + s("b") + s("c")),
        ("tokenizer.ggml.scores", 9, struct.pack("<IQ", 6, 3) + struct.pack("<fff", 0, 1, 2)),
        ("tokenizer.chat_template", 8, s(template)),
    ]
    with open(path, "wb") as f:
        f.write(b"GGUF" + struct.pack("<IQQ", 3, 0, len(kv)))
        for key, t, val in kv:
            f.write(s(key) + struct.pack("<I", t) + val)
        f.write(b"\0" * pad_mb * 2**20)
    return path


RTX3060 = {"gpu": "NVIDIA GeForce RTX 3060", "vram_gb": 12.0, "usable_vram_gb": 11.3, "ram_gb": 32.0,
           "usable_ram_gb": 19.2, "bandwidth_gbs": 360, "manual": False}


class GGUFTests(unittest.TestCase):
    def test_reads_header_and_skips_vocab(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = gguf.inspect(write_gguf(Path(tmp) / "m.gguf"))
        self.assertEqual((s["arch"], s["n_layer"], s["ctx_train"], s["n_head_kv"]), ("qwen3", 36, 40960, 8))
        self.assertEqual((s["params_b"], s["quant"]), (8.0, "Q4_K_M"))
        self.assertTrue(s["tools_in_template"])
        self.assertTrue(s["thinking"])
        self.assertIsNone(s["vocab"])  # el vocabulario no se guarda

    def test_template_without_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = gguf.inspect(write_gguf(Path(tmp) / "m.gguf", template="<|im_start|>{{ m.content }}"))
        self.assertFalse(s["tools_in_template"])

    def test_not_gguf(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.gguf"
            p.write_bytes(b"nada")
            with self.assertRaises(gguf.GGUFError):
                gguf.inspect(p)


class EstimateTests(unittest.TestCase):
    S8B = {"arch": "qwen3", "n_layer": 36, "attn_layers": 36, "n_head_kv": 8, "key_length": 128,
           "value_length": 128, "ctx_train": 40960, "params_b": 8.2}

    def test_kv_cache_size(self):
        # 36 capas × 8 cabezas × (128+128) × 2 bytes = 144 KiB por token → 32k tokens = 4.5 GiB
        e = catalog.estimate(self.S8B, 5.0, {"ctx": 32768})
        self.assertAlmostEqual(e["kv_gb"], 4.5, places=1)
        q8 = catalog.estimate(self.S8B, 5.0, {"ctx": 32768, "cache_k": "q8_0", "cache_v": "q8_0"})
        self.assertAlmostEqual(q8["kv_gb"], 4.5 * 1.0625 / 2, places=1)

    def test_partial_offload_moves_weights_to_ram(self):
        e = catalog.estimate(self.S8B, 5.0, {"ctx": 8192, "ngl": 18}, RTX3060)
        self.assertAlmostEqual(e["weights_gpu_gb"], 2.5, places=1)
        self.assertEqual(e["fit"], "mixto")
        full = catalog.estimate(self.S8B, 5.0, {"ctx": 8192}, RTX3060)
        self.assertEqual(full["fit"], "gpu")
        self.assertGreater(full["tps_est"], e["tps_est"])

    def test_suggest_prefers_long_context(self):
        sug = catalog.suggest_options(self.S8B, 5.0, RTX3060, cores=16)
        self.assertEqual(sug["estimate"]["fit"], "gpu")
        self.assertGreaterEqual(sug["options"]["ctx"], 32768)
        self.assertEqual(sug["options"]["threads"], 8)

    def test_moe_too_big_goes_to_cpu_experts(self):
        moe = {"n_layer": 48, "moe": True, "params_b": 30.5, "active_b": 3.3, "kv_mb_1k": 96, "ctx_train": 262144}
        sug = catalog.suggest_options(moe, 17.3, RTX3060)  # Q4_K_M de Qwen3-Coder-30B-A3B
        self.assertEqual(sug["estimate"]["fit"], "mixto")
        self.assertGreater(sug["options"]["n_cpu_moe"], 0)
        self.assertGreaterEqual(sug["options"]["ctx"], 32768)
        self.assertGreater(sug["estimate"]["tps_est"], 15)  # MoE con expertos en CPU sigue siendo usable


class CatalogTests(unittest.TestCase):
    def test_quant_names(self):
        self.assertEqual(catalog.quant_of("Qwen3-8B-UD-Q4_K_XL.gguf"), "UD-Q4_K_XL")
        self.assertEqual(catalog.quant_of("Q4_K_M/Qwen3-Coder-Q4_K_M-00001-of-00002.gguf"), "Q4_K_M")
        self.assertEqual(catalog.quant_of("gpt-oss-20b-MXFP4.gguf"), "MXFP4")
        self.assertEqual(catalog.base_quant("UD-Q4_K_XL"), "Q4_K_M")

    def test_catalog_is_valid(self):
        cat = catalog.load_catalog()
        self.assertGreater(len(cat), 5)
        for e in cat:
            for k in ("id", "repo", "match", "params_b", "agentic", "kv_mb_1k", "ctx_train"):
                self.assertIn(k, e, e.get("id"))
            self.assertRegex(e["repo"], r"^[\w.-]+/[\w.-]+$")

    def test_recommend_for_3060_offline(self):
        recs = catalog.recommend(RTX3060, {}, ["Qwen3-8B-Q4_K_M.gguf"])
        self.assertTrue(all(r["fit"] in ("gpu", "mixto", "no") for r in recs))
        self.assertEqual(recs, sorted(recs, key=lambda r: -r["score"]))
        q8 = next(r for r in recs if r["id"] == "qwen3-8b")
        self.assertTrue(q8["downloaded"])
        self.assertEqual(q8["fit"], "gpu")
        self.assertIn(catalog.base_quant(q8["best"]["quant"]), ("Q8_0", "Q6_K", "Q5_K_M"))
        # el de 14B cabe en la GPU en Q4/Q5 con contexto de agente
        q14 = next(r for r in recs if r["id"] == "qwen3-14b")
        self.assertEqual(q14["fit"], "gpu")
        # los primeros puestos son agentes con herramientas
        self.assertTrue(all(r["tools"] for r in recs[:4]))

    def test_recommend_uses_real_hf_sizes(self):
        files = [{"path": "Qwen3-8B-Q4_K_M.gguf", "size": 5_027_783_488},
                 {"path": "Qwen3-8B-Q8_0.gguf", "size": 8_709_518_624},
                 {"path": "mmproj-F16.gguf", "size": 1}, {"path": "README.md", "size": 1}]
        rec = next(r for r in catalog.recommend(RTX3060, {"unsloth/Qwen3-8B-GGUF": files}) if r["id"] == "qwen3-8b")
        self.assertEqual({q["quant"] for q in rec["quants"]}, {"Q4_K_M", "Q8_0"})
        self.assertTrue(rec["hf_checked"])
        self.assertEqual(rec["best"]["files"], ["Qwen3-8B-Q8_0.gguf"])

    def test_rating(self):
        s = {**EstimateTests.S8B, "tools_in_template": True, "thinking": True}
        good = catalog.rate_local(s, 5.0, RTX3060)
        bad = catalog.rate_local({**s, "tools_in_template": False}, 5.0, RTX3060)
        self.assertGreater(good["score"], bad["score"])
        failed = catalog.rate_local(s, 5.0, RTX3060, probe={"tool_calls": False, "json": False})
        self.assertLess(failed["score"], good["score"])
        self.assertIn("agente con herramientas", good["roles"])
        huge = catalog.rate_local(s, 60.0, RTX3060)
        self.assertEqual(huge["verdict"], "Poco recomendado")


class LaunchTests(unittest.TestCase):
    def test_option_args(self):
        args = llama.option_args({"flash_attn": "on", "cache_k": "q8_0", "cache_v": "q8_0", "n_cpu_moe": 0,
                                  "mlock": True, "temp": 0.7, "threads": None, "top_k": 20})
        self.assertEqual(args, ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--temp", "0.7", "--top-k", "20",
                                "--mlock"])

    def test_launch_merges_saved_and_dialog_options(self):
        store = Store(":memory:")
        settings.save(store, {"llama": {"per_model": {"/m.gguf": {"ctx": 8192, "cache_k": "q8_0", "extra": "-t 4"}}}})
        got = settings.llama_launch(store, "/m.gguf", {"ctx": 32768, "flash_attn": "on"})
        self.assertEqual(got["ctx"], 32768)
        self.assertEqual(got["extra"], ["-fa", "on", "-ctk", "q8_0", "-t", "4"])

    def test_shards_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for i in (1, 2):
                (d / f"big-Q4_K_M-0000{i}-of-00002.gguf").write_bytes(b"x" * 2**20)
            info = llama.describe(d / "big-Q4_K_M-00001-of-00002.gguf")
        self.assertEqual(info["size_gb"], round(2 / 1024, 2))
        self.assertEqual(info["name"], "big-Q4_K_M")


class HardwareTests(unittest.TestCase):
    def test_detect_never_fails(self):
        hw = hardware.detect(force=True)
        self.assertIn("gpus", hw)
        self.assertIsInstance(hw["cores"], int)

    def test_budget_override_and_bandwidth(self):
        b = hardware.budget({"gpus": [], "ram_gb": 16}, {"vram_gb": 12, "gpu_name": "RTX 3060"})
        self.assertEqual((b["vram_gb"], b["bandwidth_gbs"]), (12.0, 360))
        self.assertEqual(hardware.bandwidth("NVIDIA GeForce RTX 3060 Ti"), 448)  # gana la coincidencia más larga


@unittest.skipIf(TestClient is None, "falta fastapi (pip install -e .[server])")
class ModelsApiTests(unittest.TestCase):
    def test_ratings_estimate_and_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "modelos"
            d.mkdir()
            m = write_gguf(d / "Qwen3-8B-Q4_K_M.gguf")
            with TestClient(create_app(Path(tmp) / "lh.db", web_dist=None)) as c:
                c.put("/api/settings", json={"llama": {"model_dirs": [str(d)],
                                                       "hardware": {"vram_gb": 12, "ram_gb": 32}}})
                self.assertEqual(c.get("/api/hardware").json()["budget"]["vram_gb"], 12)
                r = c.get("/api/llama/ratings").json()["models"][str(m)]
                self.assertEqual(r["meta"]["arch"], "qwen3")
                self.assertEqual(r["catalog"]["id"], "qwen3-8b")
                self.assertGreater(r["rating"]["score"], 0)
                # la ficha queda guardada junto a la base de datos
                saved = json.loads((Path(tmp) / "model-info.json").read_text(encoding="utf-8"))
                self.assertEqual(saved[str(m)]["meta"]["n_layer"], 36)
                e = c.post("/api/llama/estimate", json={"path": str(m), "options": {"ctx": 32768,
                                                                                     "cache_k": "q8_0"}}).json()
                self.assertEqual(e["estimate"]["ctx"], 32768)
                self.assertEqual(e["ctx_train"], 40960)
                bad = c.post("/api/llama/estimate", json={"path": str(m), "options": {"cache_k": "q8; rm -rf"}})
                self.assertEqual(bad.status_code, 422)
                self.assertEqual(c.post("/api/llama/download", json={"repo": "a/b", "files": ["../x.gguf"]}).status_code,
                                 422)
                # nada arrancado (se mira un puerto libre: en el PC de Lucas suele haber un llama-server en el 8080)
                with unittest.mock.patch.object(llama, "health", return_value="off"):
                    self.assertEqual(c.post("/api/llama/probe").status_code, 409)
                # carpeta elegida al descargar: relativa no; una nueva se añade a las carpetas de modelos
                self.assertEqual(c.post("/api/llama/download", json={"repo": "a/b", "files": ["x.gguf"],
                                                                     "dest": "relativa"}).status_code, 422)
                otra = Path(tmp) / "otra"
                with unittest.mock.patch("localharness.hf.Downloads.start", return_value={"state": "queued"}) as st:
                    r = c.post("/api/llama/download", json={"repo": "a/b", "files": ["x.gguf"], "dest": str(otra)})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(st.call_args.args[2], otra)
                cfg = c.get("/api/settings").json()["values"]["llama"]
                self.assertIn(str(otra), cfg["model_dirs"])
                self.assertEqual(cfg["download_dir"], str(otra))
                recs = c.get("/api/llama/recommend?online=false").json()
                self.assertTrue(next(x for x in recs["models"] if x["id"] == "qwen3-8b")["downloaded"])


class WebOutdatedTests(unittest.TestCase):
    def test_rebuild_when_sources_are_newer(self):
        import os
        from localharness.cli import web_outdated
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp)
            (web / "src").mkdir()
            (web / "src" / "main.ts").write_text("x")
            self.assertTrue(web_outdated(web))  # sin compilar
            (web / "dist").mkdir()
            (web / "dist" / "index.html").write_text("<html>")
            os.utime(web / "src" / "main.ts", (1, 1))
            self.assertFalse(web_outdated(web))
            os.utime(web / "src" / "main.ts", None)  # git pull trae código nuevo
            os.utime(web / "dist" / "index.html", (2, 2))
            self.assertTrue(web_outdated(web))


class AutostartTests(unittest.TestCase):
    def test_autostart_last_model(self):
        from localharness.api import autostart_llama
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(":memory:")
            m = llama.LlamaPool(Path(tmp) / "llama-server.log")
            self.assertIsNone(autostart_llama(store, m))  # apagado por defecto
            gguf_path = write_gguf(Path(tmp) / "m.gguf")
            settings.save(store, {"llama": {"autostart": True, "port": 18997,
                                            "last": {"model": str(Path(tmp) / "no.gguf")}}})
            self.assertIn("no encuentro", autostart_llama(store, m))
            settings.save(store, {"llama": {"last": {"model": str(gguf_path), "options": {"ctx": 4096}}}})
            with unittest.mock.patch.object(llama.LlamaManager, "start") as start:
                self.assertIn("arrancando", autostart_llama(store, m))
            self.assertEqual(start.call_args.args[2], 4096)  # con los ajustes del último arranque
            self.assertEqual(settings.load(store)["local_base_url"], "http://127.0.0.1:18997")


if __name__ == "__main__":
    unittest.main()
