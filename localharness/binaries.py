"""Resolver el binario de una CLI a algo que se pueda lanzar SIN pasar por cmd.exe.

En Windows, npm instala shims `.cmd`: lanzarlos implica cmd.exe, que reinterpreta `& | % ^ "` y saltos
de línea de los argumentos (rompe prompts y es un riesgo). El shim de npm solo hace
`"%dp0%\\node_modules\\...\\claude.exe" %*`, así que se lee su destino y se lanza directamente.
Los scripts con shebang de Python (las CLI falsas de las pruebas) se lanzan con el intérprete actual.
"""

import re
import shutil
import sys
from pathlib import Path

_SHIM_TARGET = re.compile(r'"%(?:dp0|~dp0)%\\?([^"]+)"', re.IGNORECASE)


def resolve(binary: str) -> list[str]:
    """Devuelve el prefijo de comando para `binary` ([exe] o [intérprete, script])."""
    path = shutil.which(binary) or (binary if Path(binary).is_file() else None)
    if not path:
        return [binary]  # que falle al lanzar con FileNotFoundError
    p = Path(path)
    if p.suffix.lower() in (".cmd", ".bat"):
        return _from_npm_shim(p) or [str(p)]
    if p.suffix.lower() not in (".exe", ".com") and _is_python_script(p):
        return [sys.executable, str(p)]
    return [str(p)]


def _from_npm_shim(shim: Path) -> list[str] | None:
    try:
        text = shim.read_text(errors="replace")
    except OSError:
        return None
    targets = [shim.parent / m.replace("\\", "/") for m in _SHIM_TARGET.findall(text)]
    exe = next((t for t in targets if t.suffix.lower() == ".exe" and t.is_file()), None)
    if exe:
        return [str(exe)]
    script = next((t for t in targets if t.suffix.lower() in (".js", ".cjs", ".mjs") and t.is_file()), None)
    node = shutil.which("node")
    if script and node:
        return [node, str(script)]
    return None


def _is_python_script(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            first = f.readline(200)
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first
