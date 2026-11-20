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


def test_resource_property_with_hint_list(editor):
    # material_override's hint is "BaseMaterial3D,ShaderMaterial": any listed class is accepted.
    editor.call("node.create", type="MeshInstance3D", name="MaterialTest")
    editor.call(
        "node.set_property",
        path="MaterialTest",
        property="material_override",
        value={"type": "StandardMaterial3D", "properties": {"roughness": 0.25}},
    )
    value = editor.call("node.get_property", path="MaterialTest", property="material_override")[
        "value"
    ]
    assert value["type"] == "StandardMaterial3D"
    assert value["properties"]["roughness"] == pytest.approx(0.25)
    editor.call("editor.undo")
    assert (
        editor.call("node.get_property", path="MaterialTest", property="material_override")["value"]
        is None
    )
    with pytest.raises(BridgeError) as caught:
        editor.call(
            "node.set_property",
            path="MaterialTest",
            property="material_override",
            value={"type": "BoxMesh"},
        )
    assert caught.value.code == "INVALID_ARGUMENT"


# (node type, property, rejected values, accepted value): the engine setters clamp, wrap or ignore these,
# so the inspector's range, enum and layer hints are the only guard against writing them into the scene.
HINT_CASES = {
    "cast_shadow": ("MeshInstance3D", "cast_shadow", [99, -1], 3),
    "cast_shadow_zero": ("MeshInstance3D", "cast_shadow", [4], 0),
    "projection": ("Camera3D", "projection", [1000000000, -1, 3], 1),
    "near": ("Camera3D", "near", [0.0001, 0], 0.05),
    "far": ("Camera3D", "far", [0.005], 100),
    "camera_size": ("Camera3D", "size", [0.0005], 5),
    "light_energy": ("DirectionalLight3D", "light_energy", [-1], 16),
    "light_energy_zero": ("DirectionalLight3D", "light_energy", [-0.5], 0),
    "light_energy_or_greater": ("DirectionalLight3D", "light_energy", [], 1e9),
    "omni_range": ("OmniLight3D", "omni_range", [-1], 0),
    "spot_angle": ("SpotLight3D", "spot_angle", [181, -1], 180),
    "spot_range": ("SpotLight3D", "spot_range", [-1], 0),
    "collision_layer": ("StaticBody3D", "collision_layer", [-5], 4294967295),
    "collision_mask": ("StaticBody3D", "collision_mask", [-1], 1000000000),
    "mass": ("RigidBody3D", "mass", [0.0005], 1e9),
    "gravity_scale_or_less": ("RigidBody3D", "gravity_scale", [], -1e9),
    "gravity_scale_or_greater": ("RigidBody3D", "gravity_scale", [], 1e9),
}


@pytest.mark.parametrize("case", HINT_CASES)
def test_engine_property_hints_are_enforced(editor, case):
    kind, property, bad, good = HINT_CASES[case]
    name = f"Hint_{case}"
    editor.call("node.create", type=kind, name=name)
    for value in bad:
        with pytest.raises(BridgeError) as caught:
            editor.call("node.set_property", path=name, property=property, value=value)
        assert caught.value.code == "INVALID_ARGUMENT", (property, value)
    editor.call("node.set_property", path=name, property=property, value=good)
    assert editor.call("node.get_property", path=name, property=property)["value"] == pytest.approx(
        good
    )


def test_resource_property_hints_are_enforced(editor):
    editor.call("node.create", type="MeshInstance3D", name="HintMaterial")
    for properties in [{"roughness": 5}, {"metallic": -3}, {"roughness": 1.5, "metallic": 0.5}]:
        with pytest.raises(BridgeError) as caught:
            editor.call(
                "node.set_property",
                path="HintMaterial",
                property="material_override",
                value={"type": "StandardMaterial3D", "properties": properties},
            )
        assert caught.value.code == "INVALID_ARGUMENT", properties
    editor.call(
        "node.set_property",
        path="HintMaterial",
        property="material_override",
        value={"type": "StandardMaterial3D", "properties": {"roughness": 1, "metallic": 0}},
    )
