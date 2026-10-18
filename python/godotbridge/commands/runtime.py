import json

import typer

from ..client import Client
from .common import config, execute, perform

app = typer.Typer(
    no_args_is_help=True,
    help="Inspect the live nodes of an editor-played game (start one with game run --mode editor).",
)


debug_app = typer.Typer(no_args_is_help=True, help="Editor debugger state.")


@debug_app.command()
def status(json_output: bool = typer.Option(False, "--json")):
    """Report whether an editor-played game is running and stopped at a breakpoint."""
    perform("debug.status", json_output)


@app.command()
def tree(
    path: str = ".",
    max_nodes: int = 1000,
    json_output: bool = typer.Option(False, "--json"),
):
    """Read the running scene's node tree; PATH is relative to the running scene root."""
    perform("runtime.tree", json_output, path=path, max_nodes=max_nodes)


@app.command()
def inspect(path: str = ".", json_output: bool = typer.Option(False, "--json")):
    perform("runtime.inspect", json_output, path=path)


@app.command()
def properties(path: str = ".", json_output: bool = typer.Option(False, "--json")):
    perform("runtime.properties", json_output, path=path)


@app.command()
def get(path: str, property: str, json_output: bool = typer.Option(False, "--json")):
    perform("runtime.get_property", json_output, path=path, property=property)


@app.command("set")
def set_property(
    path: str,
    property: str,
    value: str,
    json_output: bool = typer.Option(False, "--json"),
):
    """Set a JSON value on a live node: runtime only, never saved to the scene."""
    execute(
        lambda: Client(config()).call(
            "runtime.set_property", path=path, property=property, value=json.loads(value)
        ),
        json_output,
    )
