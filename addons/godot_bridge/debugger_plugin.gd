@tool
extends EditorDebuggerPlugin
## Editor half of the debugger integration: collects the running game's log entries into a bounded
## ring buffer and exposes session state. The game side is runtime/bridge_runtime.gd.

const Wire = preload("transport_server.gd")
const MAX_ENTRIES := 5000
const MAX_READ := 5000

var entries: Array[Dictionary] = []
var next_seq := 1 # Sequence numbers are monotonic for this editor session and never reused.
var run := 0 # Counts game sessions started since the plugin loaded.
var session_runs := {} # session id -> run number
var epoch := int(Time.get_unix_time_from_system()) # Identifies this plugin session; cursors do not survive a restart.
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
