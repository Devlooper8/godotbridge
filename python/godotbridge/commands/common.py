import json
from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console

from ..client import Client
from ..config import Config
from ..errors import BridgeError

options: dict[str, Any] = {}


def config() -> Config:
    return Config.load(options.get("project"), options.get("godot"), options.get("timeout"))


def emit(value: Any, machine: bool = False):
    if machine or options.get("json"):
        typer.echo(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False))
    else:
        Console().print_json(json.dumps(value, default=str))


def execute(action: Callable[[], Any], machine: bool = False):
    try:
        emit({"ok": True, "result": action()}, machine)
    except BridgeError as exc:
        emit({"ok": False, "error": exc.as_dict()}, machine)
        raise typer.Exit(exc.exit_code) from exc
    except (OSError, ValueError) as exc:
        emit({"ok": False, "error": {"code": "INVALID_ARGUMENT", "message": str(exc)}}, machine)
        raise typer.Exit(2) from exc


def perform(operation: str, machine: bool = False, **params: Any):
    execute(lambda: Client(config()).call(operation, **params), machine)
