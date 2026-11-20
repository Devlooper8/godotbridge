# CLI reference

Global options: `--project PATH`, `--godot EXECUTABLE_OR_APP`, `--timeout SECONDS`,
`--connect-wait SECONDS`, `--json`. Put them before the command family. `--json` also
works after every leaf command. `--connect-wait` (0-600, default 0; `connect_wait` in
`godotbridge.toml`) is how long one operation may wait for the editor endpoint to become
reachable, for example while the editor is still starting: only the connection is retried,
the operation itself is sent once. Human output uses Rich to display the same structured data. Commands
are noninteractive; `--help` is the source of truth for argument syntax.

Success: `{"ok":true,"result":{...}}`. Error:
`{"ok":false,"error":{"code":"...","message":"..."}}`. `doctor` returns its
individual checks directly. Snapshot metadata can succeed with `status: partial`.

Exit codes: 0 success (including partial snapshots); 1 operation/internal failure;
2 invalid/unsupported arguments; 3 missing project/engine/editor; 4 timeout;
5 authentication failure. Inspect state before retrying a timed-out mutation (`TIMEOUT`
can also come from the editor itself when one operation runs longer than 120 s).

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
godotctl editor inspect Object   # replaces the editor selection; does not change the scene
godotctl editor focus Object     # same, and switches to the 3D workspace
godotctl editor camera-info
godotctl editor undo
godotctl editor redo
godotctl editor diagnostics
```

`project info` uses live ProjectSettings, with a headless-engine fallback offline. `doctor` reports executable/project
checks even if disconnected. Import uses `--headless --editor --import` and
requires a closed editor. Validation loads saved resources/scenes without another
editor. Script parsing uses `--check-only --script`. Diagnostics are bridge-command
failures, not a complete debugger stream. `editor inspect` and `node select` (both are
`editor.select`) and `editor focus` replace the editor selection, and the first two also open
the node in the Inspector. They are state-changing editor operations despite the
read-sounding name, but they do not modify the scene; `node inspect` is the read-only
counterpart. `editor focus` additionally switches the editor to the 3D workspace; it does
not move the editor camera.

## Editor-play runtime inspection

```text
godotctl game run --mode editor --scene res://scenes/main.tscn
godotctl debug status
godotctl runtime tree [--path Player] [--max-nodes 1000]
godotctl runtime inspect Player/Camera
godotctl runtime properties Player
godotctl runtime get Player speed
godotctl runtime set Player speed 12.5
godotctl runtime set Player position '{"type":"Vector3","value":[0,2,0]}'
```

These read and change the **live nodes of a game started with `game run --mode
editor`** (or the editor's Play button); managed games do not have them. Paths are
relative to the running scene's root (`.`), with the same rules as editor node
paths, so autoloads are not addressable. `tree` returns the same node fields as
the scene tree plus `child_count`, is capped (`--max-nodes` 1-5000; larger replies
overflowed the debugger channel) and reports `truncated`. `set` only accepts the
allowlisted node properties and exported script variables, checked for type and against
the inspector's range, enum, flags and layer hints (as `node set` does), and
changes the running game only: nothing is saved to the scene. `debug status`
reports `running`, `breaked` (stopped at a breakpoint), per-session state and the
`dap_port` Godot's debug adapter uses. Requests are answered by the game within five
seconds (`TIMEOUT` otherwise) and also work while the game is stopped at a
breakpoint. With no editor-played game they fail with `GAME_NOT_RUNNING`. Requires
the `GodotBridgeRuntime` autoload, which the plugin adds. If several instances are
run at once, the first active session answers.

## Editor-play debugging

```text
godotctl debug set-breakpoints res://scripts/player.gd 12 30
godotctl debug breakpoints
godotctl game run --mode editor --scene res://scenes/main.tscn
godotctl debug status
godotctl debug stack
godotctl debug variables [--frame 0] [--scope locals|members|globals]
godotctl debug variables --path 'party[0].stats' [--offset 0] [--limit 100] [--depth 1]
godotctl debug step [--kind over|in|out]
godotctl debug continue
godotctl debug pause
godotctl debug clear-breakpoints [res://scripts/player.gd]
```

Breakpoints are kept by the bridge, replace the script's previous bridge breakpoints
and apply to the running game and every later run until cleared. `debug breakpoints`
also lists breakpoints the script editor reported. `stack`, `variables`, `step` and
`continue` need a game stopped at a breakpoint (`NOT_BREAKED` otherwise); `status` shows
`breaked`. Values are typed as in [protocol](protocol.md); unsupported types carry a
`repr`. `pause` stops between frames, so `stack` is empty until `step --kind in`.
`--path` drills into a variable with a dotted/bracket syntax: the variable name, then
`[n]` for an array element (or the n-th dictionary entry in insertion order) and `.name`
for an object property, e.g. `inventory[2].stats[0]`. Children are paged
(`--offset`/`--limit`, at most 200) and `--depth 1|2` inlines children. Each value shows
`type`, `count`, `expandable`, and `value` for scalars; dictionary children also show their
`key`. Properties with a custom getter, or whose script source cannot be found, are shown as
`unread` (with a `reason`) and never read, freed objects as `freed`, and self-referencing
containers as `cycle`. An object whose script defines `_get`, `_get_property_list` or
`_validate_property` carries `hooks` and is listed without calling them, so properties those
hooks would add are not shown. A path that no longer resolves
fails with `VARIABLE_NOT_FOUND`. See [protocol](protocol.md#browsing-variables).
There is deliberately no expression evaluation. Execution control relies on engine
internals that Godot does not document; the tests fail if an update breaks them.

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
godotctl scene open res://scenes/base.tscn --inherited   # new unsaved inherited scene
godotctl node instantiate res://scenes/unit.tscn [--parent .] [--name Hero]
godotctl node editable-children Hero [--disable]
godotctl node remove Object
godotctl node duplicate Object [--name Copy]
godotctl node rename Object NewName
godotctl node reparent Object NewParent [--no-keep-global]   # keeps the global pose, see below
godotctl node inspect Object
godotctl node select Object   # replaces the editor selection; does not change the scene
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
In an inherited scene, nodes that come from the base scene (see `inherited` in
`node inspect`) accept property/transform edits and new children; delete, rename,
reparent and duplicate are rejected with `READ_ONLY_RESOURCE`. Nodes added in the
derived scene are ordinary nodes. Scene instances follow
the editor: the instance root accepts property/transform edits, rename, delete,
reparent and duplicate; its internal nodes are read-only for delete/rename/
reparent/duplicate, and accept property/transform edits and new children only
after `node editable-children` (shown as `instance.editable_children`).
`node instantiate` instances a saved scene (undoable); it rejects self or
recursive instancing and scenes with `@tool` scripts unless `--allow-tool-script`; that
covers scripts embedded in scene files, in nested scenes and in embedded Resource scripts.
The scene's own sub-resources are read fresh from disk on every call; those of nested
instanced scenes and shared external resources come from the engine's cache.
Only the instance root is owned by the edited scene, so saves never bake the
instance's internals. Nodes with a
non-`@tool` script are editable because the editor only holds a placeholder script
instance (no setters or lifecycle code run); nodes with a `@tool` script are rejected
with `READ_ONLY_RESOURCE` unless `--allow-tool-script` is passed. `node properties` and `node get` also expose exported script variables (marked
`"script": true`). `node set` validates a value against the declared type and the
inspector's range, enum, flags and layer hints, for exported variables, allowlisted
properties and resource sub-properties alike; a negative collision mask or an out-of-enum
`projection` is `INVALID_ARGUMENT`, and a mask of all layers is `4294967295`, not `-1`.
Duplicate keeps scripts, persistent signal connections, groups and instancing.

Node paths are root-relative; `.` is root. Absolute paths and `%UniqueName` paths
are unsupported. Reparent keeps the global pose by default: with `--keep-global`, Node3D
and Node2D keep their full global transform, a Control keeps only its global position
(rotation and scale stay as they were), and a Control moved into a Container ends up
where the Container lays it out, as in the editor. A Node3D, Node2D or Control reparented
under a parent whose transform is singular is rejected unless `--no-keep-global`. Undo
restores the exact previous pose, including a Control that a Container re-laid-out
(anchors, offsets, rotation, scale). Transforms are local unless `--world` is used.
Euler rotation arguments are degrees, interpreted in the node's `rotation_order` (YXZ by
default). A position-only (or `translate`) edit, local or `--world`, leaves the basis
untouched, so shear and scale are preserved. Rotation and scale arguments are read from
and written to euler angles plus scale, so a shear is dropped when either is given, and a
`--world` rotation or scale under a rotated, non-uniformly scaled parent stays lossy; use
a typed Transform3D to preserve a full basis.

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
degree rotation. Cameras support position/target/FOV and `--current/--no-current`
(default `--current`: the camera becomes the scene's current camera). Generic resource properties
also construct BoxShape3D, SphereShape3D and CapsuleShape3D.

## Visual feedback

```text
godotctl editor screenshot --output editor.png
godotctl editor screenshot --method preview --viewpoint top --output top.png
godotctl editor screenshot --method preview --viewpoint custom --position 10 4 6 --target 0 1 0 --output custom.png
godotctl scene snapshot --output-dir snapshots/first
```

In the CLI, `editor screenshot` defaults to `--method editor` and `scene snapshot` to
`preview`; the `viewport.capture` operation and the `godot_viewport_capture` MCP tool
default `method` to `preview` (pass `editor` for the editor viewport). All accept
width/height (64–2048) and, for preview, viewpoint (perspective/top/front/side/custom),
distance, position and target; `position` is used only by `--viewpoint custom`, the
other viewpoints derive the camera from target and distance. Editor capture uses its
existing camera and ignores preview framing. `editor screenshot` and `scene snapshot` also
take `--viewport N` (0-3, default 0): the editor 3D viewport index, used only with
`--method editor`. Output paths are project-relative and project-confined. Choose new
destinations; no overwrite flag is provided. CLI JSON never embeds image base64.

## Game execution

```text
godotctl game run [--scene res://scenes/main.tscn | --current] [--headless] [--max-seconds 60]
godotctl game status
godotctl game logs
godotctl game logs --mode editor [--since CURSOR] [--limit 1000]
godotctl game screenshot --output game.png
godotctl game stop
godotctl game run --mode editor [--current]
godotctl game status --mode editor
godotctl game stop --mode editor
```

Managed mode is default: one supervised process per project, with a one-hour
default deadline. Main or explicit scene runs work offline; `--current` requires
the live plugin and a saved open scene. Runs use saved files. An unsaved scene (for
example one opened with `scene open --inherited`) is rejected with `SCENE_NOT_FOUND` in
both modes: save it first with `scene save-as`. `SCENE_NOT_OPEN` means no scene is open.
A rejected `--current` never stops a game that is already running in editor mode and never
falls back to the main scene. Runtime capture uses native viewport
dimensions and requires graphical managed mode. Editor mode has no runtime
screenshot and uses Godot's normal play configuration.

`game logs` means two different things. Managed mode returns the supervised
process's bounded stdout/stderr text. `--mode editor` returns structured entries
from Godot's debugger channel for a game started with `game run --mode editor`
(or the editor's Play button): `seq`, `run`, `kind` (`log`, `run_started`,
`run_stopped`), `level` (`info`, `warning`, `error`, `stderr`), `message`,
`time` and, for errors and warnings, `file`, `line`, `function`, `code`. Pass the
previous result's `next` as `--since` to read only newer entries. `missed` counts
entries evicted from the editor's 5,000-entry ring before they were read,
`dropped` counts entries the game itself discarded (its queue overflowed), and
`epoch` changes if the plugin restarts (cursors then restart from 1). The stream
is produced by the bridge's `GodotBridgeRuntime` autoload (see
[architecture](architecture.md)); it needs the plugin enabled when the game starts.
