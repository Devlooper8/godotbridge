import typer

from .common import perform

app = typer.Typer(
    no_args_is_help=True,
    help="Create standard Godot meshes, materials, collision, cameras and lights.",
)


def primitive_command(kind: str):
    def command(
        name: str = typer.Option(...),
        parent: str = ".",
        size: tuple[float, float, float] = (1, 1, 1),
        radius: float = 0.5,
        height: float = 1,
        color: tuple[float, float, float, float] = (0.55, 0.65, 0.8, 1),
        position: tuple[float, float, float] = (0, 0, 0),
        collision: bool = True,
        allow_tool_script: bool = typer.Option(False, help="Allow a parent with a @tool script."),
        json_output: bool = typer.Option(False, "--json"),
    ):
        perform(
            "3d.create_primitive",
            json_output,
            name=name,
            parent=parent,
            kind=kind,
            size=size,
            radius=radius,
            height=height,
            color=color,
            position=position,
            collision=collision,
            allow_tool_script=allow_tool_script,
        )

    command.__doc__ = f"Create a {kind} with material and optional collision as one undo action."
    return command


for _kind in ("box", "sphere", "cylinder", "plane"):
    app.command(f"create-{_kind}")(primitive_command(_kind))


@app.command("create-light")
def light(
    name: str = "Light",
    type: str = "directional",
    parent: str = ".",
    energy: float = 1,
    position: tuple[float, float, float] = (0, 5, 0),
    rotation: tuple[float, float, float] = (-45, -30, 0),
    color: tuple[float, float, float, float] = (1, 1, 1, 1),
    allow_tool_script: bool = typer.Option(False, help="Allow a parent with a @tool script."),
    json_output: bool = typer.Option(False, "--json"),
):
    perform(
        "3d.create_light",
        json_output,
        name=name,
        type=type,
        parent=parent,
        energy=energy,
        position=position,
        rotation=rotation,
        color=color,
        allow_tool_script=allow_tool_script,
    )


@app.command("create-camera")
def camera(
    name: str = "MainCamera",
    parent: str = ".",
    position: tuple[float, float, float] = (10, 8, 12),
    target: tuple[float, float, float] = (0, 0, 0),
    fov: float = 70,
    allow_tool_script: bool = typer.Option(False, help="Allow a parent with a @tool script."),
    json_output: bool = typer.Option(False, "--json"),
):
    perform(
        "3d.create_camera",
        json_output,
        name=name,
        parent=parent,
        position=position,
        target=target,
        fov=fov,
        allow_tool_script=allow_tool_script,
    )
