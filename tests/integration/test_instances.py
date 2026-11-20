from types import SimpleNamespace

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
TOOL_CHILD_UNIT = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/tooled_unit.gd" id="1"]

[node name="Plain" type="Node3D"]

[node name="Tooled" type="Node3D" parent="."]
script = ExtResource("1")
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


def test_added_children_survive_structure_undo_redo(host, request):
    spawn(host)
    host.call("node.create", parent="Hero", name="Extra")
    host.call("node.set_editable_children", path="Hero", editable=True)
    host.call("node.create", parent="Hero/Body", name="Deep")
    host.call("node.create", name="Group")
    for _ in range(2):
        host.call("node.delete", path="Hero")
        host.call("editor.undo")
        host.call("editor.redo")
        host.call("editor.undo")
    host.call("node.reparent", path="Hero", parent="Group")
    host.call("editor.undo")
    host.call("editor.redo")
    host.call("editor.undo")
    host.call("node.reparent", path="Hero", parent="Group")
    host.call("node.reparent", path="Group/Hero", parent=".")
    host.call("editor.undo")
    host.call("editor.undo")
    # Undoing and redoing creation of a child below an instance keeps it owned too.
    host.call("node.create", parent="Hero", name="Late")
    host.call("editor.undo")
    host.call("editor.redo")
    text = saved(host, request)
    assert '[node name="Extra" type="Node3D" parent="Hero"' in text
    assert '[node name="Deep" type="Node3D" parent="Hero/Body"' in text
    assert '[node name="Late" type="Node3D" parent="Hero"' in text
    assert 'name="Gun"' not in text
    reload(host, request)
    host.call("node.inspect", path="Hero/Extra")
    host.call("node.inspect", path="Hero/Body/Deep")


def test_duplicate_refuses_instances_with_overrides(host):
    spawn(host)
    host.call("node.duplicate", path="Hero", name="Plain")
    host.call("node.create", parent="Hero", name="Extra")
    rejected(host, "node.duplicate", "UNSUPPORTED_OPERATION", path="Hero")
    host.call("node.create", name="Group")
    host.call("node.reparent", path="Plain", parent="Group")
    host.call("node.duplicate", path="Group", name="GroupCopy")
    host.call("node.set_editable_children", path="Group/Plain", editable=True)
    rejected(host, "node.duplicate", "UNSUPPORTED_OPERATION", path="Group", name="G2")


def test_tool_scripts_inside_instances_block_subtree_operations(host):
    write(host, "scenes/tool_child_unit.tscn", TOOL_CHILD_UNIT)
    host.call(
        "node.instantiate",
        scene="res://scenes/tool_child_unit.tscn",
        name="Tooled",
        allow_tool_script=True,
    )
    host.call("node.create", name="Group")
    host.call("node.reparent", path="Tooled", parent="Group", allow_tool_script=True)
    for method, params in [
        ("node.delete", {"path": "Group"}),
        ("node.duplicate", {"path": "Group"}),
        ("node.reparent", {"path": "Group", "parent": "."}),
    ]:
        rejected(host, method, "READ_ONLY_RESOURCE", **params)
    host.call("node.delete", path="Group", allow_tool_script=True)


DERIVED_TOOL_SCRIPT = """extends "res://scripts/tooled_unit.gd"
"""
PRELOADING_SCRIPT = """extends Node3D
const Base = preload("res://scripts/tooled_unit.gd")
"""


@pytest.mark.parametrize(
    "source", [DERIVED_TOOL_SCRIPT, PRELOADING_SCRIPT], ids=["extends", "preload"]
)
def test_tool_script_reached_through_another_script(host, source):
    write(host, "scripts/indirect.gd", source)
    write(
        host,
        "scenes/indirect.tscn",
        '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://scripts/indirect.gd" id="1"]\n\n'
        '[node name="Indirect" type="Node3D"]\nscript = ExtResource("1")\n',
    )
    rejected(host, "node.instantiate", "READ_ONLY_RESOURCE", scene="res://scenes/indirect.tscn")
    host.call("node.instantiate", scene="res://scenes/indirect.tscn", allow_tool_script=True)


def test_dependency_cap_fails_closed(host):
    lines = ['[gd_scene format=3]\n\n[node name="Heavy" type="Node3D"]\n']
    for index in range(520):
        write(
            host,
            f"scenes/many/r{index}.tres",
            '[gd_resource type="Resource" format=3]\n\n[resource]\n',
        )
    header = "".join(
        f'[ext_resource type="Resource" path="res://scenes/many/r{index}.tres" id="{index}"]\n'
        for index in range(520)
    )
    write(host, "scenes/heavy.tscn", "[gd_scene load_steps=2 format=3]\n\n" + header + lines[0])
    rejected(host, "node.instantiate", "INVALID_ARGUMENT", scene="res://scenes/heavy.tscn")


MESHED = """[gd_scene load_steps=2 format=3]

[sub_resource type="BoxMesh" id="BoxMesh_a"]
size = Vector3({size}, {size}, {size})

[node name="Meshed" type="Node3D"]

[node name="Mesh" type="MeshInstance3D" parent="."]
mesh = SubResource("BoxMesh_a")
"""
LATE_SCENE = """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/late_tool.gd" id="1"]

[node name="Late" type="Node3D"]
script = ExtResource("1")
"""


def mesh_size(editor, path):
    mesh = editor.call("node.get_property", path=path, property="mesh")["value"]
    return mesh["properties"]["size"]["value"]


def test_instantiate_reads_scene_edited_on_disk(host):
    # The loader reuses a cached sub-resource while any instance (or an undo step) holds it.
    write(host, "scenes/meshed.tscn", MESHED.format(size=1))
    host.call("node.instantiate", scene="res://scenes/meshed.tscn", name="Old")
    write(host, "scenes/meshed.tscn", MESHED.format(size=5))
    host.call("node.instantiate", scene="res://scenes/meshed.tscn", name="New")
    assert mesh_size(host, "New/Mesh") == [5, 5, 5]
    assert mesh_size(host, "Old/Mesh") == [1, 1, 1]


def test_instantiate_rechecks_tool_script_edited_on_disk(host):
    write(host, "scripts/late_tool.gd", "extends Node3D\n")
    write(host, "scenes/late.tscn", LATE_SCENE)
    host.call("node.instantiate", scene="res://scenes/late.tscn", name="Before")
    # The cached script of the live node above is still the non-@tool version.
    write(host, "scripts/late_tool.gd", TOOLED)
    rejected(host, "node.instantiate", "READ_ONLY_RESOURCE", scene="res://scenes/late.tscn")
    host.call(
        "node.instantiate", scene="res://scenes/late.tscn", name="After", allow_tool_script=True
    )


def test_instantiate_rechecks_cached_tool_script_dropped_on_disk(host):
    write(host, "scripts/cached_tool.gd", TOOLED)
    write(
        host,
        "scripts/cached_user.gd",
        'extends Node3D\nconst Base = preload("res://scripts/cached_tool.gd")\n',
    )
    write(host, "scenes/cached.tscn", script_scene("cached_user"))
    host.call(
        "node.instantiate", scene="res://scenes/cached.tscn", name="Live", allow_tool_script=True
    )
    # The live node keeps the @tool version cached and a new instance would get that script, not the file's. No
    # node carries the script itself, so only the cached-script check can see it.
    write(host, "scripts/cached_tool.gd", "extends Node3D\n")
    rejected(host, "node.instantiate", "READ_ONLY_RESOURCE", scene="res://scenes/cached.tscn")


TOOLED_UID = "uid://b8v13tooled01"
HOST_UID = "uid://b8v13hosttscn1"


def script_scene(script):
    return (
        '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" '
        f'path="res://scripts/{script}.gd" id="1"]\n\n[node name="N" type="Node3D"]\n'
        'script = ExtResource("1")\n'
    )


def seed_uid_references(config):
    # The engine only learns a uid from a sidecar that exists when the editor starts.
    project = SimpleNamespace(config=config)
    write(project, "scripts/tooled.gd", TOOLED)
    write(project, "scripts/tooled.gd.uid", TOOLED_UID + "\n")
    write(project, "scripts/via_preload.gd", f'extends Node3D\nconst T = preload("{TOOLED_UID}")\n')
    write(
        project,
        "scripts/via_load.gd",
        f'extends Node3D\nfunc f():\n\treturn load("{TOOLED_UID}")\n',
    )
    write(
        project,
        "scenes/host.tscn",
        f'[gd_scene format=3 uid="{HOST_UID}"]\n\n[node name="Host" type="Node3D"]\n',
    )
    write(project, "scripts/rec.gd", f'extends Node3D\nfunc f():\n\treturn load("{HOST_UID}")\n')
    for script in ["via_preload", "via_load", "rec"]:
        write(project, f"scenes/{script}.tscn", script_scene(script))


def test_uid_references_in_scripts_are_followed(extra_editor):
    with extra_editor(seed_uid_references) as client:
        client.call("scene.open", path="res://scenes/host.tscn")
        for script in ["via_preload", "via_load"]:
            rejected(
                client,
                "node.instantiate",
                "READ_ONLY_RESOURCE",
                scene=f"res://scenes/{script}.tscn",
            )
        client.call(
            "node.instantiate", scene="res://scenes/via_preload.tscn", allow_tool_script=True
        )
        rejected(client, "node.instantiate", "INVALID_ARGUMENT", scene="res://scenes/rec.tscn")


def gd_string(source):
    """GDScript source as the value of a scene file's script/source property."""
    return '"' + source.replace("\\", "\\\\").replace('"', '\\"') + '"'


def marker_script(marker, base="Node3D", class_name=None):
    """A @tool script that leaves a file behind. _static_init runs as soon as the script loads, _init only for
    instances that are not placeholders, so the marker also shows a script that was loaded and never instantiated."""
    body = f'\tFileAccess.open("res://{marker}", FileAccess.WRITE).store_string("ran")\n'
    named = f"class_name {class_name}\n" if class_name else ""
    return (
        f"@tool\n{named}extends {base}\nstatic func _static_init():\n{body}\nfunc _init():\n{body}"
    )


def embedded_scene(source, node_script=True):
    """A scene whose only script is a GDScript sub_resource, as a node script or as a resource's script."""
    if node_script:
        return (
            '[gd_scene load_steps=2 format=3]\n\n[sub_resource type="GDScript" id="G"]\n'
            f'script/source = {gd_string(source)}\n\n[node name="Embedded" type="Node3D"]\n'
            'script = SubResource("G")\n'
        )
    return (
        '[gd_scene load_steps=3 format=3]\n\n[sub_resource type="GDScript" id="G"]\n'
        f'script/source = {gd_string(source)}\n\n[sub_resource type="Resource" id="R"]\n'
        'script = SubResource("G")\n\n[node name="Embedded" type="Node3D"]\n'
        'metadata/payload = SubResource("R")\n'
    )


def seed_embedded(editor, case, marker):
    """Writes the scene for one way of hiding a @tool script inside scene files; returns its path."""
    base = f"scripts/marker_{case}.gd"
    # Only an embedded script extends it, so no dependency list names it.
    write(editor, base, marker_script(marker))
    derived = f'extends "res://{base}"\n'
    if case == "attached":
        scene = script_scene(f"marker_{case}")
    elif case == "relative":
        write(editor, "scripts/relative_derived.gd", f'extends "marker_{case}.gd"\n')
        scene = script_scene("relative_derived")
    elif case == "preload":
        scene = embedded_scene(f'extends Node3D\nconst Base = preload("res://{base}")\n')
    elif case == "node":
        scene = embedded_scene(marker_script(marker))
    elif case == "resource":
        scene = embedded_scene(marker_script(marker, "Resource"), node_script=False)
    elif case == "extends":
        scene = embedded_scene(derived)
    elif case == "nested":
        write(editor, f"scenes/{case}_inner.tscn", embedded_scene(derived))
        scene = (
            '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="PackedScene" '
            f'path="res://scenes/{case}_inner.tscn" id="1"]\n\n[node name="Outer" type="Node3D"]\n\n'
            '[node name="Inner" parent="." instance=ExtResource("1")]\n'
        )
    else:  # override: the embedded script sits on an instance of a plain scene.
        scene = (
            '[gd_scene load_steps=3 format=3]\n\n[ext_resource type="PackedScene" '
            'path="res://scenes/unit.tscn" id="1"]\n\n[sub_resource type="GDScript" id="G"]\n'
            f'script/source = {gd_string(derived)}\n\n[node name="Outer" type="Node3D"]\n\n'
            '[node name="Unit" parent="." instance=ExtResource("1")]\nscript = SubResource("G")\n'
        )
    write(editor, f"scenes/{case}.tscn", scene)
    return f"res://scenes/{case}.tscn"


@pytest.mark.parametrize(
    "case",
    ["node", "resource", "extends", "nested", "override", "attached", "relative", "preload"],
)
def test_tool_script_hidden_in_scene_files_needs_opt_in(host, case):
    marker = f"ran_{case}.txt"
    scene = seed_embedded(host, case, marker)
    rejected(host, "node.instantiate", "READ_ONLY_RESOURCE", scene=scene)
    # The refusal comes from the source text alone: loading a @tool script already runs its _static_init.
    assert not (host.config.project / marker).exists(), "the script ran without the opt-in"
    host.call("node.instantiate", scene=scene, name="Allowed", allow_tool_script=True)
    assert (host.config.project / marker).exists()


def seed_class_name_bases(config):
    # The engine registers a class_name when the project is scanned, so the files must exist at startup.
    project = SimpleNamespace(config=config)
    write(project, "scripts/named_base.gd", marker_script("ran_named.txt", class_name="NamedBase"))
    write(project, "scripts/named_derived.gd", "extends NamedBase\n")
    write(project, "scenes/named_attached.tscn", script_scene("named_derived"))
    write(project, "scenes/named_embedded.tscn", embedded_scene("extends NamedBase\n"))
    write(project, "scenes/open.tscn", '[gd_scene format=3]\n\n[node name="Open" type="Node3D"]\n')


@pytest.mark.parametrize("scene", ["named_attached", "named_embedded"])
def test_tool_script_reached_through_a_class_name_needs_opt_in(extra_editor, scene):
    with extra_editor(seed_class_name_bases) as client:
        client.call("scene.open", path="res://scenes/open.tscn")
        rejected(
            client, "node.instantiate", "READ_ONLY_RESOURCE", scene=f"res://scenes/{scene}.tscn"
        )
        assert not (client.config.project / "ran_named.txt").exists()
        client.call("node.instantiate", scene=f"res://scenes/{scene}.tscn", allow_tool_script=True)
        assert (client.config.project / "ran_named.txt").exists()


def test_plain_script_embedded_in_a_scene_needs_no_opt_in(host):
    write(host, "scenes/plain_embedded.tscn", embedded_scene("extends Node3D\nvar answer = 42\n"))
    host.call("node.instantiate", scene="res://scenes/plain_embedded.tscn", name="Plain")
