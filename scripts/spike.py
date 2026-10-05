"""M0 — comprobaciones con las CLI REALES en tu PC (Windows). Gasta muy pocos tokens de tu suscripción.

Uso (desde la carpeta LocalHarness):   py -3.12 scripts/spike.py
Qué hace:
  1. Versión y método de login de `claude` (debe ser 'claude.ai' = suscripción, NO api_key).
  2. Captura la salida real de `claude -p --output-format stream-json` y de `codex exec --json`
     en tests/fixtures_reales/*.jsonl y la pasa por nuestros parsers (ver qué eventos salen).
  3. Prueba si `--tools Read` impide de verdad que Claude escriba un archivo.
  4. Escribe tests/fixtures_reales/informe.json con el resumen. NO guarda credenciales.
No toca tus repos: trabaja en un repo git temporal.
"""
import asyncio, json, shutil, subprocess, sys, tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from localharness.adapters import get_adapter                      # noqa: E402
from localharness.adapters.base import RunSpec                     # noqa: E402
from localharness.adapters.claude import login_method              # noqa: E402
from localharness.binaries import resolve                         # noqa: E402
from localharness.runner import run                                # noqa: E402

OUT = ROOT / "tests" / "fixtures_reales"
OUT.mkdir(parents=True, exist_ok=True)
report: dict = {}


def tmp_repo() -> Path:
    d = Path(tempfile.mkdtemp(prefix="lh-spike-"))
    for a in (["init", "-q", "-b", "main"], ["config", "user.email", "s@s"], ["config", "user.name", "s"]):
        subprocess.run(["git", *a], cwd=d, check=True)
    (d / "README.md").write_text("spike\n")
    subprocess.run(["git", "add", "-A"], cwd=d, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=d, check=True)
    return d


async def capture(provider: str, prompt: str, name: str, **spec_kw) -> dict:
    """Usa el mismo runner que LocalHarness (binario resuelto sin cmd.exe, prompt por stdin, CLI aislada)."""
    repo = tmp_repo()
    adapter = get_adapter(provider)
    lines: list[str] = []
    orig_parse = adapter.parse
    adapter.parse = lambda line: (lines.append(line.rstrip("\n")), orig_parse(line))[1]  # guarda la salida cruda
    events = []
    res = await run(adapter, RunSpec(prompt=prompt, cwd=str(repo), **spec_kw), events.append, timeout_s=300)
    text = "\n".join(lines) + "\n"
    (OUT / f"{name}.jsonl").write_text(text, encoding="utf-8")
    raw_types = Counter(json.loads(l).get("type") for l in lines if l.strip().startswith("{"))
    return {"status": res["status"], "exit_code": res["exit_code"],
            "eventos_normalizados": dict(Counter(e.kind for e in events)), "tipos_crudos": dict(raw_types),
            "errores": [e.text[-500:] for e in events if e.kind == "error"],
            "archivos_creados": sorted(f.name for f in repo.iterdir() if f.name not in (".git", "README.md"))}


async def main() -> None:
    claude = shutil.which("claude")
    report["claude_ruta"] = resolve("claude")[-1] if claude else None
    if claude:
        report["claude_version"] = subprocess.run([*resolve("claude"), "--version"], capture_output=True,
                                                  text=True).stdout.strip()
        report["claude_login"] = login_method("claude")
        if report["claude_login"] != "claude.ai":
            print(f"AVISO: el login de claude es {report['claude_login']!r}, no 'claude.ai'. "
                  "Haz `claude auth login` con tu cuenta (suscripción) antes de seguir.")
    report["codex_ruta"] = shutil.which("codex")

    if claude:
        print("1/3 claude -p (stream-json)…")
        report["claude_salida_real"] = await capture(
            "claude", "Responde solo con la palabra: ok", "claude_real", max_turns=1, read_only=True)
        print("2/3 ¿--tools Read impide escribir? (pide crear un archivo con solo Read)…")
        report["claude_limite_tools"] = await capture(
            "claude", "Crea un archivo llamado prueba.txt con el texto hola y confirma.", "claude_limite_tools",
            max_turns=3, allowed_tools=["Read"])
    if report["codex_ruta"]:
        print("3/3 codex exec --json…")
        report["codex_salida_real"] = await capture(
            "codex", "Responde solo con la palabra: ok", "codex_real", read_only=True)
    (OUT / "informe.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nListo. Pásame {OUT / 'informe.json'} y los .jsonl (no contienen credenciales).")


asyncio.run(main())
