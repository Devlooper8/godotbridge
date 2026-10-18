import pytest
from helpers import read, rejected, write

pytestmark = pytest.mark.engine

UNIT = """[gd_scene format=3]

[node name="Unit" type="Node3D"]

[node name="Body" type="Node3D" parent="."]

[node name="Gun" type="Node3D" parent="Body"]
"""
TOOLED = """@tool
extends Node3D
"""
TOOL_UNIT = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/tooled_unit.gd" id="1"]

[node name="ToolUnit" type="Node3D"]
script = ExtResource("1")
"""
OUTER = """[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://scenes/unit_inner.tscn" id="1"]

[node name="Outer" type="Node3D"]

[node name="Inner" parent="." instance=ExtResource("1")]
"""
INNER = """[gd_scene format=3]

[node name="Inner" type="Node3D"]
"""


@pytest.fixture
def host(editor, request):
    """A fresh empty scene per test plus the shared instance sources."""
    write(editor, "scenes/unit.tscn", UNIT)
    write(editor, "scripts/tooled_unit.gd", TOOLED)
    write(editor, "scenes/tool_unit.tscn", TOOL_UNIT)
    editor.call("scene.create", path=f"res://scenes/{request.node.name}.tscn")
    return editor


def spawn(editor, name="Hero", parent="."):
    return editor.call("node.instantiate", scene="res://scenes/unit.tscn", name=name, parent=parent)


def saved(editor, request):
    editor.call("scene.save")
    return read(editor, f"scenes/{request.node.name}.tscn")


def reload(editor, request):
    path = f"res://scenes/{request.node.name}.tscn"
    editor.call("scene.close")
    editor.call("scene.open", path=path)


def test_instantiate_override_save_reload(host, request):
    info = spawn(host)
    assert info["scene_file_path"] == "res://scenes/unit.tscn"
    assert info["instance"] == {
        "is_instance_root": True,
        "editable_children": False,
        "inside_instance": False,
    }
    body = host.call("node.inspect", path="Hero/Body")
    assert body["instance"]["inside_instance"] is True
    assert body["instance"]["is_instance_root"] is False
    host.call("node.set_transform", path="Hero", position=[1, 2, 3])
    host.call("node.set_property", path="Hero", property="visible", value=False)
    text = saved(host, request)
    assert 'instance=ExtResource("' in text
    assert "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 2, 3)" in text
    assert "visible = false" in text
    assert 'name="Body"' not in text and 'name="Gun"' not in text
    reload(host, request)
    assert host.call("node.inspect", path="Hero")["position"]["value"] == [1, 2, 3]
    host.call("node.inspect", path="Hero/Body/Gun")


def test_inside_instance_is_protected(host):
    spawn(host)
    for method, params in [
        ("node.set_property", {"path": "Hero/Body", "property": "visible", "value": False}),
        ("node.set_transform", {"path": "Hero/Body", "position": [1, 0, 0]}),
        ("node.delete", {"path": "Hero/Body"}),
        ("node.rename", {"path": "Hero/Body", "name": "Other"}),
        ("node.duplicate", {"path": "Hero/Body"}),
        ("node.reparent", {"path": "Hero/Body", "parent": "."}),
        ("node.create", {"parent": "Hero/Body", "name": "Extra"}),
        ("node.instantiate", {"parent": "Hero/Body", "scene": "res://scenes/unit.tscn"}),
    ]:
        rejected(host, method, "READ_ONLY_RESOURCE", **params)
    host.call("node.create", name="Other")
    rejected(host, "node.reparent", "READ_ONLY_RESOURCE", path="Other", parent="Hero/Body")
    rejected(host, "node.set_editable_children", "READ_ONLY_RESOURCE", path="Hero/Body")
    rejected(host, "node.set_editable_children", "INVALID_ARGUMENT", path="Other")


def test_instance_root_operations_keep_internals_out_of_file(host, request):
    spawn(host)
    host.call("node.create", name="Group")
    host.call("node.rename", path="Hero", name="Boss")
    host.call("node.reparent", path="Boss", parent="Group")
    host.call("node.duplicate", path="Group/Boss", name="Clone")
    host.call("node.inspect", path="Group/Clone/Body/Gun")
    host.call("node.duplicate", path="Group", name="GroupCopy")
    host.call("node.inspect", path="GroupCopy/Boss/Body/Gun")
    host.call("node.delete", path="Group/Clone")
    host.call("editor.undo")
    host.call("node.inspect", path="Group/Clone/Body/Gun")
    host.call("node.delete", path="Group")
    host.call("editor.undo")
    text = saved(host, request)
    assert text.count("instance=ExtResource") == 4
    assert 'name="Body"' not in text and 'name="Gun"' not in text
    reload(host, request)
    host.call("node.inspect", path="GroupCopy/Clone/Body/Gun")


def test_editable_children(host, request):
    spawn(host)
    host.call("node.set_editable_children", path="Hero", editable=True)
    assert host.call("node.inspect", path="Hero")["instance"]["editable_children"] is True
    host.call("node.set_transform", path="Hero/Body", position=[4, 0, 0])
    host.call("node.set_property", path="Hero/Body/Gun", property="visible", value=False)
    host.call("node.create", parent="Hero/Body", name="Extra")
    host.call("node.inspect", path="Hero/Body/Extra")
    rejected(host, "node.rename", "READ_ONLY_RESOURCE", path="Hero/Body", name="Other")
    rejected(host, "node.delete", "READ_ONLY_RESOURCE", path="Hero/Body/Gun")
    rejected(host, "node.reparent", "READ_ONLY_RESOURCE", path="Hero/Body/Gun", parent=".")
    host.call("node.rename", path="Hero/Body/Extra", name="Added")
    text = saved(host, request)
    assert '[editable path="Hero"]' in text
    # Overrides are typeless node entries; only the added child is a full node entry.
    assert '[node name="Body" parent="Hero" index="0"]' in text
    assert "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 4, 0, 0)" in text
    assert 'name="Body" type=' not in text and 'name="Gun" type=' not in text
    assert 'name="Added" type="Node3D" parent="Hero/Body"' in text
    reload(host, request)
    assert host.call("node.inspect", path="Hero/Body")["position"]["value"] == [4, 0, 0]
    assert host.call("node.inspect", path="Hero")["instance"]["editable_children"] is True
    host.call("node.inspect", path="Hero/Body/Added")
    host.call("node.delete", path="Hero/Body/Added")
    host.call("node.set_editable_children", path="Hero", editable=False)
    rejected(
        host,
        "node.set_property",
        "READ_ONLY_RESOURCE",
        path="Hero/Body",
        property="visible",
        value=False,
    )
    host.call("editor.undo")
    assert host.call("node.inspect", path="Hero")["instance"]["editable_children"] is True
    host.call("node.set_property", path="Hero/Body", property="visible", value=False)


def test_instantiate_undo_redo(host, request):
    spawn(host)
    host.call("editor.undo")
    rejected(host, "node.inspect", "NODE_NOT_FOUND", path="Hero")
    host.call("editor.redo")
    host.call("node.inspect", path="Hero/Body/Gun")
    # Unnamed instances take the scene root's name and avoid sibling collisions.
    first = host.call("node.instantiate", scene="res://scenes/unit.tscn")
    second = host.call("node.instantiate", scene="res://scenes/unit.tscn")
    assert (first["name"], second["name"]) == ("Unit", "Unit2")
    text = saved(host, request)
    assert text.count("instance=ExtResource") == 3
    assert 'name="Gun"' not in text


def test_instantiate_validation(host):
    rejected(host, "node.instantiate", "FILE_ACCESS_DENIED", scene="res://../unit.tscn")
    rejected(host, "node.instantiate", "FILE_ACCESS_DENIED", scene="res://scenes/unit.scn")
    rejected(host, "node.instantiate", "SCENE_NOT_FOUND", scene="res://scenes/missing.tscn")
    rejected(
        host, "node.instantiate", "NODE_NOT_FOUND", scene="res://scenes/unit.tscn", parent="No"
    )
    spawn(host)
    rejected(
        host, "node.instantiate", "INVALID_ARGUMENT", scene="res://scenes/unit.tscn", name="Hero"
    )
    # Self and indirect recursion.
    own = host.call("scene.current")["scene_path"]
    rejected(host, "node.instantiate", "INVALID_ARGUMENT", scene=own)
    write(host, "scenes/unit_inner.tscn", INNER)
    write(host, "scenes/unit_outer.tscn", OUTER)
    host.call("scene.open", path="res://scenes/unit_inner.tscn")
    rejected(host, "node.instantiate", "INVALID_ARGUMENT", scene="res://scenes/unit_outer.tscn")
    # A scene containing a @tool script needs the opt-in.
    host.call("scene.open", path=own)
    rejected(host, "node.instantiate", "READ_ONLY_RESOURCE", scene="res://scenes/tool_unit.tscn")
    host.call(
        "node.instantiate",
        scene="res://scenes/tool_unit.tscn",
        name="Tooled",
        allow_tool_script=True,
    )


def test_cli_and_mcp_expose_instancing(host):
    import json
    import subprocess
    import sys

    from godotbridge.mcp_server import TOOL_OPERATIONS

    assert TOOL_OPERATIONS["godot_node_instantiate"] == "node.instantiate"
    assert TOOL_OPERATIONS["godot_node_set_editable_children"] == "node.set_editable_children"

    def godotctl(*args):
        result = subprocess.run(
            [sys.executable, "-m", "godotbridge.cli", "--project", str(host.config.project)]
            + ["--json", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        return json.loads(result.stdout)["result"]

    created = godotctl("node", "instantiate", "res://scenes/unit.tscn", "--name", "Cli")
    assert created["instance"]["is_instance_root"]
    assert godotctl("node", "editable-children", "Cli")["instance"]["editable_children"]
    assert not godotctl("node", "editable-children", "Cli", "--disable")["instance"][
        "editable_children"
    ]
