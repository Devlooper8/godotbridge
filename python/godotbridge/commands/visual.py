import typer

from .common import perform


def screenshot(
    output: str = "screenshot.png",
    method: str = "editor",
    width: int = 960,
    height: int = 640,
    viewpoint: str = "perspective",
    distance: float = 25,
    position: tuple[float, float, float] = (15, 13, 18),
    target: tuple[float, float, float] = (0, 0, 0),
    json_output: bool = typer.Option(False, "--json"),
):
    """Capture a real editor viewport or --method preview. Output is relative to the project."""
    perform(
        "viewport.capture",
        json_output,
        output=output,
        method=method,
        width=width,
        height=height,
        viewpoint=viewpoint,
        distance=distance,
        position=position,
        target=target,
    )


def snapshot(
    output_dir: str = "snapshots",
    method: str = "preview",
    width: int = 960,
    height: int = 640,
    viewpoint: str = "perspective",
    distance: float = 25,
    position: tuple[float, float, float] = (15, 13, 18),
    target: tuple[float, float, float] = (0, 0, 0),
    json_output: bool = typer.Option(False, "--json"),
):
    """Save structured scene metadata and a PNG; report partial status if capture is unavailable."""
    perform(
        "scene.snapshot",
        json_output,
        output_dir=output_dir,
        method=method,
        width=width,
        height=height,
        viewpoint=viewpoint,
        distance=distance,
        position=position,
        target=target,
    )


def camera_info(json_output: bool = typer.Option(False, "--json")):
    perform("editor.camera_info", json_output)
