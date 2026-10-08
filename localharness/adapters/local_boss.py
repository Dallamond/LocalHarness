"""Proveedor «local_boss»: el jefe local (boss.py) como un agente más. La tarea corre como cualquier otra (worktree,
oficina, revisión, integración, autopiloto), pero quien planifica, reparte, comprueba y revisa son los modelos
locales. El orquestador le prepara el mismo entorno que al MCP de delegación de Claude (servidores, log de
encargos, directo) y se lo pasa en `spec.env`."""

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

from localharness.adapters.base import Adapter, RunSpec
from localharness.adapters.local import _out
from localharness.events import Event


class LocalBossAdapter(Adapter):
    name = "local_boss"
    is_cli = False

    def __init__(self, binary: str | None = None, check: str | None = None, **_):
        super().__init__(binary)
        self.check = check

    def build_command(self, spec: RunSpec) -> list[str]:  # no es una CLI
        raise NotImplementedError

    def parse_line(self, obj: dict) -> list[Event]:
        return []

    async def execute(self, spec: RunSpec, on_event: Callable[[Event], None], timeout_s: float) -> dict:
        from localharness.boss import Boss, detect_check
        from localharness.mcp_local import NoModel, Server, ToolError

        loop = asyncio.get_running_loop()

        def say(text: str) -> None:  # desde el hilo del jefe: el evento se guarda en el bucle principal
            loop.call_soon_threadsafe(on_event, Event("progress", text=text))

        t0 = time.monotonic()
        env = {**spec.env, "LH_ROOT": spec.cwd, "LH_WRITE": "0" if spec.read_only else "1"}
        server = Server(env)
        check = self.check if self.check is not None else detect_check(Path(spec.cwd))
        # el jefe para entre pasos un poco antes del tope, para que dé tiempo al informe
        boss = Boss(server, check=check, say=say, deadline=t0 + max(60.0, timeout_s - 120))
        on_event(Event("progress", text="Jefe local: planifican, reparten, comprueban y revisan los modelos locales"))
        try:
            final = await asyncio.to_thread(boss.run, spec.prompt)
        except (NoModel, ToolError) as e:
            on_event(Event("error", text=f"Jefe local: {e}"))
            return _out("failed", round(time.monotonic() - t0, 1), str(e))
        on_event(Event("result", text=final))
        on_event(Event("usage", data={"cost_usd": 0.0}))
        return _out("done", round(time.monotonic() - t0, 1), final)
