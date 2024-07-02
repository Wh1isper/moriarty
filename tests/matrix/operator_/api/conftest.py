from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import redis
from click.testing import CliRunner
from fastapi.testclient import TestClient

from moriarty import mock
from moriarty.matrix.operator_.api_app import app as APP
from moriarty.matrix.operator_.cli import drop
from moriarty.matrix.operator_.spawner.manager import (
    SpawnerManager,
    get_spawner_manager,
    get_spawner_name,
)


@pytest.fixture
def spawner_manager():
    spawner_manager = SpawnerManager()
    spawner_manager._load_dir(mock)

    yield spawner_manager


@pytest.fixture
async def app(pg_port, redis_port, monkeypatch):
    monkeypatch.setenv("REDIS_PORT", str(redis_port))
    monkeypatch.setenv("DB_PORT", str(pg_port))

    runner = CliRunner()
    # Drop all before testing
    result = runner.invoke(drop, ["--yes"])
    assert result.exit_code == 0

    # Clear redis data
    redis_client = redis.Redis(host="localhost", port=redis_port)
    redis_client.flushall()

    APP.dependency_overrides = {
        get_spawner_name: lambda: "mock",
        get_spawner_manager: lambda: spawner_manager,
    }
    yield APP


@pytest.fixture
def client(app):
    return TestClient(app)
