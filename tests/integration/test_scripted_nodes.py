import pytest
from helpers import read, rejected, write

pytestmark = pytest.mark.engine

PLAIN = """extends Node3D
@export var health: int = 3
@export var speed: float = 1.5
@export var label: String = "none"
@export var tint: Color = Color.WHITE
@export var texture: Texture2D
@export var anything: Variant = null
@export_range(0, 10) var level: int = 1
@export_enum("Low", "High:5") var mode: int = 0
@export_enum("x", "y") var tag: String = "x"
var hidden := 1
"""
TOOL = """@tool
extends Node3D
@export var power: int = 1
"""
SCENE = """[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://scripts/plain.gd" id="1"]
[ext_resource type="Script" path="res://scripts/tooled.gd" id="2"]

[node name="Scripted" type="Node3D"]

[node name="Plain" type="Node3D" parent="." groups=["enemies"]]
script = ExtResource("1")
health = 7

[node name="Tool" type="Node3D" parent="."]
script = ExtResource("2")
"""


@pytest.fixture
def scripted(editor, request):
    write(editor, "scripts/plain.gd", PLAIN)
    write(editor, "scripts/tooled.gd", TOOL)
    # One scene per test: the session-scoped editor keeps earlier scenes open with their edits.
    name = request.node.name
    write(editor, f"scenes/{name}.tscn", SCENE)
    editor.call("scene.open", path=f"res://scenes/{name}.tscn")
    return editor


def value(editor, path, property):
    return editor.call("node.get_property", path=path, property=property)["value"]


def test_plain_scripted_node_is_editable_with_undo(scripted):
    properties = {
        p["name"]: p for p in scripted.call("node.properties", path="Plain")["properties"]
    }
    assert properties["health"]["script"] is True
    assert properties["health"]["value"] == 7
    assert properties["health"]["type"] == "int"
    assert properties["position"]["script"] is False
    assert "hidden" not in properties
    info = scripted.call("node.inspect", path="Plain")
    assert info["script"] == "res://scripts/plain.gd"
    assert info["tool_script"] is False
    assert info["groups"] == ["enemies"]

    scripted.call("node.set_property", path="Plain", property="health", value=9)
    assert value(scripted, "Plain", "health") == 9
    scripted.call("editor.undo")
    assert value(scripted, "Plain", "health") == 7
    scripted.call("editor.redo")
    assert value(scripted, "Plain", "health") == 9
    scripted.call("node.set_property", path="Plain", property="speed", value=2)
    assert value(scripted, "Plain", "speed") == 2.0
    scripted.call("node.set_property", path="Plain", property="label", value="boss")
    scripted.call(
        "node.set_property",
        path="Plain",
        property="tint",
        value={"type": "Color", "value": [1, 0, 0, 1]},
    )
    scripted.call("node.set_property", path="Plain", property="anything", value=True)
    assert value(scripted, "Plain", "label") == "boss"
    scripted.call("node.set_transform", path="Plain", position=[1, 2, 3])
    scripted.call("node.rename", path="Plain", name="Renamed")
    scripted.call("node.create", parent="Renamed", name="Child")
    scripted.call("node.delete", path="Renamed/Child")
    scripted.call("node.reparent", path="Renamed", parent="Tool", allow_tool_script=True)
    scripted.call("editor.undo")


def test_script_variable_type_validation(scripted):
    for property, bad in [
        ("health", "ten"),
        ("health", 1.5),
        ("health", {"type": "Vector3", "value": [1, 2, 3]}),
        ("label", 5),
        ("tint", {"type": "Vector3", "value": [1, 2, 3]}),
        ("texture", {"type": "StandardMaterial3D", "path": "", "properties": {}}),
        ("anything", {"type": "Node3D"}),
    ]:
        rejected(
            scripted,
            "node.set_property",
            "INVALID_ARGUMENT",
            path="Plain",
            property=property,
            value=bad,
        )
    scripted.call("node.set_property", path="Plain", property="texture", value=None)
    rejected(
        scripted,
        "node.set_property",
        "UNSUPPORTED_PROPERTY",
        path="Plain",
        property="hidden",
        value=1,
    )
    rejected(
        scripted,
        "node.set_property",
        "UNSUPPORTED_PROPERTY",
        path="Plain",
        property="script",
        value=None,
    )
    assert value(scripted, "Plain", "health") == 7


def test_tool_script_requires_opt_in(scripted):
    assert scripted.call("node.inspect", path="Tool")["tool_script"] is True
    for method, params in [
        ("node.set_property", {"path": "Tool", "property": "visible", "value": False}),
        ("node.set_property", {"path": "Tool", "property": "power", "value": 2}),
        ("node.set_transform", {"path": "Tool", "position": [1, 0, 0]}),
        ("node.rename", {"path": "Tool", "name": "Other"}),
        ("node.delete", {"path": "Tool"}),
        ("node.duplicate", {"path": "Tool"}),
        ("node.reparent", {"path": "Tool", "parent": "Plain"}),
        ("node.create", {"parent": "Tool", "name": "Child"}),
    ]:
        rejected(scripted, method, "READ_ONLY_RESOURCE", **params)
    scripted.call(
        "node.set_property", path="Tool", property="power", value=2, allow_tool_script=True
    )
    assert value(scripted, "Tool", "power") == 2
    scripted.call("node.set_transform", path="Tool", position=[1, 0, 0], allow_tool_script=True)
    scripted.call("node.create", parent="Tool", name="Child", allow_tool_script=True)
    scripted.call("node.delete", path="Tool", allow_tool_script=True)
    scripted.call("editor.undo")
    assert value(scripted, "Tool", "power") == 2
    # A tool script anywhere in a subtree blocks subtree operations.
    scripted.call("node.reparent", path="Tool", parent="Plain", allow_tool_script=True)
    rejected(scripted, "node.duplicate", "READ_ONLY_RESOURCE", path="Plain")


def test_duplicate_keeps_script_and_groups(scripted):
    scripted.call("node.duplicate", path="Plain", name="PlainCopy")
    copy = scripted.call("node.inspect", path="PlainCopy")
    assert copy["script"] == "res://scripts/plain.gd"
    assert copy["groups"] == ["enemies"]
    assert value(scripted, "PlainCopy", "health") == 7
    scripted.call("node.set_property", path="PlainCopy", property="health", value=11)
    assert value(scripted, "Plain", "health") == 7
    scripted.call("scene.save")
    text = read(scripted, "scenes/test_duplicate_keeps_script_and_groups.tscn")
    block = text[text.index('name="PlainCopy"') :]
    assert 'groups=["enemies"]' in block.splitlines()[0]
    assert "script = ExtResource" in block
    assert "health = 11" in block


def test_integer_exports_stay_integers_and_honor_hints(scripted):
    scripted.call("node.set_property", path="Plain", property="health", value=9)
    scripted.call("node.set_property", path="Plain", property="level", value=10)
    scripted.call("node.set_property", path="Plain", property="mode", value=5)
    scripted.call("node.set_property", path="Plain", property="tag", value="y")
    for property, bad in [("level", 11), ("level", -1), ("mode", 2), ("tag", "z"), ("health", 2.5)]:
        rejected(
            scripted,
            "node.set_property",
            "INVALID_ARGUMENT",
            path="Plain",
            property=property,
            value=bad,
        )
    scripted.call("scene.save")
    text = read(scripted, "scenes/test_integer_exports_stay_integers_and_honor_hints.tscn")
    assert "health = 9" in text and "health = 9.0" not in text
    assert "level = 10" in text and "mode = 5" in text and 'tag = "y"' in text
