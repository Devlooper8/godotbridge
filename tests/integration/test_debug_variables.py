import json
from dataclasses import replace

import pytest
from conftest import prepare_project
from godotbridge.headless import run_engine
from helpers import rejected
from test_debug_control import stopped  # noqa: F401
from test_debugger import graphical, make_scene, wait_until  # noqa: F401

pytestmark = pytest.mark.engine

SCRIPT = """extends Node3D

var plain := 42

var risky: int:
	get:
		print("GETTER RAN")
		return 3

class Inner:
	var plain := 5
	var risky: int:
		get:
			print("INNER GETTER RAN")
			return 3

class Derived extends Inner:
	var extra := 6

# A hook that re-enters the debugger: running it during a browse would wedge the stopped game.
class Hooky extends Node:
	var plain := 1
	func _get_property_list() -> Array[Dictionary]:
		breakpoint
		return []

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
	# A script whose source is gone cannot be checked for getters, so its variables are never read.
	var script := GDScript.new()
	script.source_code = "extends Node
var hidden := 5
"
	script.reload()
	var dyn := Node.new()
	dyn.set_script(script)
	add_child(dyn)
	script.source_code = ""
	var inner := Inner.new()
	var derived := Derived.new()
	var hooky := Hooky.new()
	add_child(hooky)
	# An inner class of a script nobody can find (not in the tree, the stack or any preload) stays unread.
	var lost := GDScript.new()
	lost.source_code = "extends RefCounted
class Hidden:
	var h := 1
"
	lost.reload()
	var hidden = lost.get_script_constant_map()["Hidden"].new()
	lost.source_code = ""
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
    assert props["plain"]["value"] == 42 and "unread" not in props["plain"]

    # Fail closed: no source to check, so nothing the script declares is read.
    dyn = named(variables(editor, path=["dyn"], limit=200)["children"])
    assert dyn["hidden"]["unread"] is True and "value" not in dyn["hidden"]
    assert dyn["process_mode"]["value"] == 0  # engine properties are still shown
    rejected(
        editor, "debug.variables", "UNSUPPORTED_OPERATION", path=["dyn", {"property": "hidden"}]
    )
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


def test_inner_class_objects_are_read_unless_their_owner_is_unknown(stopped_game):
    editor = stopped_game
    # The owner script (browse.gd) is in the scene tree, so only its real getter marks `risky` unread.
    inner = named(variables(editor, path=["inner"], limit=200)["children"])
    assert inner["plain"]["value"] == 5 and "unread" not in inner["plain"]
    assert inner["risky"]["unread"] is True and "custom getter" in inner["risky"]["reason"]
    derived = named(variables(editor, path=["derived"], limit=200)["children"])
    assert derived["plain"]["value"] == 5 and derived["extra"]["value"] == 6
    assert derived["risky"]["unread"] is True
    assert variables(editor, path=["inner", {"property": "plain"}])["target"]["value"] == 5
    rejected(
        editor, "debug.variables", "UNSUPPORTED_OPERATION", path=["inner", {"property": "risky"}]
    )
    # No owner anywhere: fail closed, with a reason that is not the getter one.
    hidden = named(variables(editor, path=["hidden"], limit=200)["children"])
    assert hidden["h"]["unread"] is True and "source" in hidden["h"]["reason"]
    assert hidden["h"]["reason"] != inner["risky"]["reason"]
    rejected(editor, "debug.variables", "UNSUPPORTED_OPERATION", path=["hidden", {"property": "h"}])
    assert editor.call("debug.status")["breaked"] is True
    logs = editor.call("game.logs", mode="editor", since=0)["entries"]
    assert any(x["kind"] == "run_started" for x in logs)  # the log is flowing
    assert not any("INNER GETTER RAN" in x.get("message", "") for x in logs)


def test_hook_methods_are_never_executed(stopped_game):
    editor = stopped_game
    # `Hooky._get_property_list` contains `breakpoint`: running it inside the break wedges the game
    # (this call then times out and the stack fills with nested `_get_property_list` frames).
    hooky = variables(editor, path=["hooky"], limit=200)
    assert editor.call("debug.status")["breaked"] is True
    assert editor.call("debug.stack")["frames"][0]["function"] == "probe"
    assert named(variables(editor)["variables"])["hooky"]["hooks"] == ["_get_property_list"]
    assert hooky["target"]["hooks"] == ["_get_property_list"]
    props = named(hooky["children"])
    assert props["plain"]["value"] == 1 and props["process_mode"]["value"] == 0
    assert props["script"]["class"] == "GDScript"
    assert variables(editor, path=["hooky", {"property": "process_mode"}])["target"]["value"] == 0


# Headless: the browser runs against objects built by a SceneTree script, no game and no debugger.
# Hooks and getters count themselves in Engine metadata, so "never executed" is a number.
HOOKED = """extends Node
var plain := 42
func _count():
	Engine.set_meta("hooks", int(Engine.get_meta("hooks", 0)) + 1)
func _get_property_list() -> Array[Dictionary]:
	_count()
	return [{"name": "dyn", "type": TYPE_INT, "usage": PROPERTY_USAGE_DEFAULT}]
func _validate_property(_property: Dictionary) -> void:
	_count()
func _get(_name):
	_count()
	return null
"""
HOOKED_DERIVED = """extends "res://scripts/hooked.gd"
var extra := 7
"""
HOOKED_MESH = """extends BoxMesh
func _get(_name):
	Engine.set_meta("hooks", int(Engine.get_meta("hooks", 0)) + 1)
	return null
"""
HOOK_DRIVER = """extends SceneTree
const Browser = preload("res://addons/godot_bridge/runtime/variable_browser.gd")

class InnerHook:
	var plain := 1
	func _validate_property(_property: Dictionary) -> void:
		Engine.set_meta("hooks", int(Engine.get_meta("hooks", 0)) + 1)

func _initialize():
	var hooked: Node = load("res://scripts/hooked.gd").new()
	hooked.name = "Hooked"
	var derived: Node = load("res://scripts/hooked_derived.gd").new()
	var mesh: Resource = load("res://scripts/hooked_mesh.gd").new()
	var roots := [{"name": "o", "value": hooked}, {"name": "d", "value": derived},
		{"name": "m", "value": mesh}, {"name": "list", "value": [hooked]},
		{"name": "keyed", "value": {hooked: 1}}, {"name": "i", "value": InnerHook.new()}]
	var ask := func(params): return Browser.browse(roots, params)
	var replies := {
		"overview": ask.call({"depth": 2, "limit": 200}),
		"o": ask.call({"path": ["o"], "limit": 200}),
		"d": ask.call({"path": ["d"], "limit": 200}),
		"m": ask.call({"path": ["m"], "limit": 200}),
		"plain": ask.call({"path": ["o", {"property": "plain"}]}),
		"mode": ask.call({"path": ["o", {"property": "process_mode"}]}),
		"script": ask.call({"path": ["o", {"property": "script"}]}),
		"extra": ask.call({"path": ["d", {"property": "extra"}]}),
		"inner": ask.call({"path": ["i"], "limit": 200}),
		"size": ask.call({"path": ["m", {"property": "size"}]}),
		"listed": ask.call({"path": ["list", {"index": 0}], "depth": 1}),
		"keys": ask.call({"path": ["keyed"], "depth": 2}),
		"dyn": ask.call({"path": ["o", {"property": "dyn"}]}),
	}
	print("GODOTBRIDGE_RESULT=", JSON.stringify({"hooks": Engine.get_meta("hooks", 0), "replies": replies}))
	hooked.free()
	derived.free()
	quit()
"""
OUTER = """extends Node
const Other = preload("res://scripts/other.gd")
class Inner:
	var plain := 5
	var risky: int:
		get:
			Engine.set_meta("getters", int(Engine.get_meta("getters", 0)) + 1)
			return 3
	class Deep:
		var deep_plain := 8
		var deep_risky: int:
			get:
				Engine.set_meta("getters", int(Engine.get_meta("getters", 0)) + 1)
				return 4
class Derived extends Inner:
	var extra := 6
func make_inner(): return Inner.new()
func make_derived(): return Derived.new()
func make_deep(): return Inner.Deep.new()
func make_other(): return Other.make()
"""
# Same inner class name as OUTER, different file and different getters.
OTHER = """extends RefCounted
class Inner:
	var plain := 1
	var risky := 9
	var oddity: int:
		get:
			Engine.set_meta("getters", int(Engine.get_meta("getters", 0)) + 1)
			return 2
static func make(): return Inner.new()
"""
# Loaded but unreachable: not in the tree, on the stack, a global class or preloaded by a candidate.
LOST = """extends RefCounted
class Thing:
	var plain := 1
	var risky: int:
		get:
			Engine.set_meta("getters", int(Engine.get_meta("getters", 0)) + 1)
			return 1
static func make(): return Thing.new()
"""
# Holds LOST's inner class as a constant, but does not declare it: no getters of its own to scan.
ALIAS = """extends Node
const Alias = preload("res://scripts/lost.gd").Thing
func make(): return Alias.new()
"""
INNER_DRIVER = """extends SceneTree
const Browser = preload("res://addons/godot_bridge/runtime/variable_browser.gd")

# Found through the stack: this script is running and nothing else refers to it.
class Local:
	var plain := 3
	var risky: int:
		get:
			Engine.set_meta("getters", int(Engine.get_meta("getters", 0)) + 1)
			return 3

func _initialize(): # not _init: the main loop is only registered after construction
	var holder = Node.new()
	holder.set_script(load("res://scripts/outer.gd"))
	root.add_child(holder)
	var aliased = Node.new()
	aliased.set_script(load("res://scripts/alias.gd"))
	root.add_child(aliased)
	var made := {"inner": holder.make_inner(), "derived": holder.make_derived(), "deep": holder.make_deep(),
		"other": holder.make_other(), "local": Local.new(), "alias": aliased.make(),
		"lost": load("res://scripts/lost.gd").make()}
	var runtime := GDScript.new()
	runtime.source_code = "extends RefCounted\\nclass Hidden:\\n\\tvar h := 1\\n"
	runtime.reload()
	made["hidden"] = runtime.get_script_constant_map()["Hidden"].new()
	runtime.source_code = ""
	var roots := []
	for key in made:
		roots.append({"name": key, "value": made[key]})
	var replies := {}
	for key in made:
		replies[key] = Browser.browse(roots, {"path": [key], "limit": 200})
	replies["read_plain"] = Browser.browse(roots, {"path": ["inner", {"property": "plain"}]})
	replies["read_risky"] = Browser.browse(roots, {"path": ["inner", {"property": "risky"}]})
	replies["read_h"] = Browser.browse(roots, {"path": ["hidden", {"property": "h"}]})
	print("GODOTBRIDGE_RESULT=", JSON.stringify({"getters": Engine.get_meta("getters", 0), "replies": replies}))
	holder.free()
	aliased.free()
	quit()
"""


@pytest.fixture
def scripted(request, tmp_path):
    if not request.config.getoption("--engine"):
        pytest.skip("Pass --engine to run actual Godot integration tests")
    return replace(prepare_project(tmp_path), timeout=60)


def run_probe(config, driver, **scripts):
    """Run a SceneTree driver headless; returns the JSON it prints after GODOTBRIDGE_RESULT=."""
    folder = config.project / "scripts"
    folder.mkdir(exist_ok=True)
    for name, text in {**scripts, "probe.gd": driver}.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    result = run_engine(config, ["--script", "res://scripts/probe.gd"])
    assert result["exit_code"] == 0 and not result["errors"], result["log"]
    lines = [x for x in result["log"].splitlines() if x.startswith("GODOTBRIDGE_RESULT=")]
    return json.loads(lines[-1].split("=", 1)[1])


def test_hooked_objects_run_no_script_code(scripted):
    out = run_probe(
        scripted,
        HOOK_DRIVER,
        **{"hooked.gd": HOOKED, "hooked_derived.gd": HOOKED_DERIVED, "hooked_mesh.gd": HOOKED_MESH},
    )
    assert out["hooks"] == 0
    replies = out["replies"]
    missing = replies.pop("dyn")  # a property only `_get_property_list` would add is not listed
    assert missing["ok"] is False and missing["error"]["code"] == "VARIABLE_NOT_FOUND"
    assert all(reply["ok"] for reply in replies.values())
    everything = {"_get", "_get_property_list", "_validate_property"}
    overview = named(replies["overview"]["result"]["variables"])
    assert set(overview["o"]["hooks"]) == everything and overview["o"]["node_name"] == "Hooked"
    assert set(overview["d"]["hooks"]) == everything  # defined by the base script only
    assert overview["m"]["hooks"] == ["_get"] and "value" not in overview["m"]
    assert overview["m"]["resource_path"] == ""
    assert overview["list"]["children"][0]["hooks"] and overview["list"]["children"][0]["children"]
    assert replies["keys"]["result"]["children"][0]["key"]["hooks"]
    assert replies["listed"]["result"]["target"]["hooks"]

    listed = replies["o"]["result"]
    assert set(listed["target"]["hooks"]) == everything
    props = named(listed["children"])
    assert props["plain"]["value"] == 42 and "unread" not in props["plain"]
    assert props["process_mode"]["value"] == 0 and props["script"]["class"] == "GDScript"
    assert "dyn" not in props
    assert named(replies["d"]["result"]["children"])["extra"]["value"] == 7
    # An inner class has no source of its own, yet its hook is found and its variable still read.
    assert overview["i"]["hooks"] == ["_validate_property"]
    assert named(replies["inner"]["result"]["children"])["plain"]["value"] == 1
    assert "size" in named(replies["m"]["result"]["children"])
    assert replies["plain"]["result"]["target"]["value"] == 42
    assert replies["mode"]["result"]["target"]["value"] == 0
    assert replies["script"]["result"]["target"]["class"] == "GDScript"
    assert replies["extra"]["result"]["target"]["value"] == 7
    assert replies["size"]["result"]["target"]["value"]["value"] == [1.0, 1.0, 1.0]


def test_inner_class_owner_is_found_by_identity_or_the_object_stays_unread(scripted):
    out = run_probe(
        scripted,
        INNER_DRIVER,
        **{"outer.gd": OUTER, "other.gd": OTHER, "lost.gd": LOST, "alias.gd": ALIAS},
    )
    assert out["getters"] == 0
    replies = out["replies"]
    children = {
        key: named(reply["result"]["children"])
        for key, reply in replies.items()
        if "children" in reply.get("result", {})
    }
    for name in ("inner", "derived", "deep", "other", "local", "alias", "lost", "hidden"):
        assert replies[name]["ok"], name

    def unread(key, prop):
        return children[key][prop].get("unread", False)

    # Found: the owner's whole file is scanned, so only variables with a getter in it are unread.
    assert children["inner"]["plain"]["value"] == 5 and not unread("inner", "plain")
    assert unread("inner", "risky") and "custom getter" in children["inner"]["risky"]["reason"]
    assert children["derived"]["extra"]["value"] == 6 and unread("derived", "risky")
    assert children["deep"]["deep_plain"]["value"] == 8 and unread("deep", "deep_risky")
    assert children["local"]["plain"]["value"] == 3 and unread("local", "risky")
    # Same class name in another file: that file's own source decides (OUTER's `risky` getter is not its).
    assert children["other"]["risky"]["value"] == 9 and unread("other", "oddity")
    assert children["other"]["plain"]["value"] == 1
    # No owner found, or only a script that aliases the class: nothing the class declares is read.
    for key, prop in (("hidden", "h"), ("lost", "plain"), ("lost", "risky"), ("alias", "plain")):
        reason = children[key][prop]["reason"]
        assert unread(key, prop) and "source" in reason and "custom getter" not in reason, key
    assert replies["read_plain"]["result"]["target"]["value"] == 5
    assert replies["read_risky"]["error"]["code"] == "UNSUPPORTED_OPERATION"
    assert replies["read_h"]["error"]["code"] == "UNSUPPORTED_OPERATION"
    assert "source" in replies["read_h"]["error"]["message"]
