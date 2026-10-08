"""Lo que necesita un modelo local con visión (P14 y P15 del plan): imágenes en base64, texto de PDF, páginas de
PDF escaneado como imagen y capturas de una web con Chrome sin ventana.

Todo opcional: `pypdf` (texto de PDF) y `pypdfium2` (PDF escaneado → imagen) solo si están instalados; las capturas
usan el Chrome o Edge del PC en modo headless. Si falta algo, el error lo dice y cómo arreglarlo.
"""

import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
             ".gif": "image/gif"}
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".yml", ".yaml"}
MAX_PDF_PAGES = 30
MIN_TEXT_PER_PAGE = 80  # menos texto que esto por página = escaneado: se lee como imagen
VIEWPORTS = {"escritorio": (1280, 1600), "móvil": (390, 1400)}


class VisionError(Exception):
    pass


def image_part(path: Path) -> dict:
    mime = IMAGE_EXT.get(path.suffix.lower())
    if not mime:
        raise VisionError(f"{path.name} no es una imagen que entienda (png, jpg, webp, gif)")
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def pdf_text(path: Path) -> list[str]:
    """Texto de cada página (vacío si el PDF es escaneado)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise VisionError("para leer PDF hace falta pypdf: .venv\\Scripts\\python -m pip install pypdf") from None
    reader = PdfReader(str(path))
    return [(p.extract_text() or "").strip() for p in reader.pages[:MAX_PDF_PAGES]]


def pdf_page_images(path: Path, pages: list[int], out_dir: Path, scale: float = 1.6) -> list[Path]:
    """Páginas (desde 0) de un PDF escaneado como PNG, para el modelo de visión."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise VisionError("este PDF es escaneado; para leerlo hace falta pypdfium2: "
                          ".venv\\Scripts\\python -m pip install pypdfium2") from None
    pdf = pdfium.PdfDocument(str(path))
    out = []
    for i in pages:
        img = pdf[i].render(scale=scale).to_pil()
        target = out_dir / f"{path.stem}-p{i + 1}.png"
        img.save(target)
        out.append(target)
    return out


def browser() -> str | None:
    """Chrome o Edge del PC (para las capturas)."""
    env = os.environ.get("LOCALHARNESS_CHROME")
    if env and Path(env).is_file():
        return env
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        for rel in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
            p = Path(base) / rel
            if p.is_file():
                return str(p)
    return None


def screenshot(page: Path, out: Path, size: tuple[int, int], exe: str | None = None, timeout: float = 60) -> Path:
    """Captura de un .html local con Chrome headless (sin perfil del usuario: uno temporal)."""
    exe = exe or browser()
    if not exe:
        raise VisionError("no encuentro Chrome ni Edge para hacer capturas (o define LOCALHARNESS_CHROME)")
    with tempfile.TemporaryDirectory(prefix="lh-chrome-") as prof:
        cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               f"--user-data-dir={prof}", f"--window-size={size[0]},{size[1]}", f"--screenshot={out}",
               "--virtual-time-budget=3000", page.resolve().as_uri()]
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise VisionError(f"Chrome tardó más de {timeout:.0f} s en capturar {page.name}") from None
    if not out.is_file():
        raise VisionError(f"Chrome no dejó la captura de {page.name}")
    return out
