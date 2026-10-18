import time

import pytest
from godotbridge.artifacts import png_dimensions
from godotbridge.demo import build_arena
from godotbridge.errors import BridgeError

pytestmark = pytest.mark.engine


def wait_for(editor, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = editor.call("game.status")
        if predicate(state):
            return state
        time.sleep(0.1)
    pytest.fail(f"Managed game did not reach expected state: {state}")


def test_managed_game_logs_stop_and_capture(editor, request):
    build_arena(editor, "res://scenes/runtime.tscn")
    graphical = request.config.getoption("--graphical")
    state = editor.call(
        "game.run", scene="res://scenes/runtime.tscn", headless=not graphical, max_seconds=60
    )
    assert state["running"]
    try:
        # Allow initialization, then verify it did not crash after spawn.
        time.sleep(1)
        assert editor.call("game.status")["running"], editor.call("game.logs")
        logs = editor.call("game.logs")
        assert "Godot Engine" in logs["log"]
        assert not logs["errors"], logs
        if graphical:
            result = editor.call("game.screenshot", output="runtime.png")
            assert result["capture_method"] == "runtime_viewport"
            assert png_dimensions(editor.config.project / "runtime.png") == (960, 640)
        else:
            with pytest.raises(BridgeError) as caught:
                editor.call("game.screenshot")
            assert caught.value.code == "CAPTURE_UNAVAILABLE"
    finally:
        result = editor.call("game.stop")
        assert result["state"] == "stopped"
        assert result["stop_reason"] == "requested"


def test_managed_timeout(editor):
    editor.call("game.run", scene="res://scenes/main.tscn", headless=True, max_seconds=0.5)
    result = wait_for(editor, lambda s: not s["running"])
    assert result["stop_reason"] == "timeout"


def test_nonzero_exit_code(editor):
    scripts = editor.config.project / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "exit.gd").write_text(
        'extends Node3D\nfunc _ready():\n\tprint("runtime diagnostic")\n\tget_tree().quit(7)\n',
        encoding="utf-8",
    )
    (editor.config.project / "scenes/exit.tscn").write_text(
        '[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://scripts/exit.gd" id="1"]\n'
        '[node name="Exit" type="Node3D"]\nscript = ExtResource("1")\n',
        encoding="utf-8",
    )
    editor.call("game.run", scene="res://scenes/exit.tscn", headless=True, max_seconds=10)
    result = wait_for(editor, lambda s: not s["running"])
    assert result["exit_code"] == 7
    assert "runtime diagnostic" in editor.call("game.logs")["log"]


def test_editor_play_controls(editor, request):
    if not request.config.getoption("--graphical"):
        pytest.skip("Editor-managed graphical play requires --graphical")
    editor.call("game.run", mode="editor", scene="res://scenes/main.tscn")
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if editor.call("game.status", mode="editor")["running"]:
                break
            time.sleep(0.1)
        else:
            pytest.fail("Editor did not report playing")
    finally:
        editor.call("game.stop", mode="editor")
