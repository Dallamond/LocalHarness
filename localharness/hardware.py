"""Qué hardware tiene este PC: GPU (VRAM), RAM y CPU. Sin dependencias: nvidia-smi y lo que da el sistema.

Sirve para recomendar qué modelos caben y con qué contexto. Si algo no se puede leer queda en None y la GUI
deja escribirlo a mano (Ajustes → llama → hardware).
"""

import ctypes
import os
import platform
import shutil
import subprocess
import time

# Ancho de banda de memoria (GB/s) de GPU conocidas: decide los tok/s al generar (cada token lee los pesos).
# Se busca por subcadena del nombre, la más larga gana. Sin coincidencia se usa un valor prudente.
GPU_BANDWIDTH = {
    "RTX 5090": 1792, "RTX 5080": 960, "RTX 5070 Ti": 896, "RTX 5070": 672, "RTX 5060 Ti": 448, "RTX 5060": 448,
    "RTX 4090": 1008, "RTX 4080": 717, "RTX 4070 Ti SUPER": 672, "RTX 4070 Ti": 504, "RTX 4070 SUPER": 504,
    "RTX 4070": 504, "RTX 4060 Ti": 288, "RTX 4060": 272,
    "RTX 3090 Ti": 1008, "RTX 3090": 936, "RTX 3080 Ti": 912, "RTX 3080": 760, "RTX 3070 Ti": 608,
    "RTX 3070": 448, "RTX 3060 Ti": 448, "RTX 3060": 360, "RTX 3050": 224,
    "RTX 2080 Ti": 616, "RTX 2080": 448, "RTX 2070": 448, "RTX 2060": 336, "GTX 1080 Ti": 484, "GTX 1660": 192,
    "A100": 1555, "H100": 2039, "L40": 864, "A6000": 768, "A4000": 448, "T4": 320, "V100": 900,
    "RX 7900 XTX": 960, "RX 7900 XT": 800, "RX 7800 XT": 624, "RX 7600": 288, "RX 6800": 512,
}
DEFAULT_GPU_BW = 300
RAM_BW = 50  # DDR4/DDR5 de escritorio en doble canal, a ojo: lo que va a la CPU genera mucho más lento

_cache: dict = {}


def _run(cmd: list[str], timeout: float = 5) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _nvidia() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe and os.name == "nt":
        cand = os.path.join(os.environ.get("ProgramW6432", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI",
                            "nvidia-smi.exe")
        exe = cand if os.path.isfile(cand) else None
    if not exe:
        return []
    out = _run([exe, "--query-gpu=name,memory.total,memory.used,memory.free,driver_version",
                "--format=csv,noheader,nounits"])
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            total, used, free = (round(float(x) / 1024, 2) for x in parts[1:4])
        except ValueError:
            continue
        gpus.append({"name": parts[0], "vendor": "nvidia", "vram_gb": total, "vram_used_gb": used,
                     "vram_free_gb": free, "driver": parts[4] if len(parts) > 4 else None, "backend": "CUDA"})
    return gpus


def _windows_gpus() -> list[dict]:
    """GPU no NVIDIA en Windows (nombre; la VRAM de Win32_VideoController se queda en 4 GB, no sirve)."""
    out = _run(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"])
    return [{"name": n.strip(), "vendor": "amd" if "AMD" in n or "Radeon" in n else "intel" if "Intel" in n else "?",
             "vram_gb": None, "vram_used_gb": None, "vram_free_gb": None, "driver": None, "backend": "Vulkan"}
            for n in out.splitlines() if n.strip() and "NVIDIA" not in n]


def _ram() -> dict:
    total = avail = None
    try:
        if os.name == "nt":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
                total, avail = st.ullTotalPhys / 2**30, st.ullAvailPhys / 2**30
        elif os.path.exists("/proc/meminfo"):
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    info[k] = int(v.split()[0]) / 2**20  # kB → GB
            total, avail = info.get("MemTotal"), info.get("MemAvailable")
        elif platform.system() == "Darwin":
            total = int(_run(["sysctl", "-n", "hw.memsize"]).strip() or 0) / 2**30 or None
    except (OSError, ValueError, AttributeError):
        pass
    return {"ram_gb": round(total, 1) if total else None, "ram_free_gb": round(avail, 1) if avail else None}


def _cpu_name() -> str | None:
    if os.name == "nt":
        out = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"])
        return out.strip().splitlines()[0].strip() if out.strip() else platform.processor() or None
    if os.path.exists("/proc/cpuinfo"):
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    if platform.system() == "Darwin":
        return _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or None
    return platform.processor() or None


def bandwidth(gpu_name: str | None) -> int:
    if not gpu_name:
        return DEFAULT_GPU_BW
    hits = [k for k in GPU_BANDWIDTH if k.lower() in gpu_name.lower()]
    return GPU_BANDWIDTH[max(hits, key=len)] if hits else DEFAULT_GPU_BW


def detect(force: bool = False) -> dict:
    """GPU, RAM y CPU. La parte lenta (nombres) se guarda 10 min; la memoria libre se lee siempre."""
    now = time.time()
    if force or not _cache or now - _cache.get("at", 0) > 600:
        _cache.clear()
        _cache.update({"at": now, "cpu": _cpu_name(), "os": f"{platform.system()} {platform.release()}"})
        if os.name == "nt" and not _nvidia():
            _cache["other_gpus"] = _windows_gpus()
    gpus = _nvidia() or list(_cache.get("other_gpus") or [])
    apple = platform.system() == "Darwin" and platform.machine() == "arm64"
    ram = _ram()
    if apple and ram["ram_gb"]:  # memoria unificada: la GPU puede usar ~70 % de la RAM
        gpus = [{"name": "Apple Silicon", "vendor": "apple", "vram_gb": round(ram["ram_gb"] * 0.7, 1),
                 "vram_used_gb": None, "vram_free_gb": None, "driver": None, "backend": "Metal"}]
    for g in gpus:
        g["bandwidth_gbs"] = bandwidth(g["name"]) if g["vendor"] != "apple" else 200
    return {"gpus": gpus, "cpu": _cache.get("cpu"), "cores": os.cpu_count(), "os": _cache.get("os"), **ram}


def budget(hw: dict, override: dict | None = None) -> dict:
    """Memoria que se puede usar para un modelo: VRAM de la mayor GPU menos un margen para el escritorio,
    y RAM para lo que no quepa (capas o expertos en CPU). `override` (de Ajustes) manda sobre lo detectado."""
    o = override or {}
    gpu = max(hw.get("gpus") or [{}], key=lambda g: g.get("vram_gb") or 0)
    vram = o.get("vram_gb") or gpu.get("vram_gb") or 0
    ram = o.get("ram_gb") or hw.get("ram_gb") or 0
    return {"gpu": o.get("gpu_name") or gpu.get("name"), "vram_gb": float(vram),
            "usable_vram_gb": max(0.0, float(vram) - (0.7 if vram else 0)),  # Windows + navegador usan algo
            "ram_gb": float(ram), "usable_ram_gb": max(0.0, float(ram) * 0.6),  # el resto, para el sistema
            "bandwidth_gbs": int(o.get("bandwidth_gbs") or bandwidth(o.get("gpu_name") or gpu.get("name"))),
            "manual": bool(o.get("vram_gb") or o.get("ram_gb"))}

