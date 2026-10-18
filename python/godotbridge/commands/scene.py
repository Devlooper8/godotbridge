import typer

from .common import perform

app = typer.Typer(
    no_args_is_help=True, help="Inspect, create, open and save scenes through the editor."
)


@app.command("list")
def list_scenes(json_output: bool = typer.Option(False, "--json")):
    perform("scene.list", json_output)


@app.command()
def current(json_output: bool = typer.Option(False, "--json")):
    perform("scene.current", json_output)


@app.command()
def tree(json_output: bool = typer.Option(False, "--json")):
    perform("scene.tree", json_output)


@app.command("open")
def open_scene(path: str, json_output: bool = typer.Option(False, "--json")):
    perform("scene.open", json_output, path=path)


@app.command()
def create(path: str, root: str = "Node3D", json_output: bool = typer.Option(False, "--json")):
    perform("scene.create", json_output, path=path, root=root)


@app.command()
def save(json_output: bool = typer.Option(False, "--json")):
    perform("scene.save", json_output)


@app.command("save-as")
def save_as(path: str, json_output: bool = typer.Option(False, "--json")):
    perform("scene.save_as", json_output, path=path)


@app.command()
def close(json_output: bool = typer.Option(False, "--json")):
    """Close the scene, refusing to discard unsaved changes."""
    perform("scene.close", json_output)
