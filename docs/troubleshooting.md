# Troubleshooting

**GODOT_NOT_FOUND:** set `GODOT_EXECUTABLE` or `--godot` to the actual 4.7+ stable
binary, including arbitrary paths or macOS `.app` bundles. Godot 3, prereleases,
old 4.x engines and shell wrappers do not satisfy discovery.

**EDITOR_DISCONNECTED:** open the selected project, install/enable the plugin,
and inspect the GodotBridge dock. A connection file from a terminated editor is
stale. Restart the plugin; clients rediscover credentials on each operation.
If another editor owns the connection, close it before enabling a second one.

**AUTHENTICATION_FAILED:** credentials may have rotated between reading and
connecting. Reconnect by issuing a new read-only operation. Do not paste tokens
into logs, issues or MCP client configuration.

**No endpoint / permissions failure:** use a writable local project. Unix needs
working chmod semantics. Windows needs `whoami.exe` and `icacls.exe` available
in System32 and permission to restrict the bridge directory. No PowerShell
execution-policy change is required.

**TIMEOUT:** raise the global `--timeout` for a slow import or GPU. A timed-out
mutation's outcome is unknown; inspect the scene before retrying. Viewport PNG
readback/encoding can briefly occupy the editor thread.

**READ_ONLY_RESOURCE:** inherited scenes, nodes inside scene instances (enable
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

**No editor game logs:** `game logs --mode editor` returns UNSUPPORTED_OPERATION.
Use managed mode for combined stdout/stderr, or the editor's normal debugger.

**Tests:** run `python scripts/run_integration_tests.py --graphical`. Artifacts and
editor logs stay in `.artifacts/`. Tests without `--engine` skip engine integration
explicitly. This Windows environment emits a root-certificate-store error from
Godot's sandboxed startup; validation retains it as an environment warning, not
a project parsing failure. No project/parse errors are suppressed.
