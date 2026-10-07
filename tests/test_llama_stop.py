import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from localharness import llama


class StopEverythingTests(unittest.TestCase):
    def test_arg_reads_flags(self):
        cmd = ["llama-server.exe", "-m", "D:/m/Qwen.gguf", "--port", "8081"]
        self.assertEqual((llama._arg(cmd, "-m"), llama._arg(cmd, "--port"), llama._arg(cmd, "-dev")),
                         ("D:/m/Qwen.gguf", "8081", None))

    def test_kill_everything_stops_ours_and_kills_strays(self):
        """«Apagar todos»: los de los paneles con orden y luego los sueltos que sigan vivos."""
        pool = llama.LlamaPool(Path(self.id() + ".log"))
        strays = [{"pid": 111, "port": 8080, "model": "Viejo"}, {"pid": 222, "port": None, "model": None}]
        with mock.patch.object(llama, "running_servers", return_value=strays), \
                mock.patch.object(llama, "kill_pid", side_effect=lambda pid: pid == 111) as kill, \
                mock.patch.object(pool, "stop_all") as stop_all:
            killed = pool.kill_everything()
        stop_all.assert_called_once()
        self.assertEqual([c.args[0] for c in kill.call_args_list], [111, 222])
        self.assertEqual(killed, [strays[0]])

    @unittest.skipUnless(sys.platform == "win32", "Job Object: solo Windows")
    def test_child_joins_the_kill_on_close_job(self):
        """El llama-server entra en el Job Object que muere con LocalHarness (aquí, un proceso cualquiera)."""
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdin=subprocess.DEVNULL)
        try:
            llama._die_with_us(child)
            self.assertIsNotNone(llama._JOB)
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32")
            k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
            inside = wintypes.BOOL()
            k32.IsProcessInJob(int(child._handle), llama._JOB, ctypes.byref(inside))
            self.assertTrue(inside.value)
        finally:
            child.kill()
            child.wait()
