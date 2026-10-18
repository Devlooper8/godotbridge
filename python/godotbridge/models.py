"""One operation registry supplies validation, plugin schemas and MCP tools."""

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Empty(Arguments):
    pass


NodeType = Literal[
    "Node",
    "Node3D",
    "MeshInstance3D",
    "StaticBody3D",
    "RigidBody3D",
    "CharacterBody3D",
    "CollisionShape3D",
    "Camera3D",
    "DirectionalLight3D",
    "OmniLight3D",
    "SpotLight3D",
    "WorldEnvironment",
    "Marker3D",
    "RayCast3D",
    "Area3D",
]
Name = Annotated[str, Field(min_length=1, max_length=128)]
Coordinate = Annotated[float, Field(ge=-1_000_000_000, le=1_000_000_000)]
Vector = tuple[Coordinate, Coordinate, Coordinate]


class ScenePath(Arguments):
    path: str = Field(description="Project-relative res:// path to a .tscn scene", max_length=1024)


class SceneCreate(ScenePath):
    root: NodeType = "Node3D"


class ToolScriptOptIn(Arguments):
    allow_tool_script: bool = Field(
        default=False,
        description="Permit mutating nodes whose script is @tool; such scripts run inside the editor.",
    )


class NodePath(Arguments):
    path: str = Field(
        default=".", max_length=1024, description="Path relative to edited scene root; '.' is root"
    )


class NodeCreate(ToolScriptOptIn):
    type: NodeType = "Node3D"
    name: Name
    parent: str = "."


class NodeMutation(NodePath, ToolScriptOptIn):
    pass


class NodeRename(NodeMutation):
    name: Name


class NodeDuplicate(NodeMutation):
    name: Name | None = None


class NodeInstantiate(ToolScriptOptIn):
    scene: str = Field(
        max_length=1024, description="Project-relative res:// path to the saved .tscn to instance"
    )
    parent: str = "."
    name: Name | None = Field(default=None, description="Defaults to the scene root's name")


class SetEditableChildren(NodeMutation):
    editable: bool = Field(
        default=True, description="Allow editing the instance's internal nodes in this scene"
    )


class NodeReparent(NodeMutation):
    parent: str
    keep_global: bool = True


class Transform(NodeMutation):
    position: Vector | None = None
    rotation: Vector | None = Field(
        default=None, description="Euler angles in degrees (Godot YXZ order)"
    )
    scale: Vector | None = None
    world: bool = False
    translate: bool = False


class Property(NodePath):
    property: str = Field(min_length=1, max_length=128)


class SetProperty(Property, ToolScriptOptIn):
    value: JsonValue


class Primitive(ToolScriptOptIn):
    name: Name
    parent: str = "."
    kind: Literal["box", "sphere", "cylinder", "plane"] = "box"
    size: tuple[
        Annotated[float, Field(gt=0, le=100000)],
        Annotated[float, Field(gt=0, le=100000)],
        Annotated[float, Field(gt=0, le=100000)],
    ] = (1, 1, 1)
    radius: float = Field(default=0.5, gt=0, le=100000)
    height: float = Field(default=1, gt=0, le=100000)
    color: tuple[float, float, float, float] = (0.55, 0.65, 0.8, 1)
    collision: bool = True
    position: Vector = (0, 0, 0)


class Light(ToolScriptOptIn):
    name: Name = "Light"
    parent: str = "."
    type: Literal["directional", "omni", "spot"] = "directional"
    color: tuple[float, float, float, float] = (1, 1, 1, 1)
    energy: float = Field(default=1, ge=0, le=1000)
    position: Vector = (0, 5, 0)
    rotation: Vector = (-45, -30, 0)


class Camera(ToolScriptOptIn):
    name: Name = "MainCamera"
    parent: str = "."
    position: Vector = (10, 8, 12)
    target: Vector = (0, 0, 0)
    fov: float = Field(default=70, gt=1, lt=179)
    current: bool = True


class Capture(Arguments):
    method: Literal["preview", "editor"] = "preview"
    width: int = Field(default=960, ge=64, le=2048)
    height: int = Field(default=640, ge=64, le=2048)
    viewpoint: Literal["perspective", "top", "front", "side", "custom"] = "perspective"
    position: Vector = (15, 13, 18)
    target: Vector = (0, 0, 0)
    distance: float = Field(default=25, gt=0, le=100000)
    viewport: int = Field(default=0, ge=0, le=3)


class CaptureOutput(Capture):
    output: str = "viewport.png"


class Snapshot(Capture):
    output_dir: str = "snapshots"


class ScriptPath(Arguments):
    path: str


class GameRun(Arguments):
    mode: Literal["managed", "editor"] = "managed"
    scene: str | None = None
    current: bool = False
    headless: bool = False
    max_seconds: float = Field(default=3600, gt=0, le=86400)


class GameMode(Arguments):
    mode: Literal["managed", "editor"] = "managed"


class GameCapture(Arguments):
    output: str = "game.png"


@dataclass(frozen=True)
class Operation:
    arguments: type[Arguments]
    description: str
    mutating: bool = False
    tool: str | None = None
    backend: Literal["editor", "client"] = "editor"


OPERATIONS: dict[str, Operation] = {
    "project.info": Operation(
        Empty,
        "Read project identity, engine version and capabilities; falls back to a headless engine if offline.",
    ),
    "editor.status": Operation(Empty, "Read connection, scene and editor play status."),
    "scene.list": Operation(Empty, "List scenes currently open in the editor."),
    "scene.current": Operation(Empty, "Read the current scene identity."),
    "scene.close": Operation(Empty, "Close a saved scene; refuse unsaved changes.", True),
    "scene.tree": Operation(Empty, "Inspect hierarchy, transforms, selection and 3D resources."),
    "scene.open": Operation(ScenePath, "Open a project scene in the editor.", True),
    "scene.create": Operation(
        SceneCreate, "Create a new scene file without overwriting and open it.", True
    ),
    "scene.save": Operation(Empty, "Save the current scene using the editor.", True),
    "scene.save_as": Operation(
        ScenePath, "Save the edited scene to a new path; refuse overwrites.", True
    ),
    "node.create": Operation(NodeCreate, "Add an owned node as one undoable editor action.", True),
    "node.delete": Operation(
        NodeMutation, "Delete a non-root node; undo restores the subtree.", True
    ),
    "node.rename": Operation(
        NodeRename, "Rename a node without colliding with its siblings.", True
    ),
    "node.duplicate": Operation(
        NodeDuplicate,
        "Duplicate a locally owned subtree, keeping scripts, signals, groups and instancing.",
        True,
    ),
    "node.instantiate": Operation(
        NodeInstantiate,
        "Instance a saved scene under a parent as one undoable action; its internals stay in the source scene.",
        True,
    ),
    "node.set_editable_children": Operation(
        SetEditableChildren,
        "Toggle editable children on a scene instance root so its internals accept property overrides.",
        True,
    ),
    "node.reparent": Operation(NodeReparent, "Move a node to another local parent.", True),
    "node.inspect": Operation(
        NodePath, "Read a node's class, transforms and resource information."
    ),
    "node.properties": Operation(
        NodePath,
        "List supported typed properties, including exported script variables, and current values.",
    ),
    "node.get_property": Operation(Property, "Read a supported property."),
    "node.set_property": Operation(
        SetProperty,
        "Set a typed, allowlisted property or exported script variable; undo restores it.",
        True,
    ),
    "node.set_transform": Operation(
        Transform, "Set local/world 3D transforms using degrees, as one undoable action.", True
    ),
    "editor.select": Operation(NodePath, "Select and inspect a node in the editor.", True),
    "editor.focus": Operation(
        NodePath, "Select a node and focus the 3D workspace. Does not move the editor camera.", True
    ),
    "editor.diagnostics": Operation(
        Empty, "Read recent GodotBridge command failures; this is not the engine debugger."
    ),
    "editor.undo": Operation(
        Empty, "Undo the most recent action in the active scene history.", True
    ),
    "editor.redo": Operation(Empty, "Redo the next action in the active scene history.", True),
    "3d.create_primitive": Operation(
        Primitive,
        "Create a mesh, material and optional static collision in one undoable action.",
        True,
        "godot_create_primitive",
    ),
    "3d.create_light": Operation(
        Light, "Create a configured 3D light in one undoable action.", True, "godot_create_light"
    ),
    "3d.create_camera": Operation(
        Camera, "Create a 3D camera looking at a local target.", True, "godot_create_camera"
    ),
    "editor.camera_info": Operation(
        Empty, "Read the public editor 3D viewport camera transform and lens."
    ),
    "viewport.capture": Operation(
        CaptureOutput,
        "Capture a PNG from the editor or an isolated geometry-only preview.",
        False,
        "godot_viewport_capture",
    ),
    "scene.snapshot": Operation(
        Snapshot,
        "Write scene.json, metadata.json and a real viewport.png when rendering is available.",
        False,
        backend="client",
    ),
    "project.validate": Operation(
        Empty,
        "Use the headless engine to load project scenes/resources and parse scripts.",
        backend="client",
    ),
    "project.import": Operation(
        Empty,
        "Import the project headlessly; requires its editor to be closed.",
        True,
        backend="client",
    ),
    "project.open": Operation(
        Empty, "Launch the configured project's Godot editor.", True, backend="client"
    ),
    "project.check_script": Operation(
        ScriptPath, "Parse a GDScript using --check-only; do not execute it.", backend="client"
    ),
    "game.run": Operation(
        GameRun,
        "Launch the main, current or specified saved scene through a managed process or editor.",
        True,
    ),
    "game.stop": Operation(
        GameMode, "Stop a bridge-managed game or editor-managed play session.", True
    ),
    "game.status": Operation(GameMode, "Read managed process state or editor play status."),
    "game.logs": Operation(
        GameMode,
        "Read bounded stdout/stderr for a bridge-managed game; editor debugger logs are not exposed.",
        backend="client",
    ),
    "game.screenshot": Operation(
        GameCapture,
        "Capture an actual managed game's viewport; requires a graphical managed run.",
        backend="client",
    ),
}


def schemas() -> dict[str, Any]:
    return {
        name: op.arguments.model_json_schema()
        for name, op in OPERATIONS.items()
        if op.backend == "editor"
    }
