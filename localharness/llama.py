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
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

SERVER_OVERRIDE: str | None = None
DIRS_OVERRIDE: list[str] = []


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


def serve_command(model: Path, port: int = 8080, ctx: int = 16384, ngl: int = 99,
                  extra: list[str] | None = None) -> list[str]:
    exe = server_binary()
    if not exe:
        raise LookupError("No encuentro llama-server: define LOCALHARNESS_LLAMA_SERVER con su ruta")
    # 127.0.0.1: el servidor no queda expuesto en la red
    return [exe, "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-c", str(ctx),
            "-ngl", str(ngl), "--jinja", *(extra or [])]


class LlamaManager:
    """Un llama-server lanzado desde la GUI (uno a la vez: una sola GPU). Vive lo que viva el servidor."""

    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None
        self.model: str | None = None
        self.port = 8080
        self.started_at: float | None = None

    def start(self, model: Path, port: int, ctx: int, ngl: int) -> None:
        self.stop()
        if health(port) != "off":
            raise RuntimeError(f"Ya hay algo escuchando en el puerto {port} (¿un llama-server lanzado a mano?)")
        cmd = serve_command(model, port, ctx, ngl)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # sin ventana de consola en Windows
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     creationflags=flags)
        log.close()
        self.model, self.port, self.started_at = str(model), port, time.time()

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
            return {"state": state, "model": self.model, "port": self.port, "pid": self.proc.pid,
                    "started_at": self.started_at, "exit_code": code, "log": self.log_tail()}
        h = health(port)
        if h != "off":
            return {"state": "external" if h == "ready" else "loading", "model": served_model(port), "port": port,
                    "pid": None, "started_at": None, "exit_code": None, "log": ""}
        return {"state": "off", "model": self.model, "port": port, "pid": None, "started_at": None,
                "exit_code": None, "log": self.log_tail() if self.model else ""}

    def log_tail(self, lines: int = 12) -> str:
        try:
            return "\n".join(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return ""


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


def describe(model: Path) -> dict:
    """Ficha de un GGUF para la GUI; la cuantización se deduce del nombre (Q4_K_M, Q8_0, F16…)."""
    import re
    m = re.search(r"(?i)[-_.](i?q\d[_a-z0-9]*|f16|bf16|f32)(?=[-_.]|$)", model.stem)
    return {"name": re.sub(r"-\d{5}-of-\d{5}$", "", model.stem), "file": model.name, "path": str(model), "dir": str(model.parent),
            "size_gb": round(model.stat().st_size / 2**30, 2), "quant": m.group(1).upper() if m else None}
