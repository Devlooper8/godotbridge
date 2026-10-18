"""Regenerate the engine's checked-in schema from the shared Python registry."""

import json
from pathlib import Path

from godotbridge.models import schemas

root = Path(__file__).resolve().parents[1]
(root / "addons/godot_bridge/schemas.json").write_text(
    json.dumps(schemas(), indent=2) + "\n", encoding="utf-8"
)
