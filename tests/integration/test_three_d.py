import pytest
from godotbridge.demo import build_arena
from godotbridge.errors import BridgeError

pytestmark = pytest.mark.engine


def test_arena(editor):
    tree = build_arena(editor)
    nodes = {node["node_path"]: node for node in tree["nodes"]}
    assert nodes["Floor"]["mesh"]["type"] == "BoxMesh"
    assert nodes["Floor/Body/Collision"]["shape"]["type"] == "BoxShape3D"
    assert nodes["MainCamera"]["class"] == "Camera3D"
    assert len(nodes) == 28
    editor.call("scene.close")
    editor.call("scene.open", path="res://scenes/arena.tscn")
    assert len(editor.call("scene.tree")["nodes"]) == 28


@pytest.mark.parametrize(
    "kind,mesh", [("sphere", "SphereMesh"), ("cylinder", "CylinderMesh"), ("plane", "PlaneMesh")]
)
def test_primitives(editor, kind, mesh):
    result = editor.call("3d.create_primitive", name=kind, kind=kind)
    assert result["mesh"]["type"] == mesh
    editor.call("editor.undo")
    with pytest.raises(BridgeError):
        editor.call("node.inspect", path=kind)
    editor.call("editor.redo")
    editor.call("node.inspect", path=f"{kind}/Body/Collision")


def test_resource_property(editor):
    editor.call("node.create", type="MeshInstance3D", name="ResourceTest")
    editor.call(
        "node.set_property",
        path="ResourceTest",
        property="mesh",
        value={"type": "BoxMesh", "properties": {"size": {"type": "Vector3", "value": [2, 3, 4]}}},
    )
    value = editor.call("node.get_property", path="ResourceTest", property="mesh")["value"]
    assert value["properties"]["size"]["value"] == [2, 3, 4]
    editor.call("editor.undo")
    assert editor.call("node.get_property", path="ResourceTest", property="mesh")["value"] is None
    editor.call("editor.redo")
    assert (
        editor.call("node.get_property", path="ResourceTest", property="mesh")["value"]["type"]
        == "BoxMesh"
    )
