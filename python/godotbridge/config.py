"""Explicit project selection and workspace confinement."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import BridgeError


@dataclass(frozen=True)
class Config:
    project: Path
    godot: str | None = None
    timeout: float = 15.0

    @classmethod
    def load(
        cls,
        project: str | Path | None = None,
        godot: str | None = None,
        timeout: float | None = None,
    ) -> "Config":
        root = Path(project or os.getenv("GODOTBRIDGE_PROJECT", ".")).resolve()
        if root.is_file() and root.name == "project.godot":
            root = root.parent
        if not (root / "project.godot").is_file():
            raise BridgeError("PROJECT_NOT_FOUND", f"No project.godot in {root}; use --project.")
        settings = {}
        file = root / "godotbridge.toml"
        if file.exists():
            try:
                settings = tomllib.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise BridgeError("INVALID_ARGUMENT", f"Cannot read {file}: {exc}") from exc
        duration = timeout if timeout is not None else settings.get("timeout", 15.0)
        if not isinstance(duration, (int, float)) or not 0 < duration <= 600:
            raise BridgeError("INVALID_ARGUMENT", "Timeout must be between 0 and 600 seconds.")
        return cls(root, godot or os.getenv("GODOT_EXECUTABLE") or settings.get("godot"), duration)

    @property
    def connection_file(self) -> Path:
        return self.private_path("connection.json")

    def private_path(self, relative: str = "") -> Path:
        """Constrain internal workers and credential files even if .godot is linked."""
        directory = self.project / ".godot/godotbridge"
        target = (directory / relative).resolve()
        if not target.is_relative_to(self.project) or not target.is_relative_to(
            directory.resolve()
        ):
            raise BridgeError("FILE_ACCESS_DENIED", "Private bridge storage escapes the project.")
        return target

    def resource_path(self, value: str, *, suffix: str | None = None) -> Path:
        if not value.startswith("res://") or "\\" in value or ":" in value[6:]:
            raise BridgeError("FILE_ACCESS_DENIED", "Use a project-relative res:// path.")
        relative = Path(value[6:])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise BridgeError("FILE_ACCESS_DENIED", "Path traversal is not permitted.")
        target = (self.project / relative).resolve()
        if not target.is_relative_to(self.project) or any(
            p.startswith(".") for p in relative.parts
        ):
            raise BridgeError(
                "FILE_ACCESS_DENIED", "Path escapes the workspace or uses a private directory."
            )
        if suffix and target.suffix != suffix:
            raise BridgeError("INVALID_ARGUMENT", f"Expected a {suffix} file.")
        return target
