"""Install the addon without overwriting unrelated or running editor files."""

import json
import shutil
from pathlib import Path

from .config import Config
from .errors import BridgeError
from .models import schemas


def addon_source() -> Path:
    packaged = Path(__file__).parent / "addon"
    source = Path(__file__).resolve().parents[2] / "addons/godot_bridge"
    return source if source.is_dir() else packaged


def install(config: Config, *, replace: bool = False) -> dict:
    if config.connection_file.exists():
        from .transport import Transport

        try:
            Transport(config).request("handshake", {})
        except BridgeError as exc:
            if exc.code != "EDITOR_DISCONNECTED":
                raise
        else:
            raise BridgeError(
                "EDITOR_BUSY", "Close this project's editor before installing its plugin."
            )
    destination = config.project / "addons/godot_bridge"
    if destination.exists() and not replace:
        raise BridgeError(
            "FILE_ACCESS_DENIED",
            "Plugin directory exists; use --replace for an intentional update.",
        )
    if not destination.resolve().is_relative_to(config.project):
        raise BridgeError("FILE_ACCESS_DENIED", "Plugin directory escapes the project.")
    shutil.copytree(
        addon_source(), destination, dirs_exist_ok=replace, ignore=shutil.ignore_patterns("*.uid")
    )
    (destination / "schemas.json").write_text(json.dumps(schemas(), indent=2), encoding="utf-8")
    return {
        "installed": str(destination),
        "next": "Enable GodotBridge in Project > Project Settings > Plugins.",
    }
