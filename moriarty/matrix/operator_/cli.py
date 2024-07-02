import asyncio
from functools import wraps

import click
import uvicorn

from moriarty.matrix.operator_.config import get_config
from moriarty.matrix.operator_.dbutils import (
    drop_all_data,
    get_db_url,
    upgrade_in_place,
)

from .api_app import app as api_app
from .callback_app import app as callback_app
from .daemon import BridgeDaemon, KubeAutoscalerDaemon


def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))

    return wrapper


@click.command()
@click.option("--host", type=click.STRING, default="0.0.0.0")
@click.option("--port", type=click.INT, default=8999)
def callback(host, port):
    """
    Start the server.
    """
    uvicorn.run(callback_app, host=host, port=port)


@click.command()
@click.option("--host", type=click.STRING, default="0.0.0.0")
@click.option("--port", type=click.INT, default=8902)
def callback(host, port):
    """
    Start the server.
    """
    uvicorn.run(api_app, host=host, port=port)


@click.command()
@coro
async def autoscale():
    """
    Start autoscaling daemon for k8s.
    """
    await KubeAutoscalerDaemon(get_config()).run_forever()


@click.command()
@coro
async def bridge():
    """
    Start bridge daemon.
    """
    await BridgeDaemon(get_config()).run_forever()


@click.command()
def init():
    """
    Init and upgrade the database.
    """

    config = get_config()

    upgrade_in_place(
        db_url=get_db_url(config, async_mode=False),
    )


@click.command()
@click.option("--yes", "-y", is_flag=True, default=False)
def drop(yes):
    """
    Drop all data before testing or other purposes.

    This command is not visible in the CLI. Only use it in tests for now.
    """
    if not yes:
        click.confirm("Are you sure you want to drop all data?", abort=True)

    click.echo("Dropping all data...")

    config = get_config()
    db_url = get_db_url(config, async_mode=False)
    drop_all_data(db_url)


@click.group()
def cli():
    pass


cli.add_command(init)
cli.add_command(bridge)
cli.add_command(autoscale)
cli.add_command(callback)
# cli.add_command(drop) # noqa: not visible in CLI
