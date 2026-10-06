import logging

# IsolatedAsyncioTestCase corre en modo debug: asyncio avisa de cada paso lento («Executing <Task…> took»).
logging.getLogger("asyncio").setLevel(logging.ERROR)
