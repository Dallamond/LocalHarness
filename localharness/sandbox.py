"""Entorno de pruebas listo para usar: un repo pequeño con fallos a propósito y agentes ya configurados.

    python -m localharness sandbox            # crea ~/LocalHarness-sandbox y lo registra (idempotente)
    python -m localharness sandbox --reset    # lo rehace desde cero (borra el repo de pruebas)
"""

import shutil
import subprocess
from pathlib import Path

from localharness.store import Store

FILES = {
    "README.md": """# Tienda de pruebas

Proyecto pequeño para probar LocalHarness. Tiene fallos a propósito:

- `calc.py`: `suma` resta y `divide` no controla la división entre cero.
- `inventario.py`: `valor_total` ignora las cantidades.
- Faltan tests de `inventario.py`.
""",
    "calc.py": '''def suma(a, b):
    return a - b


def resta(a, b):
    return a - b


def divide(a, b):
    return a / b
''',
    "inventario.py": '''from dataclasses import dataclass


@dataclass
class Producto:
    nombre: str
    precio: float
    cantidad: int


def valor_total(productos: list[Producto]) -> float:
    """Valor del inventario: precio × cantidad de cada producto."""
    return sum(p.precio for p in productos)


def agotados(productos: list[Producto]) -> list[str]:
    return [p.nombre for p in productos if p.cantidad == 0]
''',
    "tests/test_calc.py": '''import unittest

from calc import resta


class TestCalc(unittest.TestCase):
    def test_resta(self):
        self.assertEqual(resta(5, 3), 2)


if __name__ == "__main__":
    unittest.main()
''',
    "tests/__init__.py": "",
}

# nombre: (proveedor, modelo, rol, config). Los de Claude con topes bajos para gastar poco plan.
AGENTS = {
    "qwen-director": ("local", None, "director", {}),
    "qwen-jefe": ("local", None, "jefe", {"skills": ["revision-de-diff"]}),
    "qwen-agente": ("local_agent", None, "trabajador", {"max_turns": 20}),  # bucle con herramientas e internet
    "haiku-director": ("claude", "haiku", "director", {"max_turns": 6, "max_budget_usd": 0.3}),
    "haiku-jefe": ("claude", "haiku", "jefe", {"max_turns": 4, "max_budget_usd": 0.2, "skills": ["revision-de-diff"]}),
    "sonnet-trabajador": ("claude", "sonnet", "trabajador", {"max_turns": 12, "max_budget_usd": 0.5,
                                                            "skills": ["cambios-minimos"]}),
}

DEFAULT_PATH = Path.home() / "LocalHarness-sandbox"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def create(store: Store, path: Path = DEFAULT_PATH, reset: bool = False) -> list[str]:
    log = []
    path = path.resolve()
    if reset and path.exists():
        shutil.rmtree(path, onerror=lambda f, p, e: (Path(p).chmod(0o700), f(p)))
        wt = path.parent / ".localharness-worktrees" / path.name
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)
        log.append(f"borrado {path}")
    if not (path / ".git").exists():
        path.mkdir(parents=True, exist_ok=True)
        for name, text in FILES.items():
            f = path / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8", newline="\n")
        _git(path, "init", "-q", "-b", "main")
        _git(path, "add", "-A")
        _git(path, "-c", "user.name=localharness", "-c", "user.email=localharness@local", "commit", "-q",
             "-m", "Tienda de pruebas")
        log.append(f"repo creado en {path}")
    project = next((p for p in store.list_projects() if Path(p["repo_path"]) == path), None)
    if project is None:
        name = "sandbox" if not store.find_project("sandbox") else f"sandbox-{len(store.list_projects()) + 1}"
        project = store.add_project(name, str(path))
        log.append(f"proyecto «{project['name']}» registrado")
    for name, (provider, model, role, cfg) in AGENTS.items():
        if not store.find_agent(name):
            store.add_agent(name, provider, model=model, role=role, config=cfg)
            log.append(f"agente {name} ({provider}{'/' + model if model else ''}, {role})")
    return log
