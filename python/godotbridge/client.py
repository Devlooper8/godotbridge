"""Common backend for Python, CLI and MCP."""

from typing import Any

from pydantic import ValidationError

from .config import Config
from .errors import BridgeError
from .models import OPERATIONS
from .transport import Transport


class Client:
    def __init__(self, config: Config):
        self.config = config
        self.transport = Transport(config)

    def call(self, operation: str, **params: Any) -> dict[str, Any]:
        if operation not in OPERATIONS:
            raise BridgeError("UNSUPPORTED_OPERATION", f"Unknown operation: {operation}")
        try:
            arguments = (
                OPERATIONS[operation].arguments.model_validate(params).model_dump(mode="json")
            )
        except ValidationError as exc:
            raise BridgeError("INVALID_ARGUMENT", str(exc)) from exc
        if operation.startswith("game."):
            from .game import dispatch

            return dispatch(self, operation, arguments)
        if operation in {"viewport.capture", "scene.snapshot"}:
            from .artifacts import capture, snapshot

            return (capture if operation == "viewport.capture" else snapshot)(self, arguments)
        if operation in {
            "project.validate",
            "project.import",
            "project.open",
            "project.check_script",
        }:
            from .headless import check_script, import_project, open_project, validate_project

            functions = {
                "project.validate": validate_project,
                "project.import": import_project,
                "project.open": open_project,
                "project.check_script": check_script,
            }
            return functions[operation](self.config, **arguments)
        try:
            return self.transport.request(operation, arguments)
        except BridgeError as exc:
            if operation == "project.info" and exc.code == "EDITOR_DISCONNECTED":
                from .headless import project_info

                return project_info(self.config)
            raise
