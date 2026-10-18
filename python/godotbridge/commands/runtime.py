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


@debug_app.command("breakpoints")
def list_breakpoints(json_output: bool = typer.Option(False, "--json")):
    """List breakpoints the next run will hit (bridge-set and script-editor ones)."""
    perform("debug.breakpoints", json_output)


@debug_app.command("set-breakpoints")
def set_breakpoints(
    path: str,
    lines: list[int],
    json_output: bool = typer.Option(False, "--json"),
):
    """Replace PATH's bridge breakpoints with the 1-based LINES (res:// .gd script)."""
    perform("debug.set_breakpoints", json_output, path=path, lines=lines)


@debug_app.command("clear-breakpoints")
def clear_breakpoints(path: str | None = None, json_output: bool = typer.Option(False, "--json")):
    """Remove the bridge breakpoints of one script, or all of them."""
    perform("debug.clear_breakpoints", json_output, path=path)


@debug_app.command()
def stack(json_output: bool = typer.Option(False, "--json")):
    """Script frames (file, line, function) of a game stopped at a breakpoint."""
    perform("debug.stack", json_output)


@debug_app.command()
def variables(
    frame: int = 0,
    scope: str = "locals",
    json_output: bool = typer.Option(False, "--json"),
):
    """Typed locals, members or globals of a stack frame of the stopped game."""
    perform("debug.variables", json_output, frame=frame, scope=scope)


@debug_app.command("continue")
def continue_(json_output: bool = typer.Option(False, "--json")):
    perform("debug.continue", json_output)


@debug_app.command()
def step(kind: str = "over", json_output: bool = typer.Option(False, "--json")):
    """Step over, in or out. After pause use `step in`: a paused game has no frame to step over."""
    perform("debug.step", json_output, kind=kind)


@debug_app.command()
def pause(json_output: bool = typer.Option(False, "--json")):
    """Stop the running game at a frame boundary (no script frames until you step in)."""
    perform("debug.pause", json_output)


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
