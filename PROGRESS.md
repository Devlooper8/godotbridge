# GodotBridge progress

## Environment

- Empty repository; Windows, Python 3.13.7.
- Actual engine: `4.7.2.stable.mono.official.ed1daf0bf` at `D:/godot/Godot_v4.7.2-stable_mono_win64_console.exe`.
- Target/minimum for this release: Godot 4.7; Python 3.11+.
- Official 4.7 EditorInterface, EditorUndoRedoManager, TCPServer and command-line references checked before implementation.

## Plan and milestones

1. Foundation: IMPLEMENTED and verified: packaging, discovery, config, authenticated bounded transport, editor dock, CLI, connection tests.
2. Scene editing: IMPLEMENTED and engine-verified: schema validation, ownership, typed properties, undo/redo, save/reopen, duplication/reparenting, conflict detection.
3. 3D helpers: IMPLEMENTED and engine-verified: primitives, materials, collision, camera/light. Generated arena is examples/3d_demo/scenes/main.tscn.
4. Visual inspection: IMPLEMENTED and graphically verified: metadata/AABBs, direct editor capture, isolated geometry previews, five viewpoints and snapshots.
5. MCP: IMPLEMENTED and verified over actual stdio with SDK 2.0.0: tools, schemas, mutations, inspection, errors and image content.
6. Hardening: Windows ACLs, constant-time authentication, bounded transport/logs, confinement, packaging and docs implemented. CI matrix added; Linux/macOS execution unverified.
7. Game execution: IMPLEMENTED and engine-verified: managed launch/stop/status/logs, deadlines, nonzero exits, runtime PNG and editor play controls.

## Verification

- Engine version executed successfully.
- Phase 1: `python -m pytest tests/unit tests/integration/test_connection.py --engine --basetemp .artifacts/pytest-phase1 -q`: **8 passed** against actual Godot 4.7.2.
- Editable package installation and `godotctl --help` succeeded.
- Authentication, wrong-token rejection, malformed JSON, fragmented frames and reconnect tested with real TCP/editor.
- pip downloads are restricted; test dependencies downloaded from PyPI with the permitted curl tool and installed offline.
- Harness isolates editor user data; no modifications to the developer's editor settings.
- Phase 2: **14 integration tests passed**, including undo/redo and saved-scene reopening.
- Phase 3: **5 3D tests passed** after fixing null-resource serialization.
- Phase 4: **6 graphical tests passed** after fixing idle-editor redraw timing and default skeleton filtering. Preview inspected visually.
- Phase 5: real MCP stdio discovery, mutation, inspection, structured errors and graphical image content passed.
- Runtime/MCP: **5 tests passed**, including runtime screenshot, editor play and exit code 7 detection.
- Initial full graphical suite: **52 passed**, Windows/NVIDIA RTX 3070 OpenGL compatibility.
- Ruff passed. Wheel and sdist built with the canonical addon.
- Documented CLI arena workflow executed end-to-end. Negative positional-coordinate parsing was fixed and regression-tested.
- Offline import, saved demo validation and offline ProjectSettings lookup verified with actual Godot.
- Headless saves now suppress thumbnails through the public editor API; save-as and selection tested.
- Final headless suite: `python scripts/run_integration_tests.py` — **56 passed, 1 intentionally skipped** (graphical editor play).
- Final graphical suite: `python scripts/run_integration_tests.py --graphical` — **57 passed**.
- Scene-mutation milestones (scripted nodes, instances, inherited scenes; 16 new integration tests): headless **72 passed, 1 skipped**; graphical **73 passed** (one unrelated managed-game test failed once on the first run and passed on rerun and in isolation).
- Unit-only: `python -m pytest tests/unit -q` — **13 passed**.
- Installed-wheel graphical verification: `python -m pytest -o pythonpath=.artifacts/wheel-final tests/integration/test_connection.py tests/integration/test_mcp.py tests/integration/test_three_d.py --engine --graphical --basetemp .artifacts/pytest-wheel-final -q` — **10 passed**. This exercised the installed package's bundled addon against the real engine.
- Both documented CLI and Python arena workflows executed, including save, validation, reopen and snapshot.
- `godotctl --project examples/3d_demo --timeout 60 project validate --json` — valid; no project errors.
- Final Ruff lint and formatting: passed, 43 Python files. Documentation relative links: all resolve.
- `python -m build --no-isolation` produced `dist/godotbridge-0.1.0-py3-none-any.whl` and `dist/godotbridge-0.1.0.tar.gz`.
- Engine logs are retained in `.artifacts/editor-headless.log` and `.artifacts/editor-graphical.log`. The sandbox's root-certificate-store warning remains visible; no plugin parse/runtime errors remain in the final logs.

## Known limitations

- 0.1.0 is a release candidate; Linux/macOS and Python 3.11 CI have not run here.
- Mutation rules follow the editor: `@tool`-script nodes need `allow_tool_script`; instance internals need editable children and nested-instance internals stay read-only; inherited nodes take overrides only.
- Inherited detection reads the saved scene file (`get_scene_inherited_state()` is not exposed to GDScript): unsaved inherited scenes look non-inherited, and if a base file changes after first use every node is treated as inherited until the scene is reopened.
- Script variables are type-checked, not range/enum-checked; only scalar, vector, color, NodePath and simple-resource values are encodable. No cross-command atomic transaction API.
- Preview omits animation, particles, skinning, gameplay and WorldEnvironment.
- Editor camera is readable; framing uses the separate preview camera. Focus selects/switches workspace without moving the camera.
- Full debugger introspection, editor log streaming, script authoring and C# compilation are not implemented.
- Managed runtime uses a custom SceneTree and isolated user://; custom-main-loop projects should use editor mode.
- Current scene discovery requires the plugin; main/explicit scene runs work offline through supported engine APIs.
- Abandoned captures and crash-stale supervisor locks need explicit cleanup; stored PIDs are never killed.

## Exact next tasks

- Run `.github/workflows/ci.yml` on Linux/macOS/Python 3.11 before labeling the release stable; inspect permission setup, application-bundle discovery and Xvfb captures on those hosts.
- Add atomic multi-command batches with full prevalidation and rollback, backed by one editor undo action.
- Coordinate script-file writes with dirty editor buffers before exposing script-authoring tools.
- Add a supported EditorDebuggerPlugin integration for editor-managed logs and runtime inspection; retain the distinction from managed stdout capture.
- Add bounded capture-cache retention and supervisor crash-recovery tooling without signalling stored PIDs.
