import pytest
from helpers import read, rejected, write

pytestmark = pytest.mark.engine

BASE = """[gd_scene format=3]

[node name="Base" type="Node3D"]

[node name="Arm" type="Node3D" parent="."]

[node name="Hand" type="Node3D" parent="Arm"]
"""
MIDDLE = """[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://scenes/inh_base.tscn" id="1"]

[node name="Middle" instance=ExtResource("1")]

[node name="MidNode" type="Node3D" parent="Arm" index="0"]
"""
DERIVED = """[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="res://scenes/{base}.tscn" id="1"]

[node name="Derived" instance=ExtResource("1")]
"""


def derive(editor, request, base="inh_base"):
    """Write a base chain plus an inherited scene named after the test, and open it."""
    write(editor, "scenes/inh_base.tscn", BASE)
    write(editor, "scenes/inh_middle.tscn", MIDDLE)
    name = request.node.name
    write(editor, f"scenes/{name}.tscn", DERIVED.format(base=base))
    editor.call("scene.open", path=f"res://scenes/{name}.tscn")
    return f"scenes/{name}.tscn"


def test_inherited_nodes_accept_overrides_only(editor, request):
    file = derive(editor, request)
    root = editor.call("node.inspect", path=".")
    assert root["inherited"] is True
    assert editor.call("node.inspect", path="Arm/Hand")["inherited"] is True
    editor.call("node.set_transform", path="Arm", position=[1, 2, 3])
    editor.call("node.set_property", path="Arm/Hand", property="visible", value=False)
    editor.call("node.set_property", path=".", property="visible", value=False)
    for method, params in [
        ("node.delete", {"path": "Arm"}),
        ("node.delete", {"path": "Arm/Hand"}),
        ("node.rename", {"path": "Arm", "name": "Other"}),
        ("node.rename", {"path": ".", "name": "Other"}),
        ("node.reparent", {"path": "Arm/Hand", "parent": "."}),
        ("node.duplicate", {"path": "Arm"}),
    ]:
        rejected(editor, method, "READ_ONLY_RESOURCE", **params)
    editor.call("scene.save")
    text = read(editor, file)
    assert '[node name="Arm" parent="." index="0"]' in text
    assert "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 1, 2, 3)" in text
    assert '[node name="Hand" parent="Arm" index="0"]' in text
    assert text.count("visible = false") == 2
    assert 'name="Arm" type=' not in text and 'name="Hand" type=' not in text
    editor.call("scene.close")
    editor.call("scene.open", path="res://" + file)
    assert editor.call("node.inspect", path="Arm")["position"]["value"] == [1, 2, 3]
    assert editor.call("node.get_property", path="Arm/Hand", property="visible")["value"] is False
    editor.call("node.set_property", path="Arm", property="visible", value=False)
    editor.call("editor.undo")
    editor.call("editor.undo")
    assert editor.call("node.inspect", path="Arm")["position"]["value"] == [1, 2, 3]


def test_nodes_added_in_derived_scene_are_fully_editable(editor, request):
    file = derive(editor, request)
    editor.call("node.create", parent="Arm/Hand", name="Extra")
    assert editor.call("node.inspect", path="Arm/Hand/Extra")["inherited"] is False
    editor.call("node.create", name="Local")
    editor.call("node.rename", path="Arm/Hand/Extra", name="Renamed")
    editor.call("node.reparent", path="Local", parent="Arm")
    editor.call("node.duplicate", path="Arm/Local", name="LocalCopy")
    editor.call("node.set_transform", path="Arm/LocalCopy", position=[0, 5, 0])
    editor.call("node.delete", path="Arm/Hand/Renamed")
    editor.call("editor.undo")
    editor.call("node.inspect", path="Arm/Hand/Renamed")
    editor.call("node.delete", path="Arm/Hand/Renamed")
    editor.call("node.delete", path="Arm/LocalCopy")
    editor.call("editor.undo")
    editor.call("scene.save")
    text = read(editor, file)
    assert 'name="Local" type="Node3D" parent="Arm"' in text
    assert "Renamed" not in text
    assert 'name="Arm" type=' not in text
    editor.call("scene.close")
    editor.call("scene.open", path="res://" + file)
    assert editor.call("node.inspect", path="Arm/LocalCopy")["inherited"] is False
    assert editor.call("node.inspect", path="Arm/Local")["inherited"] is False


def test_nodes_from_every_level_of_the_base_chain_are_inherited(editor, request):
    derive(editor, request, base="inh_middle")
    for path in ("Arm", "Arm/Hand", "Arm/MidNode"):
        assert editor.call("node.inspect", path=path)["inherited"] is True
        rejected(editor, "node.delete", "READ_ONLY_RESOURCE", path=path)
    editor.call("node.set_property", path="Arm/MidNode", property="visible", value=False)
    editor.call("node.create", parent="Arm/MidNode", name="Leaf")
    editor.call("node.delete", path="Arm/MidNode/Leaf")


def test_base_changed_after_opening_is_treated_conservatively(editor, request):
    derive(editor, request)
    editor.call("node.create", name="Local")
    editor.call("node.delete", path="Local")
    editor.call("editor.undo")
    base = editor.config.project / "scenes/inh_base.tscn"
    base.write_text(
        base.read_text(encoding="utf-8") + '\n[node name="Late" type="Node3D" parent="."]\n',
        encoding="utf-8",
    )
    # The open tree no longer matches the base on disk: nothing may be deleted until reopening.
    rejected(editor, "node.delete", "READ_ONLY_RESOURCE", path="Local")
    editor.call("node.set_property", path="Arm", property="visible", value=False)
    write(editor, "scenes/inh_base.tscn", BASE)


def test_plain_and_instance_scenes_are_not_inherited(editor, request):
    write(editor, "scenes/inh_base.tscn", BASE)
    editor.call("scene.create", path=f"res://scenes/{request.node.name}.tscn")
    editor.call("node.instantiate", scene="res://scenes/inh_base.tscn", name="Inst")
    assert editor.call("node.inspect", path=".")["inherited"] is False
    assert editor.call("node.inspect", path="Inst")["inherited"] is False
    editor.call("node.rename", path="Inst", name="Renamed")
    rejected(editor, "node.rename", "INVALID_ARGUMENT", path=".", name="Other")


def test_new_unsaved_inherited_scene_is_detected(editor):
    write(editor, "scenes/inh_base.tscn", BASE)
    opened = editor.call("scene.open", path="res://scenes/inh_base.tscn", inherited=True)
    assert opened["scene_path"] == ""
    assert editor.call("node.inspect", path="Arm")["inherited"] is True
    rejected(editor, "node.delete", "READ_ONLY_RESOURCE", path="Arm/Hand")
    rejected(editor, "node.rename", "READ_ONLY_RESOURCE", path="Arm", name="Other")
    editor.call("node.set_property", path="Arm", property="visible", value=False)
    editor.call("node.create", parent="Arm", name="Added")
    editor.call("node.delete", path="Arm/Added")
    editor.call("scene.save_as", path="res://scenes/new_inherited.tscn")
    rejected(editor, "node.delete", "READ_ONLY_RESOURCE", path="Arm")
    text = read(editor, "scenes/new_inherited.tscn")
    assert "instance=ExtResource" in text and 'name="Arm" type=' not in text


def test_base_change_between_open_and_first_call_is_detected(editor, request):
    derive(editor, request)
    base = editor.config.project / "scenes/inh_base.tscn"
    base.write_text(
        base.read_text(encoding="utf-8")
        + "# changed after open\n[node name=Late type=Node3D parent=.]\n",
        encoding="utf-8",
    )
    editor.call("node.create", name="Local")
    rejected(editor, "node.delete", "READ_ONLY_RESOURCE", path="Local")
    write(editor, "scenes/inh_base.tscn", BASE)
