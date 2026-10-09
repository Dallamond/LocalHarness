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

    def __init__(self, binary: str | None = None, check: str | None = None, cerebro: int | None = None,
                 roles: dict | None = None, **_):
        super().__init__(binary)
        self.check = check
        self.cerebro = cerebro  # 2 = cerebro.Cerebro (diagnóstico, escalera de arreglo, pensamiento por papel)
        self.roles = roles  # cambios a cerebro.ROLES para este agente

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
        deadline = t0 + max(60.0, timeout_s - 120)
        v2 = str(self.cerebro or "") == "2"
        if v2:
            from localharness.cerebro import Cerebro
            boss = Cerebro(server, check=check, say=say, deadline=deadline, roles=self.roles)
        else:
            boss = Boss(server, check=check, say=say, deadline=deadline)
        on_event(Event("progress", text=f"Jefe local{' (cerebro 2)' if v2 else ''}: planifican, reparten, "
                                        "comprueban y revisan los modelos locales"))
        try:
            final = await asyncio.to_thread(boss.run, spec.prompt)
        except (NoModel, ToolError) as e:
            on_event(Event("error", text=f"Jefe local: {e}"))
            return _out("failed", round(time.monotonic() - t0, 1), str(e))
        on_event(Event("result", text=final))
        on_event(Event("usage", data={"cost_usd": 0.0}))
        # guardias o revisión en contra: no se puede integrar (el informe empieza por boss.REJECTED y dice por qué)
        return _out("failed" if boss.rejected else "done", round(time.monotonic() - t0, 1), final)
