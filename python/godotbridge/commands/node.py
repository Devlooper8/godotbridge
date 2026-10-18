import json

import typer

from ..client import Client
from .common import config, execute, perform

app = typer.Typer(
    no_args_is_help=True,
    help="Undoable scene node operations; paths are relative to the scene root.",
)


@app.command("add")
def add(
    name: str = typer.Option(...),
    type: str = "Node3D",
    parent: str = ".",
    json_output: bool = typer.Option(False, "--json"),
    allow_tool_script: bool = typer.Option(False, help="Allow mutating nodes with a @tool script."),
):
    perform(
        "node.create",
        json_output,
        name=name,
        type=type,
        parent=parent,
        allow_tool_script=allow_tool_script,
    )


@app.command()
def remove(
    path: str,
    json_output: bool = typer.Option(False, "--json"),
    allow_tool_script: bool = typer.Option(False, help="Allow mutating nodes with a @tool script."),
):
    perform("node.delete", json_output, path=path, allow_tool_script=allow_tool_script)


@app.command()
def duplicate(
    path: str,
    name: str | None = None,
    json_output: bool = typer.Option(False, "--json"),
    allow_tool_script: bool = typer.Option(False, help="Allow mutating nodes with a @tool script."),
):
    perform(
        "node.duplicate",
        json_output,
        path=path,
        name=name,
        allow_tool_script=allow_tool_script,
    )


@app.command()
def rename(
    path: str,
    name: str,
    json_output: bool = typer.Option(False, "--json"),
    allow_tool_script: bool = typer.Option(False, help="Allow mutating nodes with a @tool script."),
):
    perform("node.rename", json_output, path=path, name=name, allow_tool_script=allow_tool_script)


@app.command()
def reparent(
    path: str,
    parent: str,
    keep_global: bool = True,
    json_output: bool = typer.Option(False, "--json"),
    allow_tool_script: bool = typer.Option(False, help="Allow mutating nodes with a @tool script."),
):
    perform(
        "node.reparent",
        json_output,
        path=path,
        parent=parent,
        keep_global=keep_global,
        allow_tool_script=allow_tool_script,
    )


@app.command()
def inspect(path: str = ".", json_output: bool = typer.Option(False, "--json")):
    perform("node.inspect", json_output, path=path)


@app.command()
def select(path: str, json_output: bool = typer.Option(False, "--json")):
    perform("editor.select", json_output, path=path)


@app.command()
def properties(path: str = ".", json_output: bool = typer.Option(False, "--json")):
    perform("node.properties", json_output, path=path)


@app.command()
def get(path: str, property: str, json_output: bool = typer.Option(False, "--json")):
    perform("node.get_property", json_output, path=path, property=property)


@app.command("set")
def set_property(
    path: str,
    property: str,
    value: str,
    json_output: bool = typer.Option(False, "--json"),
    allow_tool_script: bool = typer.Option(False, help="Allow mutating nodes with a @tool script."),
):
    """Set a JSON value: true, a number, a quoted string, or a typed object."""
    execute(
        lambda: Client(config()).call(
            "node.set_property",
            path=path,
            property=property,
            value=json.loads(value),
            allow_tool_script=allow_tool_script,
        ),
        json_output,
    )


def transform_command(field: str, translate: bool = False):
    def command(
        path: str,
        x: float,
        y: float,
        z: float,
        world: bool = False,
        allow_tool_script: bool = typer.Option(
            False, help="Allow mutating nodes with a @tool script."
        ),
        json_output: bool = typer.Option(False, "--json"),
    ):
        perform(
            "node.set_transform",
            json_output,
            path=path,
            world=world,
            translate=translate,
            allow_tool_script=allow_tool_script,
            **{field: [x, y, z]},
        )

    command.__doc__ = f"Set {field} in {'degrees' if field == 'rotation' else 'Godot units'}; --world uses world space."
    return command


for _name in ("position", "rotation", "scale"):
    app.command(_name, context_settings={"ignore_unknown_options": True})(transform_command(_name))
app.command("translate", context_settings={"ignore_unknown_options": True})(
    transform_command("position", translate=True)
)
