"""Lanza una CLI como subproceso, lee su JSONL línea a línea y emite eventos normalizados."""

import asyncio
import os
import time
from collections.abc import Callable

from localharness.adapters.base import Adapter, RunSpec
from localharness.binaries import resolve
from localharness.events import Event


async def run(adapter: Adapter, spec: RunSpec, on_event: Callable[[Event], None],
              timeout_s: float = 1800.0, env: dict[str, str] | None = None) -> dict:
    if not adapter.is_cli:  # p. ej. llama-server por HTTP
        return await adapter.execute(spec, on_event, timeout_s)
    cmd = adapter.build_command(spec)
    cmd = [*resolve(cmd[0]), *cmd[1:]]  # en Windows: shim .cmd de npm -> exe real, sin cmd.exe
    stdin_text = adapter.stdin_text(spec)
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=spec.cwd,
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**{k: v for k, v in os.environ.items() if k not in adapter.env_remove}, **(env or {})},
            limit=16 * 1024 * 1024,  # líneas JSON largas (diffs, salidas de herramientas)
        )
    except (FileNotFoundError, PermissionError, OSError) as e:
        on_event(Event("error", text=f"No se puede lanzar {cmd[0]}: {e}"))
        return {"status": "failed", "exit_code": None, "duration_s": 0.0, "final": None, "structured": None}

    final: str | None = None
    structured: dict | None = None
    errored = False
    stderr_buf: list[str] = []

    async def pump_out():
        nonlocal final, errored, structured
        async for raw in proc.stdout:
            for ev in adapter.parse(raw.decode("utf-8", "replace")):
                if ev.kind == "result":
                    final = ev.text
                    structured = ev.data.get("structured")
                elif ev.kind == "error":
                    errored = True
                on_event(ev)

    async def feed_in():
        if stdin_text is None:
            return
        try:
            proc.stdin.write(stdin_text.encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # la CLI terminó sin leer: su código de salida lo dirá
        finally:
            proc.stdin.close()

    async def pump_err():
        async for raw in proc.stderr:
            stderr_buf.append(raw.decode("utf-8", "replace"))

    status = "done"
    try:
        await asyncio.wait_for(asyncio.gather(feed_in(), pump_out(), pump_err(), proc.wait()), timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        status = "timeout"
        on_event(Event("error", text=f"Tiempo agotado ({timeout_s:.0f} s)"))
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    if status == "done" and (proc.returncode != 0 or errored):
        status = "failed"
        if stderr_buf:
            on_event(Event("error", text="".join(stderr_buf)[-2000:]))
    return {"status": status, "exit_code": proc.returncode, "duration_s": time.monotonic() - t0, "final": final,
            "structured": structured}
