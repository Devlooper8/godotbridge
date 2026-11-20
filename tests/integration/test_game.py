import time

import pytest
from godotbridge.artifacts import png_dimensions
from godotbridge.demo import build_arena
from godotbridge.errors import BridgeError
from helpers import rejected, write
from test_debugger import wait_until

pytestmark = pytest.mark.engine

INHERITABLE = '[gd_scene format=3]\n\n[node name="Base" type="Node3D"]\n'


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
        assert result["state"] == "stopped", result
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


def test_screenshot_with_frozen_time(editor, request):
    if not request.config.getoption("--graphical"):
        pytest.skip("Runtime capture requires --graphical")
    scripts = editor.config.project / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "freeze.gd").write_text(
        "extends Node3D\nfunc _ready():\n\tEngine.time_scale = 0\n", encoding="utf-8"
    )
    (editor.config.project / "scenes/freeze.tscn").write_text(
        '[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://scripts/freeze.gd" id="1"]\n'
        '[node name="Freeze" type="Node3D"]\nscript = ExtResource("1")\n',
        encoding="utf-8",
    )
    editor.call("game.run", scene="res://scenes/freeze.tscn", max_seconds=60)
    try:
        time.sleep(1)
        result = editor.call("game.screenshot", output="frozen.png")
        assert result["capture_method"] == "runtime_viewport"
    finally:
        editor.call("game.stop")


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


def test_run_current_rejects_an_unsaved_scene(editor):
    """The engine would stop a running game, then open a modal save dialog; managed mode would run main."""
    write(editor, "scenes/run_current_base.tscn", INHERITABLE)
    # An inherited scene opens unsaved: its scene_path is empty.
    editor.call("scene.open", path="res://scenes/run_current_base.tscn", inherited=True)
    assert editor.call("scene.current")["scene_path"] == ""
    managed_before = editor.call("game.status").get("run_id")
    editor.call("game.run", mode="editor", scene="res://scenes/main.tscn")
    try:
        wait_until(lambda: editor.call("game.status", mode="editor")["running"], 10, "editor play")
        rejected(editor, "game.run", "SCENE_NOT_FOUND", mode="editor", current=True)
        rejected(editor, "game.run", "SCENE_NOT_FOUND", current=True, headless=True, max_seconds=5)
        # Rejected before play_current_scene(), which would have stopped this game.
        assert editor.call("game.status", mode="editor")["running"] is True
        assert editor.call("game.status").get("run_id") == managed_before
    finally:
        editor.call("game.stop", mode="editor")
        wait_until(
            lambda: not editor.call("game.status", mode="editor")["running"], 10, "editor stop"
        )
        # An unsaved inherited scene cannot be closed: save it, then return to the main scene.
        editor.call("scene.save_as", path="res://scenes/run_current_saved.tscn")
        editor.call("scene.open", path="res://scenes/main.tscn")
    # Once saved, --current works again.
    editor.call("scene.open", path="res://scenes/run_current_saved.tscn")
    editor.call("game.run", mode="editor", current=True)
    try:
        wait_until(lambda: editor.call("game.status", mode="editor")["running"], 10, "editor play")
    finally:
        editor.call("game.stop", mode="editor")
        wait_until(
            lambda: not editor.call("game.status", mode="editor")["running"], 10, "editor stop"
        )
        editor.call("scene.open", path="res://scenes/main.tscn")
