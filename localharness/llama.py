"""Lanzar llama-server con un GGUF que ya tengas descargado (M4).

De dónde salen las rutas (la primera que exista):
- Ajustes → Modelos locales de la GUI (settings.apply rellena SERVER_OVERRIDE y DIRS_OVERRIDE)
- `LOCALHARNESS_LLAMA_SERVER` / `LOCALHARNESS_MODEL_DIRS` (carpetas separadas por `;` en Windows, `:` en Linux)
- la configuración del agente de Arena LLM (`%APPDATA%/ArenaLLM/agent.json`: `model_dirs`, `llama_server`
  o la carpeta de `llama_bench`)
- `llama-server` en el PATH
"""

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

SERVER_OVERRIDE: str | None = None
DIRS_OVERRIDE: list[str] = []
# Clave del llama-server lanzado desde la GUI (aleatoria en cada arranque). Sin ella llama-server deja CORS
# abierto: cualquier web abierta en el navegador podría usar tu GPU a través de 127.0.0.1.
# API_KEY es la del servidor «principal» (compatibilidad); KEYS, la de cada puerto (varios modelos, uno por GPU).
API_KEY: str | None = None
KEYS: dict[int, str] = {}
PRINCIPAL = "principal"
POOL: "LlamaPool | None" = None  # el de la API en marcha (lo usa el orquestador para arrancar modelos solo)


def key_for(port: int | None) -> str | None:
    """La --api-key del llama-server que escucha en `port` (si lo arrancamos nosotros)."""
    return KEYS.get(int(port)) if port else None


def port_of(url: str | None) -> int | None:
    m = re.search(r":(\d+)(?:/|$)", url or "")
    return int(m.group(1)) if m else None


def key_for_url(url: str | None) -> str | None:
    return key_for(port_of(url)) or API_KEY  # uno lanzado a mano no tiene clave: la cabecera no molesta


def arena_config() -> dict:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "ArenaLLM" / "agent.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def server_binary() -> str | None:
    if SERVER_OVERRIDE:
        p = Path(SERVER_OVERRIDE)
        exe = "llama-server.exe" if os.name == "nt" else "llama-server"
        cand = p / exe if p.is_dir() else p  # vale la carpeta de llama.cpp o el exe
        if cand.is_file():
            return str(cand)
    env = os.environ.get("LOCALHARNESS_LLAMA_SERVER")
    if env and Path(env).is_file():
        return env
    cfg = arena_config()
    exe = "llama-server.exe" if os.name == "nt" else "llama-server"
    for key in ("llama_server", "llama_bench"):
        if cfg.get(key):
            p = Path(cfg[key])
            cand = p if key == "llama_server" else p.with_name(exe)
            if cand.is_file():
                return str(cand)
    return shutil.which("llama-server")


_devices_cache: dict = {}


def parse_devices(text: str) -> list[dict]:
    """Salida de `llama-server --list-devices` → [{id: "CUDA0", name, total_mb, free_mb}]. Es la numeración que
    entiende `-dev`, que NO tiene por qué coincidir con la de nvidia-smi (CUDA ordena de la más rápida a la más
    lenta; nvidia-smi, por bus PCI)."""
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*([A-Za-z]+\d+):\s*(.+?)\s*\((\d+)\s*MiB,\s*(\d+)\s*MiB free\)", line)
        if m:
            out.append({"id": m.group(1), "name": m.group(2), "total_mb": int(m.group(3)),
                        "free_mb": int(m.group(4))})
    return out


def list_devices(force: bool = False) -> list[dict]:
    """Las GPU tal como las ve llama.cpp (se guarda por binario: preguntar tarda ~1 s)."""
    exe = server_binary()
    if not exe:
        return []
    if not force and _devices_cache.get("exe") == exe:
        return _devices_cache["devices"]
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run([exe, "--list-devices"], capture_output=True, timeout=20, stdin=subprocess.DEVNULL,
                           creationflags=flags)
        devices = parse_devices((r.stdout + r.stderr).decode("utf-8", "replace"))
    except (OSError, subprocess.TimeoutExpired):
        devices = []
    _devices_cache.update(exe=exe, devices=devices)
    return devices


def model_dirs() -> list[Path]:
    env = os.environ.get("LOCALHARNESS_MODEL_DIRS")
    dirs = DIRS_OVERRIDE or (env.split(os.pathsep) if env else arena_config().get("model_dirs") or [])
    return [Path(d) for d in dirs if d and Path(d).is_dir()]


def list_models() -> list[Path]:
    """GGUF de modelo (se excluyen los proyectores multimodales mmproj y las partes 2..N)."""
    out = []
    for d in model_dirs():
        for p in sorted(d.rglob("*.gguf")):
            name = p.name.lower()
            if name.startswith("mmproj") or ("-of-" in name and "-00001-of-" not in name):
                continue
            out.append(p)
    return out


def find_model(query: str) -> Path:
    p = Path(query)
    if p.is_file():
        return p
    q = query.lower()
    hits = [m for m in list_models() if q in m.name.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise LookupError(f"Ningún GGUF contiene {query!r}. Mira: python -m localharness llama models")
    exact = [m for m in hits if m.stem.lower() == q]
    if len(exact) == 1:
        return exact[0]
    raise LookupError(f"{query!r} es ambiguo: " + ", ".join(m.name for m in hits))


# Ajustes de arranque que la GUI deja tocar → argumento de llama-server. Lo que no se indica, lo decide llama.cpp.
OPTION_FLAGS = {
    "flash_attn": "-fa", "cache_k": "-ctk", "cache_v": "-ctv", "threads": "-t", "batch": "-b", "ubatch": "-ub",
    "parallel": "-np", "n_cpu_moe": "--n-cpu-moe", "temp": "--temp", "top_p": "--top-p", "top_k": "--top-k",
    "min_p": "--min-p", "repeat_penalty": "--repeat-penalty", "reasoning_budget": "--reasoning-budget",
    # varias GPUs: en cuáles cargar (CUDA0, CUDA0,CUDA1…), cómo repartir (layer|row|none), proporción (3,1) y la principal
    "device": "-dev", "split_mode": "-sm", "tensor_split": "-ts", "main_gpu": "-mg",
}
BOOL_FLAGS = {"mlock": "--mlock", "no_mmap": "--no-mmap", "cont_batching_off": "--no-cont-batching"}


def option_args(opts: dict) -> list[str]:
    """{'flash_attn': 'on', 'cache_k': 'q8_0', 'mlock': True} → ['-fa', 'on', '-ctk', 'q8_0', '--mlock']"""
    out: list[str] = []
    for key, flag in OPTION_FLAGS.items():
        v = opts.get(key)
        if v in (None, "", "auto") or (key == "n_cpu_moe" and not v):
            continue
        out += [flag, str(v)]
    for key, flag in BOOL_FLAGS.items():
        if opts.get(key):
            out.append(flag)
    return out


def serve_command(model: Path, port: int = 8080, ctx: int = 16384, ngl: int = 99,
                  extra: list[str] | None = None) -> list[str]:
    exe = server_binary()
    if not exe:
        raise LookupError("No encuentro llama-server: define LOCALHARNESS_LLAMA_SERVER con su ruta")
    # -lv 4: desde ~b11000 llama.cpp ya no escribe con la verbosidad por defecto en qué GPU/RAM carga cada parte
    # («offloaded 34/34 layers», «CUDA1 model buffer size»…) ni los puntos de progreso; sin eso no se sabe dónde está
    # cada modelo (usage.placement) ni cuánto le falta. Si pasas tú otra verbosidad, manda la tuya.
    extra = list(extra or [])
    verbosity = [] if any(a in extra for a in ("-lv", "--verbosity", "--log-verbosity", "-v", "--verbose",
                                               "--log-verbose")) else ["-lv", "4"]
    # 127.0.0.1: el servidor no queda expuesto en la red
    return [exe, "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx),
            "-ngl", str(ngl), "--jinja", *verbosity, *extra]


class LlamaManager:
    """Un llama-server lanzado desde la GUI. Hay uno por cada «servidor local» de Ajustes (p. ej. uno por GPU):
    `server_id` lo distingue (log, clave y tiempos de carga propios). Vive lo que viva el servidor."""

    def __init__(self, log_path: Path, server_id: str = PRINCIPAL, port: int = 8080):
        self.server_id = server_id
        main = server_id == PRINCIPAL
        if not main:
            log_path = log_path.with_name(f"{log_path.stem}-{server_id}{log_path.suffix}")
        self.log_path = log_path
        self.times_path = log_path.with_name("llama-load-times.json")  # segundos que tardó cada GGUF en cargar
        # la --api-key del último llama-server que arrancamos: si reinicias LocalHarness y ese llama-server sigue
        # encendido, hay que seguir usando SU clave (si no, cada encargo da «401 Invalid API Key»)
        self.key_path = log_path.with_name("llama-server.key" if main else f"llama-server-{server_id}.key")
        self.port = port
        self.key: str | None = None
        try:
            self.key = self.key_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
        global API_KEY
        if self.key:
            KEYS.setdefault(port, self.key)
            if main and API_KEY is None:
                API_KEY = self.key
        self.proc: subprocess.Popen | None = None
        self.model: str | None = None
        self.device: str | None = None
        self.started_at: float | None = None
        self.ready_at: float | None = None

    def start(self, model: Path, port: int, ctx: int, ngl: int, extra: list[str] | None = None) -> None:
        self.stop()
        if health(port) != "off":
            raise RuntimeError(f"Ya hay algo escuchando en el puerto {port} (¿un llama-server lanzado a mano?)")
        global API_KEY
        import secrets
        key = secrets.token_urlsafe(24)
        cmd = serve_command(model, port, ctx, ngl, [*(extra or []), "--api-key", key])
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # sin ventana de consola en Windows
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=flags)
        log.close()
        self.model, self.port, self.started_at, self.ready_at = str(model), port, time.time(), None
        self.key = KEYS[port] = key
        dev = [a for i, a in enumerate(cmd) if i and cmd[i - 1] == "-dev"]
        self.device = dev[-1] if dev else None
        if self.server_id == PRINCIPAL:
            API_KEY = key
        try:
            self.key_path.write_text(key, encoding="utf-8")
        except OSError:
            pass

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def status(self, port: int) -> dict:
        """state: off | loading | ready | failed | external (uno que no lanzamos nosotros responde en el puerto)."""
        if self.proc is not None:
            code = self.proc.poll()
            h = health(self.port)
            state = ("failed" if code is not None else "ready" if h == "ready" else "loading")
            if state == "ready" and self.ready_at is None:
                self.ready_at = time.time()
                self._remember_load_time(self.model, self.ready_at - (self.started_at or self.ready_at))
            text = self.log_text()
            return {"state": state, "model": self.model, "port": self.port, "pid": self.proc.pid, "device": self.device,
                    "started_at": self.started_at, "exit_code": code, "log": _tail(text),
                    "log_lines": last_lines(text), "progress": self._progress(state, text)}
        h = health(port)
        if h != "off":
            return {"state": "external" if h == "ready" else "loading", "model": served_model(port), "port": port,
                    "pid": None, "started_at": None, "exit_code": None, "log": ""}
        text = self.log_text() if self.model else ""
        return {"state": "off", "model": self.model, "port": port, "pid": None, "started_at": None,
                "exit_code": None, "log": _tail(text), "log_lines": last_lines(text)}

    def log_text(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def log_tail(self, lines: int = 12) -> str:
        return _tail(self.log_text(), lines)

    # --- progreso de carga
    def load_times(self) -> dict[str, float]:
        try:
            return json.loads(self.times_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _remember_load_time(self, model: str | None, seconds: float) -> None:
        if not model or seconds <= 0:
            return
        times = self.load_times()
        # se guarda la carga más lenta (en frío, desde el disco): con el modelo en caché la barra acaba antes,
        # mejor que quedarse clavada en el 95 % la próxima vez que cargue en frío
        times[model] = round(max(seconds, times.get(model) or 0), 1)
        try:
            self.times_path.write_text(json.dumps(times, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _progress(self, state: str, text: str) -> dict | None:
        if state != "loading":
            return {"pct": 100, "stage": "listo"} if state == "ready" else None
        elapsed = time.time() - (self.started_at or time.time())
        return load_progress(text, elapsed, self.load_times().get(self.model or ""))


def _tail(text: str, lines: int = 12) -> str:
    return "\n".join(text.splitlines()[-lines:])


def _dots(line: str) -> bool:
    s = line.strip()
    return bool(s) and set(s) == {"."}


def last_lines(text: str, n: int = 2) -> list[str]:
    """Últimas líneas con contenido (sin las de solo puntos de progreso), para ver de un vistazo que va bien."""
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not _dots(ln)][-n:]


# marcas del log → (% mínimo, etapa). Gana la que aparezca más tarde en el log.
STAGES = [
    ("loading model", 3, "leyendo el modelo del disco"),
    ("load_tensors", 10, "cargando tensores"),
    ("llama_context", 92, "preparando el contexto"),
    ("initializing", 92, "preparando el contexto"),
    ("warming up", 95, "calentando"),
    ("model loaded", 98, "casi listo"),
]


def load_progress(text: str, elapsed: float, last_load_s: float | None) -> dict:
    """% aproximado de la carga. Tres fuentes, de más a menos fiable:
    1. los puntos de progreso de llama.cpp tras `load_tensors` (uno por cada 1 % de tensores; las versiones
       recientes con verbosidad 3 ya no los imprimen),
    2. lo que tardó este mismo GGUF la última vez,
    3. si no hay nada, solo la etapa (pct None = barra indeterminada)."""
    low = text.lower()
    stage, floor, at = "arrancando", 0, -1
    for key, pct, name in STAGES:
        i = low.rfind(key)
        if i > at:
            at, stage, floor = i, name, pct
    if floor >= 92:
        return {"pct": floor, "stage": stage, "source": "log"}
    i = low.rfind("load_tensors")
    if i >= 0:
        dots = sum(len(ln.strip()) for ln in text[i:].splitlines() if _dots(ln))
        if dots:
            return {"pct": min(90, 10 + round(dots * 0.8)), "stage": "cargando tensores", "source": "log"}
    if last_load_s:
        return {"pct": max(floor, min(95, round(elapsed / last_load_s * 100))), "stage": stage,
                "source": "tiempo", "eta_s": max(0, round(last_load_s - elapsed))}
    return {"pct": None, "stage": stage, "source": None}


def health(port: int) -> str:
    """ready | loading (responde pero aún carga el modelo: /health da 503) | off."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            return "ready" if r.status == 200 else "loading"
    except urllib.error.HTTPError as e:
        return "loading" if e.code == 503 else "ready"
    except OSError:
        return "off"


def served_model(port: int) -> str | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=2) as r:
            return (json.loads(r.read()).get("data") or [{}])[0].get("id")
    except (OSError, ValueError):
        return None


def shards(model: Path) -> list[Path]:
    """Todas las partes de un GGUF partido (x-00001-of-00003.gguf…); si no está partido, solo él."""
    import re
    m = re.match(r"(.*)-00001-of-(\d{5})\.gguf$", model.name, re.I)
    if not m:
        return [model]
    return [p for i in range(1, int(m.group(2)) + 1)
            if (p := model.with_name(f"{m.group(1)}-{i:05d}-of-{m.group(2)}.gguf")).is_file()]


def describe(model: Path) -> dict:
    """Ficha de un GGUF para la GUI; la cuantización se deduce del nombre (Q4_K_M, Q8_0, F16…)."""
    import re
    m = re.search(r"(?i)[-_.](i?q\d[_a-z0-9]*|f16|bf16|f32|mxfp4)(?=[-_.]|$)", model.stem)
    size = sum(p.stat().st_size for p in shards(model))
    mmproj = any(model.parent.glob("mmproj*.gguf"))
    return {"name": re.sub(r"-\d{5}-of-\d{5}$", "", model.stem), "file": model.name, "path": str(model), "dir": str(model.parent),
            "size_gb": round(size / 2**30, 2), "quant": m.group(1).upper() if m else None, "vision": mmproj}


class LlamaPool:
    """Los llama-server de LocalHarness, uno por «servidor local» de Ajustes (`llama.servers`): lo normal con dos
    GPU es uno en cada una (p. ej. el modelo «fuerte» en la grande y el «rápido» en la pequeña)."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.managers: dict[str, LlamaManager] = {}

    def get(self, server_id: str, port: int | None = None) -> LlamaManager:
        m = self.managers.get(server_id)
        if m is None:
            m = self.managers[server_id] = LlamaManager(self.log_path, server_id, port or 8080)
        elif port and not (m.proc and m.proc.poll() is None):
            m.port = port  # el puerto se puede cambiar en Ajustes mientras está apagado
        return m

    @property
    def principal(self) -> LlamaManager:
        return self.get(PRINCIPAL)

    def stop_all(self) -> None:
        for m in self.managers.values():
            m.stop()

    def load_times(self) -> dict[str, float]:
        return self.principal.load_times()
