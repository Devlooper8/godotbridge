import json

import pytest
from godotbridge.artifacts import png_dimensions
from godotbridge.demo import build_arena
from godotbridge.errors import BridgeError

pytestmark = pytest.mark.engine


def test_snapshot(editor, request):
    build_arena(editor, "res://scenes/visual.tscn")
    result = editor.call("scene.snapshot", output_dir="test-snapshot", width=512, height=384)
    directory = editor.config.project / "test-snapshot"
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["scene_path"] == "res://scenes/visual.tscn"
    assert len(json.loads((directory / "scene.json").read_text())["nodes"]) == 28
    if request.config.getoption("--graphical"):
        assert editor.call("editor.camera_info")["fov"] > 0
        assert result["status"] == "complete", result
        assert png_dimensions(directory / "viewport.png") == (512, 384)
        assert (directory / "viewport.png").stat().st_size > 1000
        assert metadata["capture_method"] == "geometry_preview"
    else:
        with pytest.raises(BridgeError) as unavailable:
            editor.call("editor.camera_info")
        assert unavailable.value.code == "CAPTURE_UNAVAILABLE"
        assert result["status"] == "partial"
        assert not (directory / "viewport.png").exists()
        assert metadata["error"]["code"] == "CAPTURE_UNAVAILABLE"


@pytest.mark.parametrize(
    "method,viewpoint",
    [
        ("editor", "perspective"),
        ("preview", "top"),
        ("preview", "front"),
        ("preview", "side"),
        ("preview", "custom"),
    ],
)
def test_capture(editor, request, method, viewpoint):
    if not request.config.getoption("--graphical"):
        with pytest.raises(BridgeError) as caught:
            editor.call("viewport.capture", method=method, viewpoint=viewpoint)
        assert caught.value.code == "CAPTURE_UNAVAILABLE"
        return
    name = f"test-{method}-{viewpoint}.png"
    result = editor.call(
        "viewport.capture", method=method, viewpoint=viewpoint, output=name, width=320, height=240
    )
    assert png_dimensions(editor.config.project / name) == (320, 240)
    assert result["capture_method"] == (
        "editor_viewport" if method == "editor" else "geometry_preview"
    )
