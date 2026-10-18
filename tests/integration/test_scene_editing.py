import pytest
from godotbridge.errors import BridgeError

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
