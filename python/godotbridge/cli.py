"""Thin Typer adapters around the shared client."""

import platform
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import typer

from .client import Client
from .commands.common import config, emit, execute, options, perform
from .commands.game import app as game_app
from .commands.node import app as node_app
from .commands.runtime import app as runtime_app
from .commands.runtime import debug_app
from .commands.scene import app as scene_app
from .commands.three_d import app as three_d_app
from .commands.visual import camera_info, screenshot, snapshot
from .discovery import discover
from .errors import BridgeError
from .install import install

app = typer.Typer(
    no_args_is_help=True, help="GodotBridge: authenticated Godot 4 editor automation."
)
# Typer >=0.22 vendors Click, so its usage errors no longer subclass click.ClickException;
# resolve the base from Typer itself to stay correct with both layouts.
ClickException = next(c for c in typer.BadParameter.__mro__ if c.__name__ == "ClickException")
project_app = typer.Typer(no_args_is_help=True)
editor_app = typer.Typer(no_args_is_help=True)
app.add_typer(project_app, name="project")
app.add_typer(editor_app, name="editor")
app.add_typer(scene_app, name="scene")
app.add_typer(node_app, name="node")
app.add_typer(three_d_app, name="3d")
app.add_typer(game_app, name="game")
app.add_typer(runtime_app, name="runtime")
app.add_typer(debug_app, name="debug")
scene_app.command("snapshot")(snapshot)
editor_app.command("screenshot")(screenshot)
editor_app.command("camera-info")(camera_info)


@app.callback()
def setup(
    project: Path = typer.Option(Path("."), envvar="GODOTBRIDGE_PROJECT"),
    godot: str | None = typer.Option(None, envvar="GODOT_EXECUTABLE"),
    timeout: float | None = typer.Option(None, min=0.01, max=600),
    connect_wait: float | None = typer.Option(
        None,
        min=0,
        max=600,
        help="Seconds one operation may wait for the editor endpoint to become reachable.",
    ),
    json_output: bool = typer.Option(False, "--json"),
):
    """Global options may precede any command; --json also works after commands."""
    options.update(
        project=project,
        godot=godot,
        timeout=timeout,
        connect_wait=connect_wait,
        json=json_output,
    )


@app.command()
def doctor(json_output: bool = typer.Option(False, "--json")):
    """Report environment, executable, project, plugin and authenticated connection."""
    result: dict[str, Any] = {"python": platform.python_version()}
    try:
        executable = config().godot
    except BridgeError:
        executable = options.get("godot")
    for name, action in {
        "godot": lambda: asdict(discover(executable)),
        "project": lambda: str(config().project),
        "plugin_installed": lambda: (config().project / "addons/godot_bridge/plugin.cfg").is_file(),
        "connection": lambda: Client(config()).call("editor.status"),
        "capabilities": lambda: Client(config()).transport.request("handshake", {})["capabilities"],
    }.items():
        try:
            result[name] = action()
        except BridgeError as exc:
            result[name] = {"error": exc.as_dict()}
    emit(result, json_output)
    if any(isinstance(v, dict) and "error" in v for v in result.values()):
        raise typer.Exit(3)


@project_app.command("info")
def project_info(json_output: bool = typer.Option(False, "--json")):
    perform("project.info", json_output)


@editor_app.command("status")
def editor_status(json_output: bool = typer.Option(False, "--json")):
    perform("editor.status", json_output)


@project_app.command("install-plugin")
def install_plugin(replace: bool = False, json_output: bool = typer.Option(False, "--json")):
    """Copy the bundled plugin; enable it in Project Settings > Plugins."""
    execute(lambda: install(config(), replace=replace), json_output)


@project_app.command("validate")
def validate(json_output: bool = typer.Option(False, "--json")):
    perform("project.validate", json_output)


@project_app.command("import")
def import_project(json_output: bool = typer.Option(False, "--json")):
    perform("project.import", json_output)


@project_app.command("open")
def open_project(json_output: bool = typer.Option(False, "--json")):
    perform("project.open", json_output)


@project_app.command("check-script")
def check_script(path: str, json_output: bool = typer.Option(False, "--json")):
    perform("project.check_script", json_output, path=path)


@editor_app.command()
def undo(json_output: bool = typer.Option(False, "--json")):
    perform("editor.undo", json_output)


@editor_app.command()
def redo(json_output: bool = typer.Option(False, "--json")):
    perform("editor.redo", json_output)


@editor_app.command("inspect")
def inspect_node(path: str, json_output: bool = typer.Option(False, "--json")):
    """Replace the editor selection with PATH and open it in the Inspector; scene is unchanged."""
    perform("editor.select", json_output, path=path)


@editor_app.command("focus")
def focus_node(path: str, json_output: bool = typer.Option(False, "--json")):
    """Replace the editor selection with PATH and switch to the 3D workspace; camera is not moved."""
    perform("editor.focus", json_output, path=path)


@editor_app.command("diagnostics")
def diagnostics(json_output: bool = typer.Option(False, "--json")):
    perform("editor.diagnostics", json_output)


def main():
    try:
        result = app(standalone_mode=False)
        if isinstance(result, int):
            raise SystemExit(result)
    except ClickException as exc:
        if "--json" in sys.argv:
            emit(
                {
                    "ok": False,
                    "error": {"code": "INVALID_ARGUMENT", "message": exc.format_message()},
                },
                True,
            )
        else:
            exc.show()
        raise SystemExit(exc.exit_code) from exc


if __name__ == "__main__":
    main()
