@tool
extends EditorDebuggerPlugin
## Editor half of the debugger integration: collects the running game's log entries into a bounded
## ring buffer and exposes session state. The game side is runtime/bridge_runtime.gd.

const Wire = preload("transport_server.gd")
const Scenes = preload("scene_manager.gd")
const MAX_ENTRIES := 5000
const MAX_READ := 5000
const REQUEST_TIMEOUT_MS := 5000
const MAX_BREAKPOINTS := 500
const STEP_TIMEOUT_MS := 3000

## Godot's debugger commands, as ScriptEditorDebugger sends them to the game with
## EditorDebuggerSession.send_message. These names are engine-internal, NOT a documented API: they were
## verified on 4.7.2 and tests/integration/test_debug_control.py fails if an engine update renames one.
## This is the only place that knows them.
const ENGINE_COMMANDS := {"continue": "continue", "over": "next", "in": "step", "out": "out", "pause": "break"}

var entries: Array[Dictionary] = []
var next_seq := 1 # Sequence numbers are monotonic for this editor session and never reused.
var run := 0 # Counts game sessions started since the plugin loaded.
var session_runs := {} # session id -> run number
var epoch := int(Time.get_unix_time_from_system()) # Identifies this plugin session; cursors do not survive a restart.
var next_request := 1
var replies := {} # request id -> {"reply": Dictionary or null while pending}
var breakpoints := {} # Bridge registry: res:// path -> {line: true}. set_breakpoint alone is lost between runs.
var editor_breakpoints := {} # Breakpoints set in the script editor, seen through _breakpoint_set_in_tree.
var break_events := 0 # Counts session `breaked` signals; lets control commands wait for the next stop.
var continue_events := 0
var dropped := 0 # Entries the game discarded because its queue overflowed.

func _has_capture(capture: String) -> bool:
	return capture == "godotbridge"

func _setup_session(session_id: int) -> void:
	var session := get_session(session_id)
	session.started.connect(_on_started.bind(session_id))
	session.stopped.connect(_on_stopped.bind(session_id))
	session.breaked.connect(func(_can_debug): break_events += 1)
	session.continued.connect(func(): continue_events += 1)

func _breakpoint_set_in_tree(script: Script, line: int, enabled: bool) -> void:
	_mark(editor_breakpoints, script.resource_path, line, enabled)

func _breakpoints_cleared_in_tree() -> void:
	editor_breakpoints.clear()

static func _mark(registry: Dictionary, path: String, line: int, enabled: bool) -> void:
	if enabled:
		registry[path] = registry.get(path, {})
		registry[path][line] = true
	elif registry.has(path):
		registry[path].erase(line)
		if registry[path].is_empty():
			registry.erase(path)

func _on_started(session_id: int) -> void:
	var session := get_session(session_id)
	for path in breakpoints:
		for line in breakpoints[path]:
			session.set_breakpoint(path, line, true)
	run += 1
	session_runs[session_id] = run
	_append(session_id, {"kind": "run_started", "level": "info", "message": "", "time": Time.get_unix_time_from_system()})

func _on_stopped(session_id: int) -> void:
	_append(session_id, {"kind": "run_stopped", "level": "info", "message": "", "time": Time.get_unix_time_from_system()})

func _capture(message: String, data: Array, session_id: int) -> bool:
	if message == "godotbridge:log":
		if data.size() == 1 and data[0] is Dictionary:
			_collect(data[0], session_id)
		return true
	if message == "godotbridge:reply":
		if data.size() == 2 and data[0] is int and data[1] is Dictionary and replies.has(data[0]):
			replies[data[0]].reply = data[1]
		return true
	return false

func _collect(batch: Dictionary, session_id: int) -> void:
	if batch.get("dropped") is int:
		dropped += batch.dropped
	var incoming = batch.get("entries")
	if not incoming is Array:
		return
	for item in incoming:
		if not item is Dictionary:
			continue
		var entry := {"kind": "log"}
		for key in ["level", "message", "time", "file", "line", "function", "code", "native_file", "native_line"]:
			if item.has(key):
				entry[key] = item[key]
		_append(session_id, entry)

func _append(session_id: int, entry: Dictionary) -> void:
	entry.seq = next_seq
	entry.run = session_runs.get(session_id, run)
	entry.session = session_id
	next_seq += 1
	entries.append(entry)
	if entries.size() > MAX_ENTRIES:
		entries.pop_front()

func is_running() -> bool:
	for session in get_sessions():
		if session.is_active():
			return true
	return false

## Entries with seq > since. `missed` counts entries evicted from the ring before they could be read.
func logs(params: Dictionary) -> Dictionary:
	var since: int = params.get("since", 0) if params.get("since") != null else 0
	var limit := mini(int(params.get("limit", 1000)), MAX_READ)
	var oldest: int = entries[0].seq if not entries.is_empty() else next_seq
	var selected: Array[Dictionary] = []
	for entry in entries:
		if entry.seq > since:
			selected.append(entry)
			if selected.size() >= limit:
				break
	return {"ok": true, "result": {"mode": "editor", "entries": selected,
		"next": selected[-1].seq if not selected.is_empty() else mini(since, next_seq - 1),
		"missed": maxi(0, oldest - 1 - since) if not entries.is_empty() else 0, "dropped": dropped,
		"running": is_running(), "run": run, "epoch": epoch}}

## Break state straight from the sessions; no debug adapter involved.
func debug_status() -> Dictionary:
	var sessions: Array[Dictionary] = []
	var breaked := false
	for session in get_sessions():
		var info := {"active": session.is_active(), "breaked": session.is_breaked(), "debuggable": session.is_debuggable()}
		sessions.append(info)
		breaked = breaked or (info.active and info.breaked)
	var settings := EditorInterface.get_editor_settings()
	return {"ok": true, "result": {"running": is_running(), "breaked": breaked, "sessions": sessions,
		"dap_port": int(settings.get_setting("network/debug_adapter/remote_port")),
		"project": ProjectSettings.globalize_path("res://").trim_suffix("/")}}

## Runs one request against the played game's autoload and waits for its reply (5 s).
func request(command: String, params: Dictionary, timeout_ms: int = REQUEST_TIMEOUT_MS) -> Dictionary:
	var session: EditorDebuggerSession = null
	for candidate in get_sessions():
		if candidate.is_active():
			session = candidate
			break
	if session == null:
		return Wire.failure("GAME_NOT_RUNNING", "No editor-played game is running; start one with game.run (mode editor).")
	var id := next_request
	next_request += 1
	var slot := {"reply": null}
	replies[id] = slot
	session.send_message("godotbridge:" + command, [id, params])
	var deadline := Time.get_ticks_msec() + timeout_ms
	while slot.reply == null and session.is_active() and Time.get_ticks_msec() < deadline:
		await Engine.get_main_loop().process_frame
	replies.erase(id)
	if slot.reply == null:
		return Wire.failure("TIMEOUT", "The game did not answer in time; it may be busy, or it has no GodotBridgeRuntime autoload.")
	return slot.reply

func _active_session() -> EditorDebuggerSession:
	for candidate in get_sessions():
		if candidate.is_active():
			return candidate
	return null

static func _lines(registry: Dictionary) -> Dictionary:
	var result := {}
	for path in registry:
		var lines: Array = registry[path].keys()
		lines.sort()
		result[path] = lines
	return result

## `bridge` holds what this API set; `editor` what the script editor reported since the plugin loaded.
## Both are applied to the next run, so `all` is what will be hit (editor breakpoints in scripts that were
## already open before the plugin loaded are not visible to it).
func list_breakpoints() -> Dictionary:
	var merged := {}
	for source in [breakpoints, editor_breakpoints]:
		for path in source:
			merged[path] = merged.get(path, {})
			merged[path].merge(source[path])
	return {"ok": true, "result": {"bridge": _lines(breakpoints), "editor": _lines(editor_breakpoints), "all": _lines(merged)}}

func set_breakpoints(path: String, lines: Array) -> Dictionary:
	if not Scenes.safe_path(path, "gd") or not FileAccess.file_exists(path):
		return Wire.failure("FILE_ACCESS_DENIED", "Use an existing project-local res:// .gd script without traversal or symlinks.")
	var wanted := {}
	for line in lines:
		wanted[int(line)] = true
	var total := wanted.size()
	for other in breakpoints:
		if other != path:
			total += breakpoints[other].size()
	if total > MAX_BREAKPOINTS:
		return Wire.failure("INVALID_ARGUMENT", "At most %d breakpoints can be registered." % MAX_BREAKPOINTS)
	var current: Dictionary = breakpoints.get(path, {})
	var session := _active_session()
	for line in current:
		if not wanted.has(line) and session:
			session.set_breakpoint(path, line, false)
	for line in wanted:
		if not current.has(line) and session:
			session.set_breakpoint(path, line, true)
	if wanted.is_empty():
		breakpoints.erase(path)
	else:
		breakpoints[path] = wanted
	return list_breakpoints()

func clear_breakpoints(path: Variant) -> Dictionary:
	var session := _active_session()
	for each in breakpoints.keys():
		if path == null or path == each:
			if session:
				for line in breakpoints[each]:
					session.set_breakpoint(each, line, false)
			breakpoints.erase(each)
	return list_breakpoints()

## Execution control. Waits for the game's reaction so callers see the new state.
func control(kind: String) -> Dictionary:
	var session := _active_session()
	if session == null:
		return Wire.failure("GAME_NOT_RUNNING", "No editor-played game is running.")
	if kind == "pause":
		if session.is_breaked():
			return {"ok": true, "result": {"breaked": true, "changed": false}}
		# Breaking while the game is still starting up crashed the editor in testing; wait until the autoload answers.
		var ready := {}
		var give_up := Time.get_ticks_msec() + 10000
		while Time.get_ticks_msec() < give_up:
			ready = await request("ping", {}, 500)
			if ready.get("ok", false) or ready.get("error", {}).get("code") != "TIMEOUT":
				break
		if not ready.get("ok", false):
			return ready
	elif not session.is_breaked():
		return Wire.failure("NOT_BREAKED", "The game is not stopped at a breakpoint.")
	var wait_for_break := kind != "continue"
	var before := break_events if wait_for_break else continue_events
	session.send_message(ENGINE_COMMANDS[kind], [])
	var deadline := Time.get_ticks_msec() + STEP_TIMEOUT_MS
	while (break_events if wait_for_break else continue_events) == before and session.is_active() and Time.get_ticks_msec() < deadline:
		await Engine.get_main_loop().process_frame
	return {"ok": true, "result": {"breaked": session.is_active() and session.is_breaked(), "running": session.is_active(), "changed": (break_events if wait_for_break else continue_events) != before}}

## Stack and variables are read by the game itself while it is stopped.
func inspect_stopped(command: String, params: Dictionary) -> Dictionary:
	var session := _active_session()
	if session == null:
		return Wire.failure("GAME_NOT_RUNNING", "No editor-played game is running.")
	if not session.is_breaked():
		return Wire.failure("NOT_BREAKED", "The game is not stopped at a breakpoint.")
	return await request(command, params)
