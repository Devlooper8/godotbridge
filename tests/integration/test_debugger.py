import json
import re
import time

import pytest
from godotbridge.errors import BridgeError
from helpers import write

pytestmark = pytest.mark.engine

LOGGER_SCRIPT = """extends Node3D

func _ready():
	print("bridge-info-line")
	push_warning("bridge-warning-line")
	push_error("bridge-error-line")
"""


@pytest.fixture
def graphical(request):
    if not request.config.getoption("--graphical"):
        pytest.skip("Editor play requires --graphical")


def make_scene(editor, name, script):
    write(editor, f"scripts/{name}.gd", script)
    write(
        editor,
        f"scenes/{name}.tscn",
        f'[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://scripts/{name}.gd" id="1"]\n'
        '[node name="Root" type="Node3D"]\nscript = ExtResource("1")\n',
    )
    return f"res://scenes/{name}.tscn"


def wait_until(predicate, timeout=20, message="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    pytest.fail(f"Timed out waiting for {message}")


def collect(editor, predicate, since=0, timeout=20):
    """Poll game.logs from a cursor until predicate(all entries so far) holds."""
    entries: list = []
    cursor = since

    def poll():
        nonlocal cursor
        result = editor.call("game.logs", mode="editor", since=cursor)
        entries.extend(result["entries"])
        cursor = result["next"]
        return result if predicate(entries) else None

    result = wait_until(poll, timeout, "editor game logs")
    return entries, result


def test_autoload_is_registered(editor):
    # The fixture enables the plugin through project.godot, like an install made before the autoload existed.
    text = (editor.config.project / "project.godot").read_text(encoding="utf-8")
    # The editor stores the path as a uid:// reference.
    assert len(re.findall(r'^GodotBridgeRuntime="\*(uid://|res://)', text, re.M)) == 1


def test_editor_logs_without_game(editor):
    result = editor.call("game.logs", mode="editor")
    assert result["running"] is False
    with pytest.raises(BridgeError) as caught:
        editor.call("game.logs", since=3)
    assert caught.value.code == "INVALID_ARGUMENT"


def test_editor_play_streams_logs_with_cursor(editor, graphical):
    scene = make_scene(editor, "logger", LOGGER_SCRIPT)
    start = editor.call("game.logs", mode="editor")["next"]
    editor.call("game.run", mode="editor", scene=scene)
    try:
        entries, result = collect(
            editor,
            lambda e: (
                {"bridge-info-line", "bridge-warning-line", "bridge-error-line"}
                <= {x.get("message") for x in e}
            ),
            since=start,
        )
        by_message = {x["message"]: x for x in entries if x["kind"] == "log"}
        assert by_message["bridge-info-line"]["level"] == "info"
        assert by_message["bridge-warning-line"]["level"] == "warning"
        error = by_message["bridge-error-line"]
        assert error["level"] == "error"
        assert error["file"].endswith("logger.gd") and error["line"] == 6
        assert any(x["kind"] == "run_started" for x in entries)
        assert result["running"] is True
        run = by_message["bridge-info-line"]["run"]
        seqs = [x["seq"] for x in entries]
        assert seqs == sorted(set(seqs))
    finally:
        editor.call("game.stop", mode="editor")
    # Cursor semantics: nothing is returned twice, and the stop boundary is delivered once.
    entries, result = collect(
        editor, lambda e: any(x["kind"] == "run_stopped" for x in e), since=seqs[-1]
    )
    assert all(x["seq"] > seqs[-1] for x in entries)
    assert result["running"] is False
    again = editor.call("game.logs", mode="editor", since=result["next"])
    assert again["entries"] == [] and again["next"] == result["next"]
    # A second run is distinguishable by its run number.
    editor.call("game.run", mode="editor", scene=scene)
    try:
        entries, _ = collect(
            editor,
            lambda e: any(x.get("message") == "bridge-info-line" for x in e),
            since=result["next"],
        )
        assert {x["run"] for x in entries} == {run + 1}
    finally:
        editor.call("game.stop", mode="editor")


def test_managed_run_with_autoload_is_unaffected(editor):
    """Managed runs have no attached debugger, so the registered autoload must stay inert."""
    scene = make_scene(
        editor,
        "managed_probe",
        'extends Node3D\n\nfunc _ready():\n\tprint("probe autoload=", has_node("/root/GodotBridgeRuntime"))\n'
        '\tprint("probe debugger=", EngineDebugger.is_active())\n\tget_tree().quit(0)\n',
    )
    editor.call("game.run", scene=scene, headless=True, max_seconds=30)
    status = wait_until(
        lambda: (s := editor.call("game.status"))["running"] is False and s, 20, "managed exit"
    )
    assert status["exit_code"] == 0
    # The supervisor releases its lock just after the final status; do not race the next managed test.
    lock = editor.config.private_path("game/run.lock")
    wait_until(lambda: not lock.exists(), 10, "supervisor lock release")
    logs = editor.call("game.logs")
    assert "probe autoload=true" in logs["log"]
    assert "probe debugger=false" in logs["log"]
    assert not logs["errors"], logs
    print(logs["log"])


# A second debugger plugin added while a game runs takes the same engine path as enabling the bridge
# plugin then (EditorDebuggerNode.add_debugger_plugin -> _setup_session), without tearing the connection down.
PROBE_SCRIPT = """@tool
extends EditorPlugin

const Debugger = preload("res://addons/godot_bridge/debugger_plugin.gd")
var probe

func _process(_delta):
	if probe or not FileAccess.file_exists("res://adopt.request"):
		return
	probe = Debugger.new()
	probe.breakpoints = {"res://scripts/spinner.gd": {6: true}}
	add_debugger_plugin(probe)
	FileAccess.open("res://adopt.result", FileAccess.WRITE).store_string(
		JSON.stringify({"run": probe.run, "sessions": probe.session_runs}))
"""
PROBE_CONFIG = '[plugin]\nname="AdoptProbe"\ndescription="test"\nauthor="test"\nversion="1"\nscript="plugin.gd"\n'
SPINNER_SCRIPT = "extends Node3D\n\nvar ticks := 0\n\nfunc _process(_delta):\n\tticks += 1\n"


def install_probe(config):
    folder = config.project / "addons/adopt_probe"
    folder.mkdir(parents=True)
    (folder / "plugin.cfg").write_text(PROBE_CONFIG, encoding="utf-8")
    (folder / "plugin.gd").write_text(PROBE_SCRIPT, encoding="utf-8")
    settings = config.project / "project.godot"
    text = settings.read_text(encoding="utf-8")
    bridge = '"res://addons/godot_bridge/plugin.cfg"'
    assert bridge in text
    settings.write_text(
        text.replace(bridge, bridge + ', "res://addons/adopt_probe/plugin.cfg"'), encoding="utf-8"
    )


def test_plugin_added_while_a_game_runs_adopts_its_session(extra_editor):
    """`started` never fires for a run that began before the plugin existed; _setup_session adopts it."""
    with extra_editor(install_probe, name="adopt") as editor:
        scene = make_scene(editor, "spinner", SPINNER_SCRIPT)
        editor.call("game.run", mode="editor", scene=scene)
        try:
            wait_until(lambda: editor.call("debug.status")["running"], 20, "editor game")
            assert editor.call("debug.status")["breaked"] is False
            (editor.config.project / "adopt.request").write_text("go", encoding="utf-8")
            result_file = editor.config.project / "adopt.result"

            def result():
                try:
                    return json.loads(result_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return None

            # The run is counted for the session that was already active.
            assert wait_until(result, 20, "probe attach") == {"run": 1, "sessions": {"0": 1}}
            # Its breakpoint registry reached the running game: the next frame stops on it.
            wait_until(lambda: editor.call("debug.status")["breaked"], 20, "registry breakpoint")
            frame = editor.call("debug.stack")["frames"][0]
            assert (frame["function"], frame["line"]) == ("_process", 6)
        finally:
            editor.call("game.stop", mode="editor")
