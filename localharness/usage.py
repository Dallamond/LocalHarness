"""Consumo en vivo: CPU y RAM del PC, del proceso de llama-server, y DÓNDE está cargado el modelo (GPU o RAM).

- Con `psutil` (va en `pip install -e .[server]`) todo es exacto. Sin él: CPU por /proc/stat (Linux) o
  GetSystemTimes (Windows), RAM con hardware._ram, y el proceso de llama-server sin datos.
- Dónde está el modelo: se lee del log de llama-server, que dice cuántas capas subió a la GPU y cuánto ocupa
  cada búfer (pesos, caché KV, cálculo) en cada dispositivo («CUDA0 model buffer size = 4403 MiB»,
  «CPU_Mapped model buffer size = 281 MiB», «offloaded 33/33 layers to GPU»).
- VRAM del proceso: `nvidia-smi --query-compute-apps` (en Windows con WDDM suele dar N/A: entonces se usa el total
  de los búferes de GPU del log).
"""

import ctypes
import os
import re
import shutil
import subprocess
import time

from localharness import hardware

try:
    import psutil
except ImportError:  # sin la dependencia: valores aproximados o None
    psutil = None

_prev: dict = {}
_procs: dict = {}


def _cpu_times() -> tuple[float, float] | None:
    """(ocupado, total) acumulados de la CPU para calcular el % entre dos lecturas."""
    try:
        if os.path.exists("/proc/stat"):
            with open("/proc/stat") as f:
                v = [float(x) for x in f.readline().split()[1:]]
            idle = v[3] + (v[4] if len(v) > 4 else 0)
            return sum(v) - idle, sum(v)
        if os.name == "nt":
            ft = [ctypes.c_ulonglong() for _ in range(3)]  # idle, kernel (incluye idle), user
            if ctypes.windll.kernel32.GetSystemTimes(*(ctypes.byref(x) for x in ft)):  # type: ignore[attr-defined]
                idle, kernel, user = (x.value for x in ft)
                return kernel + user - idle, kernel + user
    except (OSError, ValueError, AttributeError):
        pass
    return None


def system() -> dict:
    """CPU (% total y por núcleo) y RAM del PC ahora mismo."""
    out: dict = {"cpu_pct": None, "per_core": [], "cores": os.cpu_count(), "ram_total_gb": None, "ram_used_gb": None,
                 "ram_pct": None, "swap_used_gb": None, "source": "psutil" if psutil else "sistema"}
    if psutil:
        out["cpu_pct"] = psutil.cpu_percent(None)  # desde la llamada anterior (sin bloquear)
        out["per_core"] = psutil.cpu_percent(None, percpu=True)
        vm = psutil.virtual_memory()
        out.update(ram_total_gb=round(vm.total / 2**30, 1), ram_used_gb=round((vm.total - vm.available) / 2**30, 1),
                   ram_pct=vm.percent)
        try:
            out["swap_used_gb"] = round(psutil.swap_memory().used / 2**30, 1)
        except (OSError, RuntimeError):
            pass
        return out
    now = _cpu_times()
    if now and _prev.get("cpu"):
        busy, total = now[0] - _prev["cpu"][0], now[1] - _prev["cpu"][1]
        out["cpu_pct"] = round(100 * busy / total, 1) if total > 0 else 0.0
    if now:
        _prev["cpu"] = now
    ram = hardware._ram()
    if ram["ram_gb"]:
        used = ram["ram_gb"] - (ram["ram_free_gb"] or 0)
        out.update(ram_total_gb=ram["ram_gb"], ram_used_gb=round(used, 1), ram_pct=round(100 * used / ram["ram_gb"], 1))
    return out


def process(pid: int | None) -> dict | None:
    """RAM (RSS), % de CPU (100 % = un núcleo entero) e hilos de un proceso. None sin psutil o si ya no existe."""
    if not pid or not psutil:
        return None
    try:
        p = _procs.get(pid)
        if p is None:
            p = _procs[pid] = psutil.Process(pid)
            p.cpu_percent(None)  # la primera lectura siempre da 0: arranca la medida
        with p.oneshot():
            return {"pid": pid, "rss_gb": round(p.memory_info().rss / 2**30, 2), "cpu_pct": p.cpu_percent(None),
                    "threads": p.num_threads()}
    except (psutil.Error, OSError):
        _procs.pop(pid, None)
        return None


def find_llama_pid(port: int) -> int | None:
    """llama-server lanzado fuera de LocalHarness: el proceso que escucha en el puerto (solo con psutil)."""
    if not psutil:
        return None
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid:
                return c.pid
    except (psutil.Error, OSError):
        pass
    return None


_GPU_APPS: dict = {"at": 0.0, "data": {}}


def gpu_by_pid() -> dict[int, float]:
    """VRAM (MB) que usa cada proceso según nvidia-smi (cacheado 2 s). Vacío si no hay o da N/A."""
    if time.time() - _GPU_APPS["at"] < 2:
        return _GPU_APPS["data"]
    data: dict[int, float] = {}
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            r = subprocess.run([exe, "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in r.stdout.strip().splitlines():
                pid, _, mem = (x.strip() for x in line.partition(","))
                if pid.isdigit() and mem.replace(".", "", 1).isdigit():
                    data[int(pid)] = float(mem)
        except (OSError, subprocess.SubprocessError):
            pass
    _GPU_APPS.update(at=time.time(), data=data)
    return data


_LAYERS = re.compile(r"offloaded (\d+)/(\d+) layers to GPU")
_BUFFER = re.compile(r"(\S+) (model|KV|compute|output|RS) buffer size\s*=\s*([\d.]+) MiB")
GPU_DEVICES = ("CUDA", "ROCm", "Vulkan", "Metal", "SYCL", "MUSA", "CANN", "OpenCL")
KIND = {"model": "pesos", "KV": "caché KV", "compute": "cálculo", "output": "salida", "RS": "estado"}


def placement(log_text: str) -> dict | None:
    """Dónde cargó llama-server el modelo, según su log (se reescribe en cada arranque): capas en GPU y MB por
    dispositivo y tipo de búfer."""
    if not log_text:
        return None
    text = log_text
    layers = _LAYERS.findall(text)
    buffers: dict[str, dict[str, float]] = {}
    for dev, kind, mb in _BUFFER.findall(text):
        dev = dev.rstrip(":")
        buffers.setdefault(dev, {})
        buffers[dev][KIND.get(kind, kind)] = buffers[dev].get(KIND.get(kind, kind), 0.0) + float(mb)
    if not layers and not buffers:
        return None
    on_gpu = lambda d: d.startswith(GPU_DEVICES) and not d.endswith("_Host")  # noqa: E731 — CUDA_Host = RAM fijada
    gpu_mb = sum(sum(v.values()) for d, v in buffers.items() if on_gpu(d))
    ram_mb = sum(sum(v.values()) for d, v in buffers.items() if not on_gpu(d))
    got = layers[-1] if layers else None
    return {"layers_gpu": int(got[0]) if got else None, "layers_total": int(got[1]) if got else None,
            "gpu_mb": round(gpu_mb, 1), "ram_mb": round(ram_mb, 1),
            "devices": [{"device": d, "gpu": on_gpu(d), "total_mb": round(sum(v.values()), 1),
                         "parts": {k: round(x, 1) for k, x in v.items()}} for d, v in buffers.items()]}
