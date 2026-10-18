@tool
extends EditorDebuggerPlugin
## Editor half of the debugger integration: collects the running game's log entries into a bounded
## ring buffer and exposes session state. The game side is runtime/bridge_runtime.gd.

const Wire = preload("transport_server.gd")
const MAX_ENTRIES := 5000
const MAX_READ := 5000
const REQUEST_TIMEOUT_MS := 5000

var entries: Array[Dictionary] = []
var next_seq := 1 # Sequence numbers are monotonic for this editor session and never reused.
var run := 0 # Counts game sessions started since the plugin loaded.
var session_runs := {} # session id -> run number
var epoch := int(Time.get_unix_time_from_system()) # Identifies this plugin session; cursors do not survive a restart.
var next_request := 1
var replies := {} # request id -> {"reply": Dictionary or null while pending}
var dropped := 0 # Entries the game discarded because its queue overflowed.

func _has_capture(capture: String) -> bool:
	return capture == "godotbridge"

func _setup_session(session_id: int) -> void:
	var session := get_session(session_id)
	session.started.connect(_on_started.bind(session_id))
	session.stopped.connect(_on_stopped.bind(session_id))

func _on_started(session_id: int) -> void:
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
func request(command: String, params: Dictionary) -> Dictionary:
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
	var deadline := Time.get_ticks_msec() + REQUEST_TIMEOUT_MS
	while slot.reply == null and session.is_active() and Time.get_ticks_msec() < deadline:
		await Engine.get_main_loop().process_frame
	replies.erase(id)
	if slot.reply == null:
		return Wire.failure("TIMEOUT", "The game did not answer in time; it may be busy, or it has no GodotBridgeRuntime autoload.")
	return slot.reply
