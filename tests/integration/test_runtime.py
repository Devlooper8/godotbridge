import pytest
from godotbridge.errors import BridgeError
from helpers import rejected
from test_debugger import graphical, make_scene, wait_until  # noqa: F401

pytestmark = pytest.mark.engine

TICKER = """extends Node3D

@export var ticks := 0
@export var label := "start"

func _process(_delta):
	ticks += 1
"""


def vector(x, y, z):
    return {"type": "Vector3", "value": [x, y, z]}


def test_runtime_requires_a_running_game(editor):
    rejected(editor, "runtime.tree", "GAME_NOT_RUNNING")
    status = editor.call("debug.status")
    assert status["running"] is False and status["breaked"] is False
    assert 0 < status["dap_port"] < 65536


def test_runtime_inspection_is_live(editor, graphical):  # noqa: F811
    scene = make_scene(editor, "ticker", TICKER)
    scene_file = editor.config.project / "scenes/ticker.tscn"
    scene_file.write_text(
        scene_file.read_text(encoding="utf-8") + '[node name="Child" type="Node3D" parent="."]\n',
        encoding="utf-8",
    )
    editor.call("game.run", mode="editor", scene=scene)
    try:

        def tree_ready():
            try:
                return editor.call("runtime.tree")
            except BridgeError as exc:
                if exc.code in {"TIMEOUT", "SCENE_NOT_FOUND", "GAME_NOT_RUNNING"}:
                    return None
                raise

        tree = wait_until(tree_ready, 20, "runtime tree")
        assert [n["node_path"] for n in tree["nodes"]] == [".", "Child"]
        assert tree["nodes"][0]["script"] == "res://scripts/ticker.gd"
        assert tree["nodes"][1]["class"] == "Node3D" and tree["truncated"] is False
        assert editor.call("runtime.tree", max_nodes=1)["truncated"] is True
        assert editor.call("runtime.tree", path="Child")["nodes"][0]["node_path"] == "Child"

        status = editor.call("debug.status")
        assert status["running"] is True and status["breaked"] is False

        # The script advances every frame, so a later read must be larger: the data is live.
        first = editor.call("runtime.get_property", path=".", property="ticks")["value"]
        wait_until(
            lambda: (
                editor.call("runtime.get_property", path=".", property="ticks")["value"] > first
            ),
            10,
            "ticks to advance",
        )
        listed = {p["name"]: p for p in editor.call("runtime.properties")["properties"]}
        assert listed["ticks"]["script"] is True and "position" in listed

        editor.call("runtime.set_property", path=".", property="ticks", value=1_000_000)
        assert editor.call("runtime.get_property", path=".", property="ticks")["value"] >= 1_000_000
        editor.call("runtime.set_property", path=".", property="label", value="changed")
        assert editor.call("runtime.get_property", path=".", property="label")["value"] == "changed"
        moved = editor.call(
            "runtime.set_property", path="Child", property="position", value=vector(1, 2, 3)
        )
        assert moved["value"]["value"] == [1, 2, 3]
        assert editor.call("runtime.inspect", path="Child")["position"]["value"] == [1, 2, 3]

        rejected(editor, "runtime.inspect", "NODE_NOT_FOUND", path="Missing")
        rejected(editor, "runtime.inspect", "INVALID_NODE_PATH", path="../x")
        rejected(editor, "runtime.inspect", "INVALID_NODE_PATH", path="/root/GodotBridgeRuntime")
        rejected(editor, "runtime.get_property", "UNSUPPORTED_PROPERTY", property="name")
        rejected(editor, "runtime.set_property", "UNSUPPORTED_PROPERTY", property="name", value="x")
        rejected(editor, "runtime.set_property", "INVALID_ARGUMENT", property="ticks", value="x")

        # Runtime changes never touch the edited scene or the saved file.
        assert "1000000" not in scene_file.read_text(encoding="utf-8")
    finally:
        editor.call("game.stop", mode="editor")
    wait_until(lambda: not editor.call("debug.status")["running"], 10, "game to stop")
    rejected(editor, "runtime.tree", "GAME_NOT_RUNNING")


def test_runtime_inspection_while_stopped_at_a_breakpoint(editor, graphical):  # noqa: F811
    # The `breakpoint` statement stops the game in the debugger exactly like an editor breakpoint.
    scene = make_scene(
        editor, "stopped", "extends Node3D\n\nvar frozen := 7\n\nfunc _ready():\n\tbreakpoint\n"
    )
    editor.call("game.run", mode="editor", scene=scene)
    try:
        wait_until(lambda: editor.call("debug.status")["breaked"], 20, "breakpoint")
        # Debugger captures are still serviced while the game is stopped.
        assert editor.call("runtime.tree")["nodes"][0]["script"] == "res://scripts/stopped.gd"
        editor.call("runtime.set_property", path=".", property="position", value=vector(4, 5, 6))
        assert editor.call("runtime.inspect")["position"]["value"] == [4, 5, 6]
        assert editor.call("debug.status")["running"] is True
    finally:
        editor.call("game.stop", mode="editor")
    wait_until(lambda: not editor.call("debug.status")["running"], 10, "game to stop")


def test_runtime_tree_of_a_large_scene(editor, graphical):  # noqa: F811
    scene = make_scene(
        editor,
        "crowd",
        "extends Node3D\n\nfunc _ready():\n\tfor i in 1500:\n\t\tvar n := Node3D.new()\n"
        '\t\tn.name = "N%d" % i\n\t\tadd_child(n)\n',
    )
    editor.call("game.run", mode="editor", scene=scene)
    try:
        result = wait_until(lambda: _large_tree(editor), 20, "large runtime tree")
        assert len(result["nodes"]) == 1000 and result["truncated"] is True
        rejected(editor, "runtime.tree", "INVALID_ARGUMENT", max_nodes=5001)
        full = editor.call("runtime.tree", max_nodes=5000)
        assert len(full["nodes"]) == 1501 and full["truncated"] is False
    finally:
        editor.call("game.stop", mode="editor")
    wait_until(lambda: not editor.call("debug.status")["running"], 10, "game to stop")


def _large_tree(editor):
    try:
        result = editor.call("runtime.tree")
    except BridgeError as exc:
        if exc.code in {"TIMEOUT", "SCENE_NOT_FOUND", "GAME_NOT_RUNNING"}:
            return None
        raise
    return result if len(result["nodes"]) > 1 else None


def test_runtime_call_right_after_game_run_needs_no_polling(editor, graphical):  # noqa: F811
    scene = make_scene(editor, "immediate", TICKER)
    editor.call("game.run", mode="editor", scene=scene)
    try:
        # The session is not active yet and the autoload has not registered its capture: the plugin waits.
        tree = editor.call("runtime.tree")
        assert tree["nodes"][0]["script"] == "res://scripts/immediate.gd"
    finally:
        editor.call("game.stop", mode="editor")
    wait_until(lambda: not editor.call("debug.status")["running"], 10, "game to stop")
