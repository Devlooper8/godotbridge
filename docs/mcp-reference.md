# MCP server

GodotBridge uses the official Python MCP SDK **2.x** with local **stdio** transport.
No HTTP or remote transport is exposed. Stdout is reserved for MCP messages;
diagnostics use stderr. Start with `godotbridge-mcp --project /absolute/project`.
Optional `--godot` and `--timeout` configure the same shared client backend.

Example client configuration (adjust to your client's configuration format):

```json
{
  "mcpServers": {
    "godotbridge": {
      "command": "C:\\work\\godotbridge\\.venv\\Scripts\\godotbridge-mcp.exe",
      "args": ["--project", "D:\\Games\\Arena", "--timeout", "30"]
    }
  }
}
```

On Linux/macOS use `/path/to/.venv/bin/godotbridge-mcp`. The client process must
run as the same user as the editor so it can read private session credentials.
Do not put the session token in client configuration: it rotates on plugin restart.

## Tools

Names generally map from protocol methods by replacing `.` with `_` and adding
`godot_`. The three helper tools use explicit names.

| Family | Tools |
| --- | --- |
| Project | `godot_project_info`, `godot_project_open`, `godot_project_import`, `godot_project_validate`, `godot_project_check_script` |
| Scenes | `godot_scene_list`, `godot_scene_current`, `godot_scene_open`, `godot_scene_create`, `godot_scene_tree`, `godot_scene_save`, `godot_scene_save_as`, `godot_scene_close`, `godot_scene_snapshot` |
| Nodes | `godot_node_create`, `godot_node_delete`, `godot_node_duplicate`, `godot_node_rename`, `godot_node_reparent`, `godot_node_instantiate`, `godot_node_set_editable_children`, `godot_node_inspect`, `godot_node_properties`, `godot_node_get_property`, `godot_node_set_property`, `godot_node_set_transform` |
| Editor | `godot_editor_status`, `godot_editor_select`, `godot_editor_focus`, `godot_editor_undo`, `godot_editor_redo`, `godot_editor_camera_info`, `godot_editor_diagnostics` |
| 3D | `godot_create_primitive`, `godot_create_light`, `godot_create_camera` |
| Images | `godot_viewport_capture` |
| Runtime (editor play) | `godot_runtime_tree`, `godot_runtime_inspect`, `godot_runtime_properties`, `godot_runtime_get_property`, `godot_runtime_set_property`, `godot_debug_status` |
| Game | `godot_game_run`, `godot_game_stop`, `godot_game_status`, `godot_game_logs`, `godot_game_screenshot` |

`godot_game_logs` with `mode: "managed"` returns the supervised process's stdout/stderr
text; with `mode: "editor"` it returns structured debugger entries for the editor-played
game and accepts `since` (previous `next`) and `limit`.

The `godot_runtime_*` tools act on the live nodes of a game started with
`godot_game_run` and `mode: "editor"`; `godot_runtime_set_property` changes the running
game only. They fail with `GAME_NOT_RUNNING` when no editor-played game exists.

Every tool has a description, explicit JSON input schema, and read-only/mutating
annotations. Read-only annotations mean no scene mutation; capture tools still
create image artifacts. Project validation can execute trusted scene `_init`
code while instantiating smoke tests. Unknown fields are rejected.

Example `godot_node_set_transform` arguments:

```json
{"path":"ObstacleA","position":[1,2,3],"rotation":[0,90,0],"world":false}
```

Example `godot_create_primitive`:

```json
{"name":"Floor","kind":"box","size":[14,0.25,14],"position":[0,-0.125,0],"collision":true}
```

## Results and errors

Results include both JSON text content and MCP structured content:

```json
{"ok":true,"result":{"node_path":"Floor","class":"MeshInstance3D"}}
```

Screenshot/snapshot tools also return standard `ImageContent` with `image/png`,
alongside the artifact path and capture metadata. Game screenshots are actual
runtime captures. Image-free headless snapshots return `status: partial` and a
CAPTURE_UNAVAILABLE warning with the scene metadata.

Errors set MCP `isError` and provide a stable structured envelope:

```json
{"ok":false,"error":{"code":"NODE_NOT_FOUND","message":"Node does not exist: Missing"}}
```

INVALID_ARGUMENT is a user/schema error; UNSUPPORTED_OPERATION indicates a
capability limit; EDITOR_DISCONNECTED and AUTHENTICATION_FAILED describe connection
problems; INTERNAL_ERROR indicates an unexpected server failure. TIMEOUT can mean
a mutation completed without its response being received. Inspect before retrying.

There is no arbitrary GDScript evaluation, object method invocation, shell tool,
remote debugger access, or generic write-any-file tool.
