from typing import Annotated

import typer

from .common import perform

Viewport = Annotated[
    int,
    typer.Option(
        min=0, max=3, help="Editor 3D viewport index 0-3 (split layouts); only for --method editor."
    ),
]


def screenshot(
    output: str = "screenshot.png",
    method: str = "editor",
    width: int = 960,
    height: int = 640,
    viewpoint: str = "perspective",
    distance: float = 25,
    position: tuple[float, float, float] = (15, 13, 18),
    target: tuple[float, float, float] = (0, 0, 0),
    viewport: Viewport = 0,
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
        viewport=viewport,
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
    viewport: Viewport = 0,
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
        viewport=viewport,
    )


def camera_info(json_output: bool = typer.Option(False, "--json")):
    perform("editor.camera_info", json_output)
