import typer

from .common import perform

app = typer.Typer(
    no_args_is_help=True,
    help="Run via editor or a supervised process; logs and runtime PNGs require managed mode.",
)


@app.command()
def run(
    mode: str = "managed",
    scene: str | None = None,
    current: bool = False,
    headless: bool = False,
    max_seconds: float = 3600,
    json_output: bool = typer.Option(False, "--json"),
):
    perform(
        "game.run",
        json_output,
        mode=mode,
        scene=scene,
        current=current,
        headless=headless,
        max_seconds=max_seconds,
    )


@app.command()
def stop(mode: str = "managed", json_output: bool = typer.Option(False, "--json")):
    perform("game.stop", json_output, mode=mode)


@app.command()
def status(mode: str = "managed", json_output: bool = typer.Option(False, "--json")):
    perform("game.status", json_output, mode=mode)


@app.command()
def logs(mode: str = "managed", json_output: bool = typer.Option(False, "--json")):
    perform("game.logs", json_output, mode=mode)


@app.command()
def screenshot(output: str = "game.png", json_output: bool = typer.Option(False, "--json")):
    """Capture the actual viewport of a graphical bridge-managed game."""
    perform("game.screenshot", json_output, output=output)
