# Troubleshooting

**GODOT_NOT_FOUND:** set `GODOT_EXECUTABLE` or `--godot` to the actual 4.7+ stable
binary, including arbitrary paths or macOS `.app` bundles. Godot 3, prereleases,
old 4.x engines and shell wrappers do not satisfy discovery.

**EDITOR_DISCONNECTED:** open the selected project, install/enable the plugin,
and inspect the GodotBridge dock: it shows `127.0.0.1:<port>` while listening,
`Retrying: <reason>` while the plugin retries (every 1 s, backing off to 10 s) and
`Disabled` when its toggle is off. A connection file from a terminated editor is
stale; a new editor takes it over once nothing on the old port answers a GodotBridge
handshake. A port that is still open but held by another program no longer blocks the
takeover, and an owner that is frozen or very slow (no editor frame for about a second)
may be taken over as well.
`Retrying: Another editor owns this project's connection` appears only while a GodotBridge
that answers a handshake still sits on the old port, so that editor really is alive:
close it. The plugin rewrites a deleted credentials file within about two
seconds. Clients rediscover credentials on each operation. To ride out an editor
that is still starting or restarting, pass `--connect-wait SECONDS`, set
`connect_wait` in `godotbridge.toml` or give the MCP server `--connect-wait`: only
connecting is retried (every 0.2 s), the operation itself is sent once. An MCP
server may start before the project or editor exist; its calls fail with
EDITOR_DISCONNECTED until the editor with the enabled plugin is open.

**AUTHENTICATION_FAILED:** credentials may have rotated between reading and
connecting (an editor restart). The client already reads the file again once
immediately, and repeatedly while `connect_wait` lasts; a failure that persists
means the file does not belong to the listening editor. Reconnect by issuing a new
read-only operation. Do not paste tokens into logs, issues or MCP client
configuration.

**No endpoint / permissions failure:** use a writable local project. Unix needs
working chmod semantics. Windows needs `whoami.exe` and `icacls.exe` available
in System32 and permission to restrict the bridge directory. No PowerShell
execution-policy change is required.

**TIMEOUT:** raise the global `--timeout` for a slow import or GPU. A timed-out
mutation's outcome is unknown; inspect the scene before retrying. Viewport PNG
readback/encoding can briefly occupy the editor thread. A TIMEOUT can also come from the
editor itself after 120 s ("did not finish within 120 s and was abandoned" in the editor
log): a stuck operation no longer blocks the editor forever, but it may still finish its
side effects later. The state is also in `editor diagnostics` (recent errors with the
method and `TIMEOUT`).

**INTERNAL_ERROR "failed inside the editor":** a handler hit a script error. Its outcome
is unknown; read the editor log and inspect the scene before retrying.

**READ_ONLY_RESOURCE:** structure changes to inherited-scene nodes (also returned
for every node when the base scene changed on disk after the scene was opened:
reopen the scene), nodes inside scene instances (enable
`node.set_editable_children` for property edits; structure changes always belong
to the source scene) and `@tool` scripted nodes are protected. Open the source
scene or edit through the normal editor;
for a `@tool` node pass `allow_tool_script` if you accept that its script runs
in the editor. Only exported script variables are exposed besides built-in properties.

**FILE_ACCESS_DENIED on save:** a file changed on disk since it was opened or
saved. Resolve/reload that change in Godot before saving. New scenes, save-as,
captures and snapshots require unused destinations. Output paths are relative
to the selected project, not the terminal working directory.

**CAPTURE_UNAVAILABLE / partial snapshot:** a headless editor or runtime has no
visible framebuffer. Use a graphical editor for screenshots. `metadata.json`
records the exact capture failure and `scene.json` remains useful. An editor
screenshot is not a runtime screenshot; use a graphical managed game for the latter.

**Preview differs from the game:** preview renders static mesh/light geometry
with standardized lighting and a separate camera. It omits animation, particles,
skinning, runtime logic and custom environments. Read its warnings. Use
`game screenshot` during a managed graphical run for actual runtime pixels.

**Validation fails but exit code is zero:** Godot sometimes reports parse/resource
errors without a failing process exit. GodotBridge inspects diagnostics as well
as the exit code and its validator summary. Import missing resources while the
editor is closed. C# builds are not part of this validator.

**Managed game cannot restart:** `game status` and `game logs` expose the last
state and exit code. Try `game stop`. If the supervisor crashed, verify manually
that its game has ended before removing `.godot/godotbridge/game/run.lock`.
No stored PID is killed automatically. A captured runtime request may leave a
`capture.lock` after a crashed client; remove it only after that client has exited.

**No editor game logs:** `game logs --mode editor` only sees games started while the
plugin was enabled and the `GodotBridgeRuntime` autoload existed (check
Project Settings > Globals > Autoload; the plugin re-adds it when it loads). The
autoload is inert in exported builds and managed runs. A game that already
crashed before its first frame sends nothing; read the editor's Output panel or
use managed mode (`game logs`, stdout/stderr) instead. If the cursor stops
advancing after an editor restart, compare `epoch` and restart from no `since`.

**GAME_NOT_RUNNING / runtime TIMEOUT:** `runtime.*` needs a game started with
`game run --mode editor` (managed games do not have it) and the
`GodotBridgeRuntime` autoload in Project Settings > Globals > Autoload. Right after
`game run` the plugin first waits up to five seconds for the game to start and its
autoload to answer; "has not finished starting, or it has no GodotBridgeRuntime
autoload" means that wait ran out (a game started before the plugin was enabled has no
autoload and must be restarted). Once the game is ready, a command it does not answer
within five seconds (frozen main thread) is a TIMEOUT too; it is sent once and never
resent. Trees are limited to 5,000 nodes per request.

**NOT_BREAKED / breakpoint not hit:** `debug stack/variables/step/continue` need a game
stopped at a breakpoint (see `debug status`). Breakpoints go on executable lines of a
`.gd` script (1-based) and apply to the next run; a game that already passed the line is
unaffected. After `debug pause` there are no script frames: use `debug step --kind in`.

**Tests:** run `python scripts/run_integration_tests.py --graphical`. Artifacts and
editor logs stay in `.artifacts/`. Tests without `--engine` skip engine integration
explicitly. This Windows environment emits a root-certificate-store error from
Godot's sandboxed startup; validation retains it as an environment warning, not
a project parsing failure. No project/parse errors are suppressed.
