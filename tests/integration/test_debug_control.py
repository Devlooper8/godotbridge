import pytest
from helpers import rejected
from test_debugger import collect, graphical, make_scene, wait_until  # noqa: F401

pytestmark = pytest.mark.engine

# Line numbers matter: the tests set breakpoints on 10 and 11.
SCRIPT = """extends Node3D

var counter := 0

func helper(v: int) -> int:
	var doubled := v * 2
	return doubled + 1

func work(x: int) -> int:
	var local_a := x * 2
	var local_b := helper(local_a)
	counter += local_b
	return local_b

func _ready():
	print("start")
	var r = work(5)
	print("done ", r)
"""


def stopped(editor, expect=True, timeout=20):
    return wait_until(
        lambda: editor.call("debug.status")["breaked"] is expect, timeout, f"breaked={expect}"
    )


def top(editor):
    frame = editor.call("debug.stack")["frames"][0]
    return frame["function"], frame["line"]


def local(editor, name, scope="locals", frame=0):
    variables = editor.call("debug.variables", frame=frame, scope=scope)["variables"]
    return {v["name"]: v["value"] for v in variables}[name]


@pytest.fixture
def play(editor, graphical):  # noqa: F811
    scene = make_scene(editor, "debuggee", SCRIPT)
    editor.call("debug.clear_breakpoints")
    yield lambda: editor.call("game.run", mode="editor", scene=scene)
    editor.call("debug.clear_breakpoints")
    editor.call("game.stop", mode="editor")
    wait_until(lambda: not editor.call("debug.status")["running"], 10, "game to stop")


def test_breakpoint_stack_variables_and_stepping(editor, play):
    path = "res://scripts/debuggee.gd"
    # Set before any game runs: the bridge registry applies it to the next run.
    result = editor.call("debug.set_breakpoints", path=path, lines=[10])
    assert result["bridge"] == {path: [10]} and result["all"][path] == [10]
    rejected(editor, "debug.stack", "GAME_NOT_RUNNING")
    play()
    stopped(editor)

    frames = editor.call("debug.stack")["frames"]
    assert [(f["function"], f["line"], f["file"]) for f in frames] == [
        ("work", 10, path),
        ("_ready", 17, path),
    ]
    assert local(editor, "x") == 5
    assert local(editor, "counter", "members") == 0
    assert local(editor, "x", frame=0) == 5 and local(editor, "r", frame=1) is None
    rejected(editor, "debug.variables", "INVALID_ARGUMENT", frame=5)

    # Step over: next line of the same function.
    assert editor.call("debug.step", kind="over")["breaked"] is True
    assert top(editor) == ("work", 11)
    assert local(editor, "local_a") == 10
    # Step in: into helper.
    assert editor.call("debug.step", kind="in")["breaked"] is True
    assert top(editor)[0] == "helper"
    assert local(editor, "v") == 10
    # Step out: back in work, after the call.
    assert editor.call("debug.step", kind="out")["breaked"] is True
    assert top(editor)[0] == "work"
    assert top(editor)[1] >= 11

    editor.call("debug.clear_breakpoints")
    assert editor.call("debug.breakpoints")["all"] == {}
    assert editor.call("debug.continue")["running"] is True
    stopped(editor, expect=False)
    rejected(editor, "debug.stack", "NOT_BREAKED")
    rejected(editor, "debug.continue", "NOT_BREAKED")
    entries, _ = collect(editor, lambda e: any(x.get("message") == "done 21" for x in e))
    assert any(x.get("message") == "done 21" for x in entries)


def test_cleared_breakpoint_is_not_hit(editor, play):
    path = "res://scripts/debuggee.gd"
    editor.call("debug.set_breakpoints", path=path, lines=[10, 11])
    editor.call("debug.set_breakpoints", path=path, lines=[11])
    assert editor.call("debug.breakpoints")["bridge"] == {path: [11]}
    play()
    stopped(editor)
    assert top(editor) == ("work", 11)  # 10 was removed before the run
    editor.call("debug.clear_breakpoints", path=path)
    editor.call("debug.continue")
    stopped(editor, expect=False)

    # A cleared breakpoint is not hit by the next run either.
    editor.call("game.stop", mode="editor")
    wait_until(lambda: not editor.call("debug.status")["running"], 10, "game to stop")
    play()
    collect(editor, lambda e: sum(x.get("message") == "done 21" for x in e) >= 2)
    assert editor.call("debug.status")["breaked"] is False


def test_breakpoint_set_while_running_and_pause(editor, graphical):  # noqa: F811
    scene = make_scene(
        editor,
        "spinner",
        "extends Node3D\n\nvar ticks := 0\n\nfunc _process(_delta):\n\tticks += 1\n",
    )
    editor.call("game.run", mode="editor", scene=scene)
    try:
        wait_until(lambda: editor.call("debug.status")["running"], 10, "running")
        rejected(editor, "debug.continue", "NOT_BREAKED")
        # Pause stops at a frame boundary, outside any script, so there are no script frames yet.
        assert editor.call("debug.pause")["breaked"] is True
        assert editor.call("debug.pause") == {"breaked": True, "running": True, "changed": False}
        assert editor.call("debug.stack")["frames"] == []
        # Step in runs to the next script line (step over would not stop: there is no frame to step in).
        assert editor.call("debug.step", kind="in")["breaked"] is True
        assert top(editor)[0] == "_process"
        assert local(editor, "ticks", "members") >= 0
        editor.call("debug.continue")
        stopped(editor, expect=False)
        # A breakpoint added to the live game is hit on a later frame.
        editor.call("debug.set_breakpoints", path="res://scripts/spinner.gd", lines=[6])
        stopped(editor)
        assert top(editor) == ("_process", 6)
        editor.call("debug.clear_breakpoints")
        editor.call("debug.continue")
        stopped(editor, expect=False)
    finally:
        editor.call("debug.clear_breakpoints")
        editor.call("game.stop", mode="editor")
    wait_until(lambda: not editor.call("debug.status")["running"], 10, "game to stop")


def test_breakpoint_validation(editor):
    for bad in ("res://scenes/main.tscn", "res://scripts/missing.gd", "res://.godot/x.gd"):
        rejected(editor, "debug.set_breakpoints", "FILE_ACCESS_DENIED", path=bad, lines=[1])
    rejected(editor, "debug.set_breakpoints", "INVALID_ARGUMENT", path="res://a.gd", lines=[0])
    rejected(editor, "debug.step", "INVALID_ARGUMENT", kind="sideways")
