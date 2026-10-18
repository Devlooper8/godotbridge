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
allowlisted node properties and exported script variables, type-checked, and
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
`key`. Properties with a custom getter are shown as `unread` and never read, freed objects
as `freed`, and self-referencing containers as `cycle`. A path that no longer resolves
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
In an inherited scene, nodes that come from the base scene (see `inherited` in
`node inspect`) accept property/transform edits and new children; delete, rename,
reparent and duplicate are rejected with `READ_ONLY_RESOURCE`. Nodes added in the
derived scene are ordinary nodes. Scene instances follow
the editor: the instance root accepts property/transform edits, rename, delete,
reparent and duplicate; its internal nodes are read-only for delete/rename/
reparent/duplicate, and accept property/transform edits and new children only
after `node editable-children` (shown as `instance.editable_children`).
`node instantiate` instances a saved scene (undoable); it rejects self or
recursive instancing and scenes with `@tool` scripts unless `--allow-tool-script`.
Only the instance root is owned by the edited scene, so saves never bake the
instance's internals. Nodes with a
non-`@tool` script are editable because the editor only holds a placeholder script
instance (no setters or lifecycle code run); nodes with a `@tool` script are rejected
with `READ_ONLY_RESOURCE` unless `--allow-tool-script` is passed. `node properties`
and `node get` also expose exported script variables (marked `"script": true`) and
`node set` validates their value against the declared type. Duplicate keeps scripts,
persistent signal connections, groups and instancing.

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
godotctl game logs --mode editor [--since CURSOR] [--limit 1000]
godotctl game screenshot --output game.png
godotctl game stop
godotctl game run --mode editor [--current]
godotctl game status --mode editor
godotctl game stop --mode editor
```

Managed mode is default: one supervised process per project, with a one-hour
default deadline. Main or explicit scene runs work offline; `--current` requires
the live plugin. Runs use saved files. Runtime capture uses native viewport
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
