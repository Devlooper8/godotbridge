---
name: godotbridge
description: Operates a Godot 4 project through GodotBridge, using the `godot_*` MCP tools or the `godotctl` CLI. Covers inspecting and editing scenes and nodes in the live editor (undoable), 3D helpers, screenshots and snapshots, running the game, runtime inspection, logs, breakpoints and stepping, and project validation. Use when a task involves a Godot 4 project with GodotBridge, `godotctl`, or `godot_*` tools.
---

# GodotBridge

Drives a live Godot 4.7+ editor (plus headless engine workers) through one operation registry, exposed as MCP tools and as `godotctl`.
The editor is authoritative: every mutation lands in the user's open editor. Targets 3D scenes; stable Godot 4.7+ only.

## 1. Choose the interface

Use the `godot_*` MCP tools when present (schemas, read-only/destructive hints, images returned inline). Otherwise `godotctl --json ...`.

- CLI global options go **before** the command: `godotctl --project P --json --timeout 30 --godot EXE --connect-wait 20 scene tree`. `--json` also works after the leaf command.
- Project: `--project` (directory or its `project.godot`), else `GODOTBRIDGE_PROJECT`, else cwd. Engine: `--godot`, `GODOT_EXECUTABLE`, or `godot` in `<project>/godotbridge.toml` (also `timeout`, `connect_wait`).
- MCP server is bound to one project at start: `godotbridge-mcp --project P [--godot E] [--timeout S] [--connect-wait S]`. It cannot be switched per call.
- `doctor` and `project install-plugin` are CLI-only. Results are `{"ok":true,"result":{...}}` or `{"ok":false,"error":{"code","message","details?"}}` (MCP: same JSON, errors set `isError`; `doctor` prints its checks without the envelope).
- Timeout is flag > toml `timeout` > default; the default is 15 s for the CLI (0.01-600) and 30 s for the MCP server. The MCP server reads the toml once, at its first call: restart it after editing the file.

**Name mapping.** Operations are `family.verb_noun`. MCP tool = `godot_` + name with `.` -> `_` (`scene.tree` -> `godot_scene_tree`, `node.set_property` -> `godot_node_set_property`).
CLI = `godotctl family verb-noun` (`scene.save_as` -> `scene save-as`, `project.check_script` -> `project check-script`, `debug.set_breakpoints` -> `debug set-breakpoints`). Exceptions:

| Operation | MCP tool | CLI |
| --- | --- | --- |
| `3d.create_primitive` | `godot_create_primitive` (`kind`: box/sphere/cylinder/plane) | `3d create-box`, `create-sphere`, `create-cylinder`, `create-plane` |
| `3d.create_light`, `3d.create_camera` | `godot_create_light`, `godot_create_camera` | `3d create-light`, `3d create-camera` |
| `node.create`, `node.delete` | rule | `node add`, `node remove` |
| `node.get_property`, `node.set_property` | rule | `node get`, `node set` |
| `node.set_transform` | rule (one call: `position`/`rotation`/`scale`/`world`/`translate`) | `node position`, `rotation`, `scale`, `translate` |
| `node.set_editable_children` | rule | `node editable-children` |
| `runtime.get_property`, `runtime.set_property` | rule | `runtime get`, `runtime set` |
| `editor.select` | rule | `node select` or `editor inspect` (same op; replaces the editor selection, scene unchanged; `editor focus` does too and switches to 3D) |
| `viewport.capture` | `godot_viewport_capture` | `editor screenshot` |

## 2. Preflight and startup

**Works without an editor** (needs only the Godot 4.7+ executable): `doctor`, `project info` (falls back to a headless engine, `connected: false`), `project validate`, `project check-script`, `project import` (editor must be closed), `project open` (launches the editor), `project install-plugin` (no engine; editor must be closed), managed `game run` (main scene or `--scene`; `--current` needs the editor) and managed `game status|logs|stop|screenshot`.
**Needs the live editor with the plugin enabled**: everything else (`scene.*`, `node.*`, `editor.*`, `3d.*`, `viewport.capture`, `scene snapshot`, `runtime.*`, `debug.*`, `game ... --mode editor`).

1. `godotctl --project P doctor --json`: checks `godot`, `project`, `plugin_installed`, `connection`, `capabilities`; exits 3 if any fails.
2. Plugin missing: with the editor closed, `godotctl project install-plugin` (`--replace` to upgrade). The user must enable **GodotBridge** in Project Settings > Plugins (the installer does not). `godotctl project open` starts the editor.
3. `godotctl editor status` (`godot_editor_status`): `connected`, `scene_path`, `playing`, `display_server` (`headless` means no screenshots). Then `scene current`.

**Not connected vs broken.** `EDITOR_DISCONNECTED` "no connection file exists" = editor closed or plugin disabled. "Cannot connect ... refused" = stale file from a killed editor: start the editor. These are not faults.
Broken: `AUTHENTICATION_FAILED` that survives a fresh read-only retry, `PROTOCOL_MISMATCH` (plugin differs from the installed package: `install-plugin --replace`), `FILE_ACCESS_DENIED` "Connection belongs to another project" (connection file recorded a different project path), or a plugin that never starts (see the GodotBridge dock: second editor on the project, ACL/permission failure).
An `UNSUPPORTED_OPERATION` "Unknown operation" for a listed operation means an outdated plugin; compare `doctor`'s `capabilities`.

**`--connect-wait SECONDS`** (CLI global option, `connect_wait` in `godotbridge.toml`, `--connect-wait` on `godotbridge-mcp`; default 0, max 600): one operation waits up to that long for the editor endpoint to become reachable. Only the connect/handshake phase is retried; the operation itself is sent once and never replayed. Use it right after `project open` or when the editor may still be starting. It does not enable the plugin and is no remedy for `TIMEOUT`; a call that cannot connect takes the full wait before failing, so keep it 0 for offline work.

**Recovers automatically:** every operation reconnects and re-reads credentials (restarted editor, rotated token); the plugin recreates a deleted connection file and retries listening; `runtime.*` waits up to ~5 s for the played game's autoload to be ready (`debug pause` waits for it too), so calls right after `game run --mode editor` work; the MCP server starts even if `project.godot` does not exist yet and reports `PROJECT_NOT_FOUND` per call.
**Not automatic:** replaying failed operations, launching the editor, enabling the plugin, restoring unsaved edits after an editor restart (re-check `scene list` / `scene current`).

## 3. Recipes (CLI; MCP tool after `#`)

### Inspect a scene
```sh
godotctl --json scene current                 # godot_scene_current (scene_path "" = unsaved)
godotctl --json scene list                    # godot_scene_list: open tabs
godotctl --json scene open res://scenes/main.tscn   # godot_scene_open (mutating: switches tab)
godotctl --json scene tree                    # godot_scene_tree: nodes + revision
godotctl --json node inspect Player/Camera    # godot_node_inspect
godotctl --json node properties Player        # godot_node_properties (exported script vars: "script": true)
godotctl --json node get Player visible       # godot_node_get_property
```
Paths are root-relative, `.` is the root; absolute, `..`, `%Unique` and `:` paths are rejected. Paths change after rename/reparent: re-read the tree.
Node entries carry `class`, typed transforms, `mesh`/`shape`/`camera`/`light`, `script`, `tool_script`, `groups`, `inherited`, `instance{is_instance_root,editable_children,inside_instance}`. Transforms and mesh/camera/light data are reported for Node3D only: read 2D/UI position, rotation and scale with `node get`. Compare `revision` across reads to notice other edits.

### Edit nodes and save
```sh
godotctl scene create res://scenes/arena.tscn --root Node3D   # godot_scene_create: refuses existing; root named after the file
godotctl node add --type MeshInstance3D --name Marker --parent .   # godot_node_create
godotctl node set Marker visible false        # godot_node_set_property
godotctl node position Marker 1 2 3 --world   # godot_node_set_transform; rotation = degrees in the node's rotation_order (YXZ default); translate adds a delta
godotctl node instantiate res://scenes/unit.tscn --parent . --name Hero   # godot_node_instantiate
godotctl node rename Marker Pin               # godot_node_rename; also node remove PATH, duplicate PATH [--name N],
godotctl node reparent Pin Hero [--no-keep-global]   #   godot_node_delete, godot_node_duplicate, godot_node_reparent
godotctl scene save                           # godot_scene_save (FILE_ACCESS_DENIED if the file changed on disk)
godotctl scene save-as res://scenes/copy.tscn # godot_scene_save_as (refuses existing); scene close = godot_scene_close (refuses unsaved)
godotctl editor undo                          # godot_editor_undo / godot_editor_redo
```
A position-only (or translate) transform edit leaves the basis untouched (shear and scale kept); a rotation or scale argument rebuilds it from euler angles plus scale and drops shear, and a `--world` rotation or scale under a rotated, non-uniformly scaled parent stays lossy (pass a typed Transform3D to keep a full basis). Reparent keeps the global pose by default: Node3D and Node2D keep the full global transform, a Control only its global position (a Control moved into a Container ends up where the Container lays it out); under a parent with a singular transform it is `INVALID_ARGUMENT` unless `--no-keep-global`; undo restores the exact previous pose. `node instantiate` reads the scene's own sub-resources fresh from disk on every call, but sub-resources of nested instanced scenes and shared external resources (`.tres`, textures, scripts) can still come from the engine's cache (reopen or reimport).
`scene.create` and `node.create` types are limited to: Node, Node3D, MeshInstance3D, StaticBody3D, RigidBody3D, CharacterBody3D, CollisionShape3D, Camera3D, DirectionalLight3D, OmniLight3D, SpotLight3D, WorldEnvironment, Marker3D, RayCast3D, Area3D.
Settable built-ins: visible, position, rotation (radians), rotation_degrees, scale, transform, top_level, cast_shadow, mesh, material_override, shape, disabled, light_color, light_energy, shadow_enabled, omni_range, spot_range, spot_angle, fov, near, far, current, projection, size, mass, gravity_scale, collision_layer, collision_mask, target_position, enabled, monitoring, monitorable; plus exported script variables. Values are type-checked and, for the built-ins and resource sub-properties as well as the script variables, checked against the inspector's range/enum/flags/layer hints (`INVALID_ARGUMENT` otherwise; `collision_layer`/`collision_mask` must be non-negative, all layers is `4294967295`, not `-1`). Anything else is `UNSUPPORTED_PROPERTY`.

`node set` takes JSON text (MCP: the JSON value). Values (typed values are objects with `type`; basis vectors are **columns**; integers are accepted for floats):

| Type | JSON |
| --- | --- |
| bool, number, null | `true`, `2.5`, `null` (null clears a resource property) |
| String | JSON-quoted: `'"boss"'` |
| Vector2 / Vector3 | `{"type":"Vector3","value":[1,2,3]}` |
| Color | `{"type":"Color","value":[0.2,0.6,0.9,1]}` (4 components) |
| NodePath | `{"type":"NodePath","value":"Parent/Child"}` (no leading `/`, `..`, `:`) |
| Basis | `{"type":"Basis","value":[[1,0,0],[0,1,0],[0,0,1]]}` |
| Transform3D | `{"type":"Transform3D","basis":{<Basis>},"origin":{<Vector3>}}` (keeps a full basis; non-uniform parent scale makes Euler edits lossy) |
| Resource | `{"type":"BoxMesh","properties":{"size":{"type":"Vector3","value":[2,3,4]}}}` |

Resource classes and properties: BoxMesh(size), SphereMesh(radius, height, radial_segments, rings), CylinderMesh(top_radius, bottom_radius, height, radial_segments), PlaneMesh(size), StandardMaterial3D(albedo_color, roughness, metallic), BoxShape3D(size), SphereShape3D(radius), CapsuleShape3D(radius, height). Assignment replaces the node's resource; existing resource paths are not loaded.
**Windows PowerShell 5.1 strips double quotes inside native arguments**: write `'{\"type\":\"Vector3\",\"value\":[0,2,0]}'`, use bash, or call the MCP tool. Negative coordinates work as positional args (`node position X -2 1 3`).

### 3D helpers (each one undo action)
```sh
godotctl 3d create-box --name Floor --size 14 0.25 14 --position 0 -0.125 0 --color 0.55 0.65 0.8 1 [--no-collision] [--parent .]
godotctl 3d create-sphere --name Ball --radius 1          # height is 2 x radius
godotctl 3d create-cylinder --name Column --radius 0.5 --height 3
godotctl 3d create-plane --name Ground --size 10 1 10     # X and Z only; 0.05-unit box collision
godotctl 3d create-light --type omni --name Lamp --energy 1.4 --position 0 5 0 --rotation -45 -30 0   # directional|omni|spot, degrees
godotctl 3d create-camera --name MainCamera --position 15 13 18 --target 0 0 0 --fov 70   # position != target
```
MCP: `godot_create_primitive {"name":"Floor","kind":"box","size":[14,0.25,14],"position":[0,-0.125,0],"collision":true}`; `godot_create_light`; `godot_create_camera` (also `current`, default true; CLI `--current/--no-current`). Collision adds `<name>/Body` and `<name>/Body/Collision`. `--color` takes four floats (RGBA).

### Visual verification
| Kind | Command / tool | Shows | Use for |
| --- | --- | --- | --- |
| Editor viewport | `editor screenshot --method editor` / `godot_viewport_capture {"method":"editor"}` | The user's 3D viewport as it is (grid, gizmos); switches the editor to the 3D workspace; camera cannot be moved | What the user sees now |
| Geometry preview | `editor screenshot --method preview --viewpoint top\|front\|side\|perspective\|custom [--position X Y Z --target X Y Z --distance D]`; `scene snapshot --output-dir snapshots/x` / `godot_scene_snapshot` | Isolated render of meshes and lights with standard lighting; no scripts, animation, particles, world environment | Layout and proportions from a chosen viewpoint; snapshot also writes `scene.json` + `metadata.json` |
| Runtime viewport | `game screenshot --output game.png` / `godot_game_screenshot` | Actual window of a graphical **managed** run, with runtime changes | What the game really renders |

`editor screenshot` defaults to `editor`, `scene snapshot` to `preview`, and **`godot_viewport_capture` defaults to `preview`**: always pass `method`. `width`/`height` 64-2048 (default 960x640). Preview framing: `perspective`, `top`, `front`, `side` look at `--target` from `--distance` (the last three orthographic); `--position` applies only to `custom`. `editor screenshot` and `scene snapshot` also take `--viewport N` (0-3, default 0; MCP `viewport`): the editor 3D viewport index, used only with `--method editor`.
Outputs are project-relative, confined to the project (no dot-directories), and **must not exist yet**; a snapshot directory must be new or empty. Use a fresh name per capture. Results: `artifact_path`, `capture_method` (`editor_viewport`, `geometry_preview`, `runtime_viewport`), `warnings`. MCP also returns the PNG; the CLI never embeds image data, so read the PNG file.
Headless editor or headless managed run: `CAPTURE_UNAVAILABLE`; `scene snapshot` returns `status: partial` (exit 0) with `scene.json` and `metadata.json` (records the error) but no PNG. Always check `status`. `editor camera-info` is read-only; `editor focus` replaces the editor selection and switches to 3D without moving the camera.

### Run the game
| | Managed (default) | Editor (`--mode editor`) |
| --- | --- | --- |
| Start | `game run [--scene res://x.tscn \| --current] [--headless] [--max-seconds N]` | `game run --mode editor [--scene X \| --current]` (no `--headless`) |
| Editor needed | No (except `--current`) | Yes |
| Behavior | Supervised process on **saved** files, one per project (second run: `EDITOR_BUSY`), 3600 s default limit, isolated `user://` | The editor's normal Play |
| Status / stop | `game status`, `game stop` | `game status --mode editor`, `game stop --mode editor` |
| Logs | `game logs`: bounded stdout/stderr text with `errors`, `warnings` | `game logs --mode editor [--since N] [--limit N]`: structured entries |
| Screenshot | `game screenshot` (graphical only) | None |
| `runtime.*`, `debug.*` | No | Yes |

MCP: `godot_game_run {"mode":"editor","scene":"res://..."}`, `godot_game_logs {"mode":"editor","since":N}`, same pattern for status/stop.
`--current` needs a saved open scene: an unsaved one (for example after `scene open --inherited`; save it first with `scene save-as`) is `SCENE_NOT_FOUND` in both modes, no open scene is `SCENE_NOT_OPEN`. A rejected `--current` never stops a game already running in editor mode and never falls back to the main scene.
Editor logs: entries have `seq`, `run`, `kind` (`log`, `run_started`, `run_stopped`), `level` (`info`, `warning`, `error`, `stderr`), `message`, `time`, and `file`/`line`/`function`/`code` for errors. Call once without `since`, then pass the result's `next` as `since`. `missed` > 0: the 5,000-entry ring evicted unread entries; `dropped` > 0: the game's queue overflowed; changed `epoch`: plugin restarted, drop `since`. Only games started while the plugin was enabled stream logs; a game that dies before its first frame sends nothing (use managed logs or the editor's Output panel).
`since` with managed logs is `INVALID_ARGUMENT`. Managed `game logs`/`game stop` with no session: `UNSUPPORTED_OPERATION`. Stuck managed game: `game status`, `game stop`; remove `.godot/godotbridge/game/run.lock` only after confirming the game process ended and with the user's consent.

### Runtime inspection (editor-played game)
```sh
godotctl game run --mode editor --scene res://scenes/main.tscn
godotctl --json debug status                  # godot_debug_status: running, breaked, sessions, dap_port
godotctl --json runtime tree --path Player --max-nodes 1000   # godot_runtime_tree (1-5000, `truncated`)
godotctl --json runtime inspect Player/Camera # godot_runtime_inspect; also runtime properties|get
godotctl runtime set Player speed 12.5        # godot_runtime_set_property: runtime only, never saved
```
Paths are relative to the running scene root (autoloads are not addressable). Same allowlist, value checks (type, range/enum/flags/layers) and encoding as `node.*`. Works while stopped at a breakpoint. A reply takes up to 5 s, else `TIMEOUT`; no editor-played game: `GAME_NOT_RUNNING`. To keep a change, make it with `node set` in the edited scene.

### Debug
```sh
godotctl debug set-breakpoints res://scripts/player.gd 12 30   # godot_debug_set_breakpoints {"path","lines":[12,30]}; replaces that script's set, [] clears
godotctl game run --mode editor --scene res://scenes/main.tscn
godotctl --json debug status                  # poll until "breaked": true (there is no blocking wait)
godotctl --json debug stack                   # godot_debug_stack: frames[] (index 0 innermost: file, line, function)
godotctl --json debug variables --frame 0 --scope locals      # godot_debug_variables; scope locals|members|globals
godotctl --json debug variables --path 'party[0].stats' --depth 1 --offset 0 --limit 100   # MCP path: ["party",{"index":0},{"property":"stats"}]
godotctl debug step --kind over               # godot_debug_step: over|in|out; godot_debug_continue; godot_debug_pause
godotctl debug clear-breakpoints [res://scripts/player.gd]    # godot_debug_clear_breakpoints; godot_debug_breakpoints lists bridge/editor/all
godotctl game stop --mode editor
```
- Breakpoints go on executable lines (1-based) of existing `.gd` files; they persist for the running game and every later run: **clear them when done**.
- `stack`, `variables`, `step`, `continue` need a game stopped at a breakpoint (`NOT_BREAKED`). `step`/`continue`/`pause` wait up to 3 s and return `breaked`, `running`, `changed`; `changed: false` means no reaction yet, so check `debug status`.
- `debug pause` stops between frames: the stack is empty until `debug step --kind in`.
- `--path`: variable name, then `[n]` (array element, or n-th dictionary entry in insertion order) or `.property`. `limit` <= 200, `depth` 0-2. Values show `type`, `expandable`, `count`, `value`; markers `unread` (custom getter, or script source not found, for example an inner class whose owning script is not among the loaded scripts: never read; each unread entry has a `reason`), `hooks` (on an object summary: its script defines `_get`/`_get_property_list`/`_validate_property`, which are never called, so the properties they would add are not listed; `unverified` = not GDScript), `freed`, `cycle`, `truncated`, `budget_exhausted`, `supported: false` + `repr`.
- A path that no longer resolves is `VARIABLE_NOT_FOUND` (the game moved on): re-read from the parent. There is no expression evaluation.

### Validate a project
```sh
godotctl scene save                           # validation reads saved files, not editor state
godotctl --timeout 120 project validate       # godot_project_validate
godotctl project check-script res://scripts/player.gd   # godot_project_check_script (parse only)
godotctl --timeout 120 project import         # godot_project_import: editor must be closed (EDITOR_BUSY otherwise)
```
Failure is `TRANSACTION_FAILED` (exit 1) with `details` (`errors`, `warnings`, `log`, `validation`); Godot may exit 0 on errors, the bridge still fails. The root-certificate-store line is an environment warning. Validation instantiates scenes off-tree (`_init` runs, `_ready` does not): trusted projects only. It does not import resources (close the editor, `project import`) or compile C#.

## 4. Safety

- Mutations hit the live editor immediately and are visible to the user; `scene save` is separate. Read-only: inspect/get/list/tree/properties/status/diagnostics/camera-info/captures/snapshot/validate/check-script/`runtime` reads/`debug` reads. Everything else mutates (including `editor select|focus`, `game run|stop`, `project open|import`, `debug set|clear-breakpoints|step|continue|pause`).
- Never replay a mutation after `TIMEOUT`, `INTERNAL_ERROR` or a dropped connection: its outcome is unknown (the editor itself answers `TIMEOUT` when one operation runs over 120 s and `INTERNAL_ERROR` "failed inside the editor" on a handler script error; an abandoned operation may still finish its side effects). Inspect first (`node inspect`, `scene tree` revision), undo if needed. The client never replays; do not either. (A repeated `node add` fails with a sibling-name `INVALID_ARGUMENT`, which means the first one landed.)
- Each helper or node call is one undo action; sequences are not transactions. Scene create/save/save-as are filesystem operations and not undoable. `editor undo|redo` act on the active scene's history **including the user's own edits**: inspect before undoing.
- Protected nodes: `@tool` scripts run inside the editor, so mutating them needs `--allow-tool-script` / `allow_tool_script` and the user's consent; also applies to instancing scenes with `@tool` scripts, including scripts embedded in scene files, nested scenes and embedded Resource scripts (the screen is coarse and fails closed: a scene with a GDScript `sub_resource` and "@tool" anywhere needs the opt-in). Non-`@tool` scripted nodes are editable (exported vars appear in `node properties`).
- Instances: only the instance root accepts rename/delete/reparent/duplicate; internals accept property, transform and new children only after `node editable-children`. Inherited scenes (`scene open --inherited`, then `scene save-as`): base nodes accept overrides and new children, but not delete/rename/reparent/duplicate. Violations are `READ_ONLY_RESOURCE`; edit the source scene. Duplicating an instance with editable children or added children is `UNSUPPORTED_OPERATION`.
- Paths: scenes are `res://` `.tscn` paths without traversal, dot-directories or symlinks; scene create/save-as, screenshots and snapshots refuse existing destinations: pick new names.
- Do not edit a `.tscn` on disk while the editor has it open (the next `scene save` is refused). Do not run a second editor on the project.
- Never read, print or copy `.godot/godotbridge/connection.json` (it holds the session token), and keep tokens out of MCP config, logs and commits.
- Validation and any game run execute project code: only for trusted projects. `project import` and `install-plugin` refuse while the editor is connected; commit local plugin changes before `install-plugin --replace`.

## 5. Errors

Exit codes: 0 ok (including partial snapshots), 1 operation/internal failure, 2 `INVALID_*`/`UNSUPPORTED_*`, 3 `EDITOR_DISCONNECTED`/`GODOT_NOT_FOUND`/`PROJECT_NOT_FOUND` (and failing `doctor`), 4 `TIMEOUT`, 5 `AUTHENTICATION_FAILED`.

| Code | Meaning | Next |
| --- | --- | --- |
| `EDITOR_DISCONNECTED` | No/stale/invalid connection file, or refused | Start the editor, enable the plugin, `doctor`; `--connect-wait` if starting |
| `AUTHENTICATION_FAILED` | Token rotated mid-connect or wrong | Retry a read-only call once; never paste the token |
| `PROTOCOL_MISMATCH` | Plugin and client protocol differ | `install-plugin --replace` with the editor closed |
| `INVALID_ARGUMENT` | Schema/value error, bad name, sibling collision, malformed JSON for `node set`, root delete/rename | Fix arguments; do not resend unchanged |
| `INVALID_NODE_PATH` | Absolute, `..`, `%Unique` or `:` path | Use a root-relative path |
| `NODE_NOT_FOUND` | No node at that path | `scene tree`; paths change on rename/reparent |
| `SCENE_NOT_FOUND` | Scene missing/unloadable, no main scene, `game run --current` on an unsaved scene, or the game has no running scene yet | Check the path; `--scene`/`--current`; save an unsaved scene first (`scene save-as`); retry reads shortly after play starts |
| `SCENE_NOT_OPEN` | No edited scene | `scene open` or `scene create` |
| `RESOURCE_NOT_FOUND` | `check-script` target missing | Fix the `res://` `.gd` path |
| `UNSUPPORTED_NODE_TYPE` | Transform on a non-Node3D | Use a Node3D |
| `UNSUPPORTED_PROPERTY` | Not allowlisted nor an exported script var | `node properties` for what is available |
| `UNSUPPORTED_OPERATION` | Capability limit (tree > 10,000 nodes, `--headless` with `--mode editor`, no managed session, `unread` variable by path, instance duplicate with overrides) | Use the supported alternative |
| `READ_ONLY_RESOURCE` | `@tool`, inherited or instance-internal node | See Safety; reopen the scene if its base changed on disk |
| `FILE_ACCESS_DENIED` | Bad/confined path, destination exists, scene changed on disk, plugin dir exists | New path; reload the scene in the editor before saving |
| `PROJECT_NOT_FOUND` | No `project.godot` at the path | `--project` / `GODOTBRIDGE_PROJECT` |
| `GODOT_NOT_FOUND` | No Godot 4.7+ stable executable | `--godot` / `GODOT_EXECUTABLE`; ask the user to install it |
| `TIMEOUT` | Client deadline hit, or the editor gave up on one operation after 120 s; a mutation may have applied; runtime replies take > 5 s | Outcome unknown: inspect before retrying; raise `--timeout`; game frozen or no autoload |
| `EDITOR_BUSY` | Import/install with editor open, unsaved close, managed game already running, capture pending, queue full, scene switch unfinished | Resolve the cause, inspect state, then retry |
| `TRANSACTION_FAILED` | Headless worker failed (validate, import, check-script, managed start) | Read `details.errors` / `details.log`; fix the project |
| `CAPTURE_UNAVAILABLE` | No renderer (headless) or not a graphical managed game | Use a graphical editor/run; rely on `scene.json` |
| `GAME_NOT_RUNNING` | No editor-played game | `game run --mode editor` |
| `NOT_BREAKED` | Game not stopped at a breakpoint | Set breakpoints, run, poll `debug status` |
| `VARIABLE_NOT_FOUND` | Variable path no longer resolves | Re-read the parent level |
| `INTERNAL_ERROR` | Unexpected failure, or a handler script error inside the editor ("failed inside the editor") | Outcome unknown: inspect state, see the editor log, report; do not loop |

`editor diagnostics` (`godot_editor_diagnostics`) lists the last bridge command failures, not engine errors.

## 6. Limits

- `scene tree` 10,000 nodes; preview capture 10,000; `runtime tree` 5,000 (default 1,000). Eight clients with one pending request each (so at most eight queued), one active operation per editor, answered `TIMEOUT` after 120 s.
- Timeouts: runtime replies 5 s; step/continue/pause 3 s; managed game 3600 s default (`--max-seconds` <= 86400). Editor log ring 5,000 entries, `limit` 1-5,000 (default 1,000); managed logs are a bounded recent tail.
- Breakpoints: <= 100 lines per call, 500 registered. Images 64-2048 px.
- Not available: expression evaluation, method calls, arbitrary file writes, shell, C# builds, runtime inspection or debugging of managed runs, runtime screenshots of editor-played games, moving the editor camera. Godot's own debug-adapter port (`dap_port`) is unauthenticated and separate: do not use it.
- Headless editor (`godot --headless --editor --path P`) supports scene editing; images and `editor camera-info` fail. Editor play and its runtime/debug features were verified in a graphical editor (a headless editor was also observed to run editor-mode games, report a debugger session and serve `runtime.tree`). Projects with custom main loops need editor play mode.
