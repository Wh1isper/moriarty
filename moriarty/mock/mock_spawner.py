from moriarty.log import logger
from moriarty.matrix.operator_.spawner.plugin import Spawner, hookimpl


class MockSpawner(Spawner):
    register_name = "mock"

    async def prepare(self) -> None:
        pass


@hookimpl
def register(manager):
    manager.register(MockSpawner)
