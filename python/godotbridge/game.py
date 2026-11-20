"""Select editor play APIs or a supervised standalone runtime explicitly."""

from typing import Any

from . import process_manager
from .errors import BridgeError


def dispatch(client, operation: str, arguments: dict[str, Any]) -> dict:
    if operation == "game.screenshot":
        return process_manager.screenshot(client, arguments["output"])
    if arguments.get("mode") == "editor":
        return client.transport.request(operation, arguments)
    if operation == "game.logs" and arguments.get("since") is not None:
        raise BridgeError(
            "INVALID_ARGUMENT", "since applies to editor-mode debugger logs, not managed stdout."
        )
    if operation == "game.status":
        return process_manager.status(client.config)
    if operation == "game.logs":
        return process_manager.logs(client.config)
    if operation == "game.stop":
        return process_manager.stop(client.config)
    scene = arguments["scene"]
    if arguments["current"]:
        scene = client.call("scene.current")["scene_path"]
        if not scene:
            raise BridgeError(
                "SCENE_NOT_FOUND",
                "The current scene is unsaved; save it first (scene.save_as) before running it as the current scene.",
            )
    if not scene:
        # ProjectSettings is authoritative; the client can read it in a headless
        # engine when no editor is available. Never parse project.godot as text.
        scene = client.call("project.info").get("main_scene")
    if not scene:
        raise BridgeError(
            "SCENE_NOT_FOUND", "No main scene configured; use --scene res://... or --current."
        )
    return process_manager.start(
        client.config, scene, arguments["headless"], arguments["max_seconds"]
    )
