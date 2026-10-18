"""Stable errors shared by command-line, MCP and transport layers."""

from typing import Any


class BridgeError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_dict(self) -> dict[str, Any]:
        result = {"code": self.code, "message": self.message}
        if self.details is not None:
            result["details"] = self.details
        return result

    @property
    def exit_code(self) -> int:
        if self.code in {"EDITOR_DISCONNECTED", "GODOT_NOT_FOUND", "PROJECT_NOT_FOUND"}:
            return 3
        if self.code == "TIMEOUT":
            return 4
        if self.code == "AUTHENTICATION_FAILED":
            return 5
        if self.code.startswith(("INVALID", "UNSUPPORTED")):
            return 2
        return 1
