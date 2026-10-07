"""Consumo en vivo: CPU/RAM y dónde cargó llama-server el modelo (leído de su log)."""

import os
import unittest
from unittest import mock

from localharness import usage

LOG = """main: build = 5000
llama_model_loader: loaded meta data with 30 key-value pairs
load_tensors: offloading 28 repeating layers to GPU
load_tensors: offloaded 20/37 layers to GPU
load_tensors:        CUDA0 model buffer size =  3200.50 MiB
load_tensors:   CPU_Mapped model buffer size =  1800.25 MiB
llama_kv_cache_unified:      CUDA0 KV buffer size =  1024.00 MiB
llama_context:      CUDA0 compute buffer size =   300.00 MiB
llama_context:  CUDA_Host compute buffer size =    40.00 MiB
main: server is listening on http://127.0.0.1:8080
"""


class PlacementTests(unittest.TestCase):
    def test_reads_layers_and_buffers_by_device(self):
        p = usage.placement(LOG)
        self.assertEqual((p["layers_gpu"], p["layers_total"]), (20, 37))
        self.assertEqual(p["gpu_mb"], 4524.5)        # pesos + KV + cálculo en CUDA0
        self.assertEqual(p["ram_mb"], 1840.2)        # CPU_Mapped + CUDA_Host (RAM fijada, no VRAM)
        cuda = next(d for d in p["devices"] if d["device"] == "CUDA0")
        self.assertEqual(cuda["parts"], {"pesos": 3200.5, "caché KV": 1024.0, "cálculo": 300.0})
        self.assertFalse(next(d for d in p["devices"] if d["device"] == "CUDA_Host")["gpu"])

    def test_cpu_only_and_empty(self):
        p = usage.placement("load_tensors: offloaded 0/33 layers to GPU\nload_tensors:   CPU_Mapped model buffer size = 4400.00 MiB\n")
        self.assertEqual((p["layers_gpu"], p["gpu_mb"], p["ram_mb"]), (0, 0, 4400.0))
        self.assertIsNone(usage.placement(""))
        self.assertIsNone(usage.placement("nada que ver"))


class SystemTests(unittest.TestCase):
    def test_system_has_cpu_and_ram(self):
        usage.system()
        s = usage.system()
        self.assertIsNotNone(s["ram_total_gb"])
        self.assertTrue(s["cpu_pct"] is None or 0 <= s["cpu_pct"] <= 100)

    def test_without_psutil_falls_back(self):
        with mock.patch.object(usage, "psutil", None):
            usage.system()
            s = usage.system()
            self.assertEqual(s["source"], "sistema")
            self.assertIsNone(usage.process(os.getpid()))  # sin psutil no se mide un proceso



class LlamaKeyTests(unittest.TestCase):
    def test_key_survives_a_restart_of_localharness(self):
        """Reinicias LocalHarness con el llama-server aún encendido: hay que seguir usando SU clave (sin 401)."""
        import tempfile
        from pathlib import Path
        from localharness import llama
        old = llama.API_KEY
        try:
            with tempfile.TemporaryDirectory() as tmp:
                log = Path(tmp) / "llama-server.log"
                (Path(tmp) / "llama-server.key").write_text("clave-del-arranque-anterior", encoding="utf-8")
                llama.API_KEY = None
                llama.LlamaManager(log)
                self.assertEqual(llama.API_KEY, "clave-del-arranque-anterior")
        finally:
            llama.API_KEY = old


if __name__ == "__main__":
    unittest.main()
