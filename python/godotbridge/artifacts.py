"""Workspace-confined artifact handling, PNG verification and honest partial snapshots."""

import hashlib
import json
import os
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .errors import BridgeError

if TYPE_CHECKING:
    from .client import Client


def output_path(client: "Client", value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = client.config.project / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(client.config.project) or resolved == client.config.project:
        raise BridgeError(
            "FILE_ACCESS_DENIED", "Artifacts must remain inside the configured project."
        )
    relative = resolved.relative_to(client.config.project)
    if any(part.startswith(".") for part in relative.parts):
        raise BridgeError(
            "FILE_ACCESS_DENIED", "Do not write artifacts into private project directories."
        )
    return resolved


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise BridgeError("CAPTURE_UNAVAILABLE", "Capture is not a valid PNG image.")
    return struct.unpack("!II", header[16:24])


def capture(client: "Client", params: dict[str, Any]) -> dict[str, Any]:
    params = params.copy()
    output = output_path(client, params.pop("output", "viewport.png"))
    if output.exists():
        raise BridgeError(
            "FILE_ACCESS_DENIED", "Capture destination exists; choose a new filename."
        )
    # The plugin chooses a random private artifact path; no caller-controlled paths reach it.
    result = client.transport.request("viewport.capture", params)
    source = Path(result["artifact_path"]).resolve()
    cache = client.config.private_path("captures")
    if (
        not source.is_relative_to(cache)
        or source.suffix != ".png"
        or source.stat().st_size > 32 * 1024 * 1024
    ):
        raise BridgeError("FILE_ACCESS_DENIED", "Invalid capture artifact returned by the editor.")
    dimensions = png_dimensions(source)
    if dimensions != (params["width"], params["height"]):
        raise BridgeError("CAPTURE_UNAVAILABLE", "Screenshot dimensions differ from the request.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(source.read_bytes())
    source.unlink()
    result["artifact_path"] = str(output)
    return result


def snapshot(client: "Client", params: dict[str, Any]) -> dict[str, Any]:
    params = params.copy()
    directory = output_path(client, params.pop("output_dir"))
    if directory.exists() and any(directory.iterdir()):
        raise BridgeError(
            "FILE_ACCESS_DENIED", "Snapshot directory is not empty; choose a new directory."
        )
    tree = client.call("scene.tree")
    identity = client.call("project.info")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "scene.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    metadata: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "godot_version": identity["godot_version"],
        "project_identifier": hashlib.sha256(os.fsencode(client.config.project)).hexdigest()[:16],
        "scene_path": tree["scene_path"],
        "status": "complete",
        "warnings": [],
        "viewpoint": params["viewpoint"],
        "width": None,
        "height": None,
        "capture_method": None,
    }
    try:
        image = capture(client, {**params, "output": str(directory / "viewport.png")})
        metadata.update(
            {
                key: image[key]
                for key in ("width", "height", "capture_method", "viewpoint", "warnings")
            }
        )
        if image["scene_path"] != tree["scene_path"]:
            metadata["status"] = "partial"
            metadata["warnings"].append(
                "Active scene changed during snapshot; retry for a consistent view."
            )
        after = client.call("scene.tree")
        if after["scene_path"] != tree["scene_path"] or after["revision"] != tree["revision"]:
            metadata["status"] = "partial"
            metadata["warnings"].append(
                "Scene edits occurred during capture; metadata and image may differ."
            )
    except BridgeError as exc:
        metadata.update(status="partial", error=exc.as_dict())
        metadata["warnings"].append(exc.message)
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return {
        "output_dir": str(directory),
        "scene_path": str(directory / "scene.json"),
        "image_path": str(directory / "viewport.png")
        if (directory / "viewport.png").exists()
        else None,
        "metadata": metadata,
        "status": metadata["status"],
    }
