import pytest
from helpers import rejected
from test_debug_control import stopped  # noqa: F401
from test_debugger import graphical, make_scene, wait_until  # noqa: F401

pytestmark = pytest.mark.engine

SCRIPT = """extends Node3D

var risky: int:
	get:
		print("GETTER RAN")
		return 3

func _ready():
	probe()

func probe():
	var nested := [{"name": "a", "items": [10, 20, {"deep": [1, 2, 3]}]}, 5]
	var odd := {1: "one", Vector2(1, 2): "vec", "s": [true]}
	var packed := PackedInt32Array([7, 8, 9])
	var cyc := [1]
	cyc.append(cyc)
	var me := self
	var probe_node := Node3D.new()
	probe_node.name = "Probe"
	add_child(probe_node)
	var res := BoxMesh.new()
	var dead := Node.new()
	dead.free()
	var many := range(250)
	var typed: Array[int] = [4, 5]
	var grid := []
	for i in 24:
		grid.append(range(24))
	print("stop")
	nested.clear()
	print("after")
"""
STOP_LINE = SCRIPT.split("\n").index('\tprint("stop")') + 1


def variables(editor, **params):
    return editor.call("debug.variables", **params)


def named(entries):
    return {entry["name"]: entry for entry in entries}


@pytest.fixture
def stopped_game(editor, graphical):  # noqa: F811
    scene = make_scene(editor, "browse", SCRIPT)
    editor.call("debug.clear_breakpoints")
    editor.call("debug.set_breakpoints", path="res://scripts/browse.gd", lines=[STOP_LINE])
    editor.call("game.run", mode="editor", scene=scene)
    stopped(editor)
    assert editor.call("debug.stack")["frames"][0]["function"] == "probe"
    yield editor
    editor.call("debug.clear_breakpoints")
    editor.call("game.stop", mode="editor")
    wait_until(lambda: not editor.call("debug.status")["running"], 10, "game to stop")


def test_summaries_paths_paging_and_depth(stopped_game):
    editor = stopped_game
    top = named(variables(editor)["variables"])
    assert top["nested"]["type"] == "Array"
    assert top["nested"]["count"] == 2 and top["nested"]["expandable"] is True
    assert "value" not in top["nested"] and "children" not in top["nested"]
    assert top["packed"]["type"] == "PackedInt32Array" and top["packed"]["count"] == 3
    assert top["typed"]["element_type"] == "int"
    assert top["many"]["count"] == 250
    assert top["me"]["class"] == "Node3D" and top["me"]["instance_id"] > 0
    assert top["probe_node"]["node_name"] == "Probe"
    assert top["probe_node"]["node_path"].endswith("Root/Probe")
    assert top["res"]["class"] == "BoxMesh" and top["res"]["value"]["type"] == "BoxMesh"
    assert top["dead"]["freed"] is True and top["dead"]["expandable"] is False
    assert top["cyc"]["count"] == 2

    # Array -> dictionary -> array -> dictionary -> array, one segment at a time.
    first = variables(editor, path=["nested", {"index": 0}])
    assert first["target"]["type"] == "Dictionary" and first["total"] == 2
    keys = [(c["index"], c["key"]["value"], c["type"]) for c in first["children"]]
    assert keys == [(0, "name", "String"), (1, "items", "Array")]
    assert first["children"][0]["value"] == "a"
    deep = variables(
        editor, path=["nested", {"index": 0}, {"index": 1}, {"index": 2}, {"index": 0}]
    )
    assert deep["target"]["count"] == 3
    assert [c["value"] for c in deep["children"]] == [1, 2, 3]

    # Dictionary with non-string keys is addressed by insertion position.
    odd = variables(editor, path=["odd"])
    assert [c["key"] for c in odd["children"]][:2] == [
        {"type": "int", "expandable": False, "value": 1},
        {"type": "Vector2", "expandable": False, "value": {"type": "Vector2", "value": [1.0, 2.0]}},
    ]
    assert variables(editor, path=["odd", {"index": 1}])["target"]["value"] == "vec"
    assert variables(editor, path=["odd", {"index": 2}])["children"][0]["value"] is True

    # Packed arrays and paging.
    assert [c["value"] for c in variables(editor, path=["packed"])["children"]] == [7, 8, 9]
    page = variables(editor, path=["many"], offset=240, limit=100)
    assert (page["total"], len(page["children"]), page["truncated"]) == (250, 10, False)
    assert page["children"][0] == {"type": "int", "expandable": False, "value": 240, "index": 240}
    page = variables(editor, path=["many"], offset=0, limit=7)
    assert len(page["children"]) == 7 and page["truncated"] is True
    assert len(variables(editor, limit=3)["variables"]) == 3

    # Depth inlines children; the entry budget truncates explicitly.
    inline = named(variables(editor, depth=2)["variables"])
    first_child = inline["nested"]["children"][0]
    assert [c["type"] for c in first_child["children"]] == ["String", "Array"]
    assert first_child["children"][1]["count"] == 3 and "children" not in first_child["children"][1]
    nested = variables(editor, path=["nested"], depth=2)["children"][0]
    inner = nested["children"][1]["children"]  # items: 10, 20, {"deep": [...]}
    assert [c["type"] for c in inner] == ["int", "int", "Dictionary"]
    assert nested["children"][1]["child_total"] == 3
    wide = variables(editor, path=["many"], depth=1, limit=200)
    assert wide["budget_exhausted"] is False
    everything = variables(editor, depth=2, limit=200)
    assert len(everything["variables"]) > 0

    # A reply is bounded by an entry budget, and says so when it cut something off.
    grid = variables(editor, path=["grid"], depth=1, limit=200)
    assert grid["budget_exhausted"] is True
    assert len(grid["children"][-1]["children"]) < 20  # the last rows lost their inlined children
    assert all(
        len(row["children"]) == 20 and row["children_truncated"] for row in grid["children"][:3]
    )
    assert variables(editor, path=["grid"], depth=0)["budget_exhausted"] is False

    # Self-referencing containers are marked, never inlined forever, and still drillable.
    cyc = variables(editor, path=["cyc"], depth=2)
    assert cyc["children"][1]["cycle"] is True and "children" not in cyc["children"][1]
    again = variables(editor, path=["cyc", {"index": 1}, {"index": 1}, {"index": 0}])
    assert again["target"]["value"] == 1
    inline_cyc = named(variables(editor, depth=2)["variables"])["cyc"]
    assert inline_cyc["children"][1]["cycle"] is True

    # Objects: properties, nested objects, script variables, freed objects.
    me = variables(editor, path=["me"])
    props = named(me["children"])
    assert props["visible"]["value"] is True
    assert props["position"]["value"]["type"] == "Vector3"
    assert props["script"]["class"] == "GDScript"
    assert variables(editor, path=["me", {"property": "scale"}])["target"]["type"] == "Vector3"
    mesh = variables(editor, path=["res", {"property": "size"}])
    assert mesh["target"]["value"]["value"] == [1.0, 1.0, 1.0]
    assert variables(editor, path=["dead"])["children"] == []
    rejected(editor, "debug.variables", "VARIABLE_NOT_FOUND", path=["dead", {"property": "name"}])


def test_getters_are_never_executed_and_errors(stopped_game):
    editor = stopped_game
    # `risky` has a getter containing `breakpoint`; reading it would re-enter the debugger.
    props = named(variables(editor, path=["me"], limit=200)["children"])
    assert props["risky"]["unread"] is True and props["risky"]["expandable"] is False
    rejected(editor, "debug.variables", "UNSUPPORTED_OPERATION", path=["me", {"property": "risky"}])
    assert editor.call("debug.status")["breaked"] is True
    assert editor.call("debug.stack")["frames"][0]["function"] == "probe"

    rejected(editor, "debug.variables", "VARIABLE_NOT_FOUND", path=["nope"])
    rejected(editor, "debug.variables", "VARIABLE_NOT_FOUND", path=["nested", {"index": 9}])
    rejected(editor, "debug.variables", "VARIABLE_NOT_FOUND", path=["nested", {"property": "x"}])
    rejected(
        editor, "debug.variables", "VARIABLE_NOT_FOUND", path=["many", {"index": 0}, {"index": 0}]
    )
    rejected(editor, "debug.variables", "VARIABLE_NOT_FOUND", path=["me", {"property": "nope"}])
    rejected(editor, "debug.variables", "INVALID_ARGUMENT", path=[{"index": 0}])
    rejected(editor, "debug.variables", "INVALID_ARGUMENT", limit=0)


def test_stale_path_after_the_game_moves_on(stopped_game):
    editor = stopped_game
    path = ["nested", {"index": 0}, {"index": 1}]
    assert variables(editor, path=path)["target"]["count"] == 3
    # `nested.clear()` runs: the same path no longer resolves.
    editor.call("debug.step", kind="over")  # print("stop")
    editor.call("debug.step", kind="over")  # nested.clear()
    rejected(editor, "debug.variables", "VARIABLE_NOT_FOUND", path=path)
    assert variables(editor, path=["nested"])["target"]["count"] == 0
    editor.call("debug.clear_breakpoints")
    editor.call("debug.continue")
    stopped(editor, expect=False)
    rejected(editor, "debug.variables", "NOT_BREAKED", path=path)
