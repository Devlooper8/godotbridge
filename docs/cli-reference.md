# CLI reference

Global options: `--project PATH`, `--godot EXECUTABLE_OR_APP`, `--timeout SECONDS`,
`--json`. Put them before the command family. `--json` also works after every leaf
command. Human output uses Rich to display the same structured data. Commands
are noninteractive; `--help` is the source of truth for argument syntax.

Success: `{"ok":true,"result":{...}}`. Error:
`{"ok":false,"error":{"code":"...","message":"..."}}`. `doctor` returns its
individual checks directly. Snapshot metadata can succeed with `status: partial`.

Exit codes: 0 success (including partial snapshots); 1 operation/internal failure;
2 invalid/unsupported arguments; 3 missing project/engine/editor; 4 timeout;
5 authentication failure. Inspect state before retrying a timed-out mutation.

## Project and editor

```text
godotctl doctor
godotctl project install-plugin [--replace]
godotctl project info
godotctl project open
godotctl project import
godotctl project validate
godotctl project check-script res://scripts/player.gd
godotctl editor status
godotctl editor inspect Object
godotctl editor focus Object
godotctl editor camera-info
godotctl editor undo
godotctl editor redo
godotctl editor diagnostics
```

`project info` uses live ProjectSettings, with a headless-engine fallback offline. `doctor` reports executable/project
checks even if disconnected. Import uses `--headless --editor --import` and
requires a closed editor. Validation loads saved resources/scenes without another
editor. Script parsing uses `--check-only --script`. `focus` selects a node and
switches to 3D; it does not move the editor camera. Diagnostics are bridge-command
failures, not a complete debugger stream.

## Scenes and nodes

```text
godotctl scene list
godotctl scene current
godotctl scene open res://scenes/main.tscn
godotctl scene create res://scenes/test.tscn --root Node3D
godotctl scene tree --json
godotctl scene save
godotctl scene save-as res://scenes/copy.tscn
godotctl scene close
godotctl node add --type Node3D --name Object --parent .
godotctl node remove Object
godotctl node duplicate Object [--name Copy]
godotctl node rename Object NewName
godotctl node reparent Object NewParent [--no-keep-global]
godotctl node inspect Object
godotctl node select Object
godotctl node properties Object
godotctl node get Object visible
godotctl node set Object visible true
godotctl node position Object 1 2 3 [--world]
godotctl node rotation Object 0 90 0 [--world]
godotctl node scale Object 2 2 2 [--world]
godotctl node translate Object 1 0 0 [--world]
```

`list` lists open editor tabs. `close` refuses unsaved scenes. Create/save-as
refuse existing destinations. Save detects external changes since opening/saving.
Root deletion/duplication, traversal and sibling collisions are rejected.
Instance/inherited/scripted-node mutations are read-only in 0.1. Duplicate copies
local hierarchy/properties but omits signal connections and group memberships.

Node paths are root-relative; `.` is root. Absolute paths and `%UniqueName` paths
are unsupported. Reparent preserves world transforms by default. Transforms are
local unless `--world` is used. Euler rotation arguments are degrees, converted
to radians before constructing Godot's YXZ basis. Nonuniform parent scaling/shear
can make Euler decomposition lossy; use a typed Transform3D to preserve a full basis.

Properties accept JSON primitives or [tagged values](protocol.md). String values
must be JSON-quoted. For complex values use Python/MCP to avoid shell escaping:

```python
from godotbridge.client import Client
from godotbridge.config import Config
client = Client(Config.load("/work/game"))
client.call("node.set_property", path="Object", property="position",
            value={"type": "Vector3", "value": [1, 2, 3]})
```

## 3D helpers

```text
godotctl 3d create-box --name Floor --size 10 0.2 10
godotctl 3d create-sphere --name Ball --radius 1
godotctl 3d create-cylinder --name Column --radius 0.5 --height 3
godotctl 3d create-plane --name Ground --size 10 1 10
godotctl 3d create-light --type omni --name Lamp
godotctl 3d create-camera --name MainCamera --position 10 8 12 --target 0 0 0
```

Primitives accept `--parent`, `--position X Y Z`, `--color R G B A`,
`--no-collision`, and size/radius/height as applicable. Sphere height is twice its
radius. Plane size uses X/Z, with 0.05-unit box collision. Cylinder uses
CylinderShape3D. Lights support directional/omni/spot, color, energy, position and
degree rotation. Cameras support position/target/FOV. Generic resource properties
also construct BoxShape3D, SphereShape3D and CapsuleShape3D.

## Visual feedback

```text
godotctl editor screenshot --output editor.png
godotctl editor screenshot --method preview --viewpoint top --output top.png
godotctl editor screenshot --method preview --viewpoint custom --position 10 4 6 --target 0 1 0 --output custom.png
godotctl scene snapshot --output-dir snapshots/first
```

Screenshot defaults to editor capture; snapshot defaults to preview. Both accept
width/height (64–2048), viewpoint (perspective/top/front/side/custom), distance,
position and target. Editor capture uses its existing camera and ignores preview
framing. Output paths are project-relative and project-confined. Choose new
destinations; no overwrite flag is provided. CLI JSON never embeds image base64.

## Game execution

```text
godotctl game run [--scene res://scenes/main.tscn | --current] [--headless] [--max-seconds 60]
godotctl game status
godotctl game logs
godotctl game screenshot --output game.png
godotctl game stop
godotctl game run --mode editor [--current]
godotctl game status --mode editor
godotctl game stop --mode editor
```

Managed mode is default: one supervised process per project, with a one-hour
default deadline. Main or explicit scene runs work offline; `--current` requires
the live plugin. Runs use saved files. Runtime capture uses native viewport
dimensions and requires graphical managed mode. Editor mode has no captured
stdout or runtime screenshot and uses Godot's normal play configuration.
