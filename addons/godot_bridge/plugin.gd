@tool
extends EditorPlugin

const Transport = preload("transport_server.gd")
const Dispatcher = preload("command_dispatcher.gd")
const Dock = preload("dock/bridge_dock.gd")
const DebuggerBridge = preload("debugger_plugin.gd")
const AUTOLOAD_NAME := "GodotBridgeRuntime"
const AUTOLOAD_PATH := "res://addons/godot_bridge/runtime/bridge_runtime.gd"
const RETRY_MIN_MS := 1000
const RETRY_MAX_MS := 10000
# Plugin-side operations take about 15 s at most (debug.pause waits 10 s + 3 s, runtime.* 5 s + 5 s) and clients allow
# timeouts up to 600 s, so a request still running after this is considered lost.
const REQUEST_WATCHDOG_MS := 120000
var transport: RefCounted
var dispatcher: RefCounted
var dock: VBoxContainer
var debugger: EditorDebuggerPlugin
var last_command := ""
var last_error := ""
var busy := false
var generation := 0 # Identifies the executing request, so a coroutine abandoned by the watchdog stays silent if it resumes.
var current: Dictionary = {}
var started_at := 0
var recent_errors: Array[Dictionary] = []
var wanted := true # The dock toggle is the desired state; _process restarts a failed or lost listener while it is on.
var retry_at := 0
var retry_delay := RETRY_MIN_MS
var reported_error := ""

## Enabling registers the game-side autoload; _enter_tree covers installs enabled before it existed.
func _enable_plugin() -> void:
	_register_autoload()

func _disable_plugin() -> void:
	if ProjectSettings.has_setting("autoload/" + AUTOLOAD_NAME):
		remove_autoload_singleton(AUTOLOAD_NAME)

func _register_autoload() -> void:
	# Deferred from _enter_tree: the autoload settings are not ready yet at that point and the call is silently lost.
	# Leave project.godot untouched when the entry is already there.
	if not ProjectSettings.has_setting("autoload/" + AUTOLOAD_NAME):
		add_autoload_singleton(AUTOLOAD_NAME, AUTOLOAD_PATH)
		# The editor only persists this when it closes cleanly; a crash or kill would lose it.
		ProjectSettings.save()

func _enter_tree() -> void:
	_register_autoload.call_deferred()
	debugger = DebuggerBridge.new()
	add_debugger_plugin(debugger)
	transport = Transport.new()
	dispatcher = Dispatcher.new(self)
	dock = Dock.new()
	dock.connection_toggled.connect(_toggle)
	add_control_to_dock(DOCK_SLOT_RIGHT_BL, dock)
	_toggle(true)
	set_process(true)

func _exit_tree() -> void:
	set_process(false)
	if transport:
		transport.stop()
	if dock:
		remove_control_from_docks(dock)
		dock.queue_free()
	dispatcher = null
	if debugger:
		remove_debugger_plugin(debugger)
		debugger = null

func _toggle(enabled: bool) -> void:
	wanted = enabled
	if enabled:
		retry_delay = RETRY_MIN_MS
		_start_transport()
	else:
		transport.stop()
		transport.start_error = ""

func _start_transport() -> void:
	if transport.start() == OK:
		retry_delay = RETRY_MIN_MS
		reported_error = ""
		return
	if transport.start_error != reported_error:
		reported_error = transport.start_error
		push_error("GodotBridge: " + reported_error)
	retry_at = Time.get_ticks_msec() + retry_delay
	retry_delay = mini(retry_delay * 2, RETRY_MAX_MS)

func _state_line() -> String:
	if not wanted:
		return "Disabled"
	if transport.is_up():
		return "127.0.0.1:%d" % transport.port
	return "Retrying: " + transport.start_error

func _process(_delta: float) -> void:
	if wanted:
		transport.maintain()
		if not transport.is_up() and Time.get_ticks_msec() >= retry_at:
			_start_transport()
	transport.poll()
	# Outside `wanted` on purpose: switching the dock off must not leave a stuck operation holding the editor.
	if busy and Time.get_ticks_msec() - started_at > REQUEST_WATCHDOG_MS:
		_abandon()
	if not busy and not transport.queue.is_empty():
		_execute(transport.queue.pop_front())
	dock.update_status(_state_line(), transport.clients.size(), last_command, last_error)

func _execute(item: Dictionary) -> void:
	busy = true
	generation += 1
	var mine := generation
	current = item
	started_at = Time.get_ticks_msec()
	last_command = item.request.method
	var result: Dictionary = await dispatcher.dispatch(item.request.method, item.request.get("params", {}))
	if mine != generation:
		return # Abandoned: the watchdog already answered and released `busy`, which a newer request may hold now.
	# A handler script error returns {} (or a failure without an error object); answer it instead of aborting here
	# and leaving `busy` set.
	if not result.has("ok") or (not result.ok and not result.get("error") is Dictionary):
		result = Transport.failure("INTERNAL_ERROR", "The operation failed inside the editor; its outcome is unknown. See the editor log.")
	if not result.ok:
		_record_error(result.error)
	transport.respond(item.client, item.request.request_id, result)
	busy = false
	current = {}

func _record_error(error: Dictionary) -> void:
	last_error = str(error.get("message", ""))
	recent_errors.append({"method": last_command, "timestamp": Time.get_datetime_string_from_system(true), "error": error})
	if recent_errors.size() > 50:
		recent_errors.pop_front()

## The executing request never finished (its coroutine is not resuming, or a hook awaits something that never
## happens). Answer it so the client is not left waiting and release `busy` so the editor serves requests again. The
## zombie may still complete its side effects later: clients must treat TIMEOUT as an unknown outcome.
func _abandon() -> void:
	if current.is_empty():
		busy = false
		return
	generation += 1
	var item := current
	current = {}
	var failure := Transport.failure("TIMEOUT", "The editor did not finish this operation in time; its outcome is unknown. Inspect before retrying.")
	push_error("GodotBridge: %s did not finish within %.0f s and was abandoned" % [item.request.method, REQUEST_WATCHDOG_MS / 1000.0])
	_record_error(failure.error)
	transport.respond(item.client, item.request.request_id, failure)
	busy = false
