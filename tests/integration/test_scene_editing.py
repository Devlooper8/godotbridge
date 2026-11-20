import math

import pytest
from godotbridge.errors import BridgeError
from helpers import read, rejected, write

pytestmark = pytest.mark.engine


def missing(editor, path):
    with pytest.raises(BridgeError) as caught:
        editor.call("node.inspect", path=path)
    assert caught.value.code == "NODE_NOT_FOUND"


def test_create_transform_property_delete_undo_redo(editor):
    editor.call("scene.create", path="res://scenes/editing.tscn")
    editor.call("node.create", name="Object")
    assert editor.call("node.inspect", path="Object")["class"] == "Node3D"
    editor.call("editor.undo")
    missing(editor, "Object")
    editor.call("editor.redo")
    editor.call("node.set_transform", path="Object", position=[1, 2, 3], rotation=[0, 90, 0])
    assert editor.call("node.inspect", path="Object")["position"]["value"] == [1, 2, 3]
    editor.call("editor.undo")
    assert editor.call("node.inspect", path="Object")["position"]["value"] == [0, 0, 0]
    editor.call("editor.redo")
    assert editor.call("node.inspect", path="Object")["rotation_degrees"]["value"][
        1
    ] == pytest.approx(90)
    editor.call("node.set_property", path="Object", property="visible", value=False)
    assert editor.call("node.get_property", path="Object", property="visible")["value"] is False
    editor.call("editor.undo")
    assert editor.call("node.get_property", path="Object", property="visible")["value"] is True
    editor.call("editor.redo")
    assert editor.call("node.get_property", path="Object", property="visible")["value"] is False
    editor.call("node.rename", path="Object", name="Renamed")
    missing(editor, "Object")
    editor.call("editor.undo")
    editor.call("node.inspect", path="Object")
    editor.call("editor.redo")
    editor.call("node.create", parent="Renamed", name="Child")
    editor.call("node.delete", path="Renamed")
    missing(editor, "Renamed")
    editor.call("editor.undo")
    editor.call("node.inspect", path="Renamed/Child")
    editor.call("editor.redo")
    missing(editor, "Renamed")
    editor.call("editor.undo")
    editor.call("scene.save")
    editor.call("scene.close")
    editor.call("scene.open", path="res://scenes/editing.tscn")
    child = editor.call("node.inspect", path="Renamed/Child")
    assert child["class"] == "Node3D"
    assert editor.call("node.inspect", path="Renamed")["position"]["value"] == [1, 2, 3]


def test_duplicate_reparent_and_world_transform(editor):
    editor.call("scene.create", path="res://scenes/reparent.tscn")
    editor.call("node.create", name="Parent")
    editor.call("node.set_transform", path="Parent", position=[10, 0, 0])
    editor.call("node.create", name="Object")
    editor.call("node.set_transform", path="Object", position=[1, 2, 3])
    editor.call("node.reparent", path="Object", parent="Parent")
    assert editor.call("node.inspect", path="Parent/Object")["position"]["value"] == [-9, 2, 3]
    editor.call("editor.undo")
    assert editor.call("node.inspect", path="Object")["position"]["value"] == [1, 2, 3]
    editor.call("editor.redo")
    editor.call("node.set_transform", path="Parent/Object", position=[12, 0, 0], world=True)
    assert editor.call("node.inspect", path="Parent/Object")["position"]["value"] == [2, 0, 0]
    editor.call("node.duplicate", path="Parent", name="Copy")
    editor.call("node.inspect", path="Copy/Object")
    editor.call("editor.undo")
    missing(editor, "Copy")
    editor.call("editor.redo")
    editor.call("scene.save")
    editor.call("scene.close")
    editor.call("scene.open", path="res://scenes/reparent.tscn")
    editor.call("node.inspect", path="Copy/Object")


@pytest.mark.parametrize(
    "method,params,code",
    [
        ("node.inspect", {"path": "../outside"}, "INVALID_NODE_PATH"),
        ("node.inspect", {"path": "/root"}, "INVALID_NODE_PATH"),
        ("node.delete", {"path": "."}, "INVALID_ARGUMENT"),
        (
            "node.set_property",
            {"path": ".", "property": "script", "value": "oops"},
            "UNSUPPORTED_PROPERTY",
        ),
        (
            "node.set_property",
            {"path": ".", "property": "visible", "value": "false"},
            "INVALID_ARGUMENT",
        ),
        ("scene.create", {"path": "res://../escape.tscn"}, "FILE_ACCESS_DENIED"),
        ("node.create", {"name": "invalid/name"}, "INVALID_ARGUMENT"),
    ],
)
def test_invalid_operations(editor, method, params, code):
    with pytest.raises(BridgeError) as caught:
        editor.call(method, **params)
    assert caught.value.code == code


def test_external_modification_not_overwritten(editor):
    editor.call("scene.create", path="res://scenes/conflict.tscn")
    file = editor.config.project / "scenes/conflict.tscn"
    with file.open("a", encoding="utf-8") as stream:
        stream.write("\n; external modification\n")
    editor.call("node.create", name="Unsaved")
    with pytest.raises(BridgeError) as caught:
        editor.call("scene.save")
    assert caught.value.code == "FILE_ACCESS_DENIED"
    assert "external modification" in file.read_text(encoding="utf-8")


def test_save_as_and_selection(editor):
    editor.call("scene.create", path="res://scenes/save-as-source.tscn")
    editor.call("node.create", name="Selected")
    assert editor.call("editor.select", path="Selected")["selected"]
    assert editor.call("editor.focus", path="Selected")["selected"]
    assert any(
        p["name"] == "position"
        for p in editor.call("node.properties", path="Selected")["properties"]
    )
    editor.call("scene.save_as", path="res://scenes/save-as-copy.tscn")
    editor.call("scene.close")
    editor.call("scene.open", path="res://scenes/save-as-copy.tscn")
    assert editor.call("node.inspect", path="Selected")["class"] == "Node3D"
    with pytest.raises(BridgeError) as error:
        editor.call("scene.save_as", path="res://scenes/save-as-source.tscn")
    assert error.value.code == "FILE_ACCESS_DENIED"


REPARENT_2D = """[gd_scene format=3]

[node name="Root" type="Node2D"]

[node name="A" type="Node2D" parent="."]
position = Vector2(100, 50)
rotation = 0.5
scale = Vector2(2, 3)

[node name="C" type="Node2D" parent="."]
position = Vector2(7, 9)

[node name="Singular" type="Node2D" parent="."]
scale = Vector2(0, 0)

[node name="X" type="Node2D" parent="."]
position = Vector2(3, 4)

[node name="K" type="Node2D" parent="."]
position = Vector2(11, 12)
"""
REPARENT_UI = """[gd_scene format=3]

[node name="UI" type="Control"]
layout_mode = 3
anchors_preset = 0

[node name="A" type="Control" parent="."]
layout_mode = 0
offset_left = 100.0
offset_top = 50.0
offset_right = 300.0
offset_bottom = 150.0
rotation = 0.5
scale = Vector2(2, 3)

[node name="Box" type="VBoxContainer" parent="."]
layout_mode = 0
offset_left = 300.0
offset_top = 300.0
offset_right = 400.0
offset_bottom = 400.0

[node name="C" type="Control" parent="."]
layout_mode = 0
offset_left = 7.0
offset_top = 9.0
offset_right = 37.0
offset_bottom = 39.0
rotation = 0.2
scale = Vector2(1.5, 1.5)

[node name="Full" type="Control" parent="."]
layout_mode = 3
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
grow_horizontal = 2
grow_vertical = 2
"""


def local_in_a(point):
    """A point of the parent's space as seen from A (position (100, 50), rotation 0.5, scale (2, 3))."""
    dx, dy = point[0] - 100, point[1] - 50
    cos, sin = math.cos(0.5), math.sin(0.5)
    return [(dx * cos + dy * sin) / 2, (-dx * sin + dy * cos) / 3]


def vector(editor, path, property="position"):
    value = editor.call("node.get_property", path=path, property=property)["value"]
    return value["value"] if isinstance(value, dict) else value


def test_reparent_keeps_global_pose_of_2d_nodes(editor):
    write(editor, "scenes/reparent_2d.tscn", REPARENT_2D)
    editor.call("scene.open", path="res://scenes/reparent_2d.tscn")
    expected = local_in_a([7, 9])
    editor.call("node.reparent", path="C", parent="A")
    assert vector(editor, "A/C") == pytest.approx(expected, abs=1e-3)
    editor.call("editor.undo")
    assert vector(editor, "C") == [7, 9]
    editor.call("editor.redo")
    assert vector(editor, "A/C") == pytest.approx(expected, abs=1e-3)
    # A parent whose transform cannot be inverted is refused; without keep_global the local pose is kept.
    rejected(editor, "node.reparent", "INVALID_ARGUMENT", path="X", parent="Singular")
    assert vector(editor, "X") == [3, 4]
    editor.call("node.reparent", path="K", parent="A", keep_global=False)
    assert vector(editor, "A/K") == [11, 12]


def test_reparent_keeps_global_position_of_controls_and_undoes_container_layout(editor):
    write(editor, "scenes/reparent_ui.tscn", REPARENT_UI)
    editor.call("scene.open", path="res://scenes/reparent_ui.tscn")
    editor.call("node.reparent", path="C", parent="A")
    assert vector(editor, "A/C") == pytest.approx(local_in_a([7, 9]), abs=1e-3)
    editor.call("editor.undo")
    assert vector(editor, "C") == [7, 9]
    # A Container overwrites the rect, rotation and scale of the Control it adopts; undo must bring them all back.
    editor.call("scene.save")
    before = read(editor, "scenes/reparent_ui.tscn")
    for name in ["C", "Full"]:
        editor.call("node.reparent", path=name, parent="Box")
        editor.call("editor.undo")
    assert vector(editor, "C") == [7, 9]
    assert vector(editor, "C", "rotation") == pytest.approx(0.2)
    assert vector(editor, "C", "scale") == [1.5, 1.5]
    editor.call("scene.save")
    assert read(editor, "scenes/reparent_ui.tscn") == before


ROTATION_ORDER = """[gd_scene format=3]

[node name="Order" type="Node3D"]

[node name="Xyz" type="Node3D" parent="."]
rotation_order = 0

[node name="Zyx" type="Node3D" parent="."]
rotation_order = 5
"""


def euler(editor, path):
    return editor.call("node.inspect", path=path)["rotation_degrees"]["value"]


def set_vector(editor, path, property, value):
    editor.call(
        "node.set_property",
        path=path,
        property=property,
        value={"type": "Vector3", "value": value},
    )


@pytest.mark.parametrize("translate", [False, True])
def test_position_edit_keeps_rotation_and_scale(editor, translate):
    editor.call("scene.create", path=f"res://scenes/position_edit_{translate}.tscn")
    editor.call("node.create", name="Obj")
    set_vector(editor, "Obj", "rotation_degrees", [10, 20, 30])
    set_vector(editor, "Obj", "scale", [2, 3, 4])
    editor.call("node.set_transform", path="Obj", position=[1, 2, 3], translate=translate)
    info = editor.call("node.inspect", path="Obj")
    assert info["position"]["value"] == [1, 2, 3]
    assert info["rotation_degrees"]["value"] == pytest.approx([10, 20, 30], abs=1e-3)
    assert info["scale"]["value"] == pytest.approx([2, 3, 4])
    # Each of rotation and scale leaves the other one alone.
    editor.call("node.set_transform", path="Obj", rotation=[5, 6, 7])
    assert euler(editor, "Obj") == pytest.approx([5, 6, 7], abs=1e-3)
    assert editor.call("node.inspect", path="Obj")["scale"]["value"] == pytest.approx([2, 3, 4])
    editor.call("node.set_transform", path="Obj", scale=[4, 3, 2])
    assert euler(editor, "Obj") == pytest.approx([5, 6, 7], abs=1e-3)


def test_set_transform_honors_rotation_order(editor):
    write(editor, "scenes/rotation_order.tscn", ROTATION_ORDER)
    editor.call("scene.open", path="res://scenes/rotation_order.tscn")
    editor.call("node.set_transform", path="Xyz", rotation=[10, 20, 30])
    assert euler(editor, "Xyz") == pytest.approx([10, 20, 30], abs=1e-3)
    set_vector(editor, "Zyx", "rotation_degrees", [40, 50, 60])
    set_vector(editor, "Zyx", "scale", [2, 3, 4])
    editor.call("node.set_transform", path="Zyx", scale=[5, 6, 7])
    assert euler(editor, "Zyx") == pytest.approx([40, 50, 60], abs=1e-3)
    assert editor.call("node.inspect", path="Zyx")["scale"]["value"] == pytest.approx([5, 6, 7])
    editor.call("node.set_transform", path="Zyx", rotation=[10, 20, 30], world=True)
    assert euler(editor, "Zyx") == pytest.approx([10, 20, 30], abs=1e-3)


def test_world_position_edit_under_scaled_parent_keeps_local_basis(editor):
    editor.call("scene.create", path="res://scenes/world_position.tscn")
    editor.call("node.create", name="P")
    set_vector(editor, "P", "rotation_degrees", [0, 45, 0])
    set_vector(editor, "P", "scale", [3, 1, 1])
    editor.call("node.create", name="C", parent="P")
    set_vector(editor, "P/C", "rotation_degrees", [0, 0, 30])
    before = editor.call("node.get_property", path="P/C", property="transform")["value"]["basis"]
    editor.call("node.set_transform", path="P/C", position=[9, 9, 9], world=True)
    info = editor.call("node.inspect", path="P/C")
    assert info["global_transform"]["origin"]["value"] == pytest.approx([9, 9, 9], abs=1e-4)
    assert info["local_transform"]["basis"] == before
    assert info["scale"]["value"] == pytest.approx([1, 1, 1])
    assert info["rotation_degrees"]["value"] == pytest.approx([0, 0, 30], abs=1e-3)
