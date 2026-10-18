extends Node
## Game-side half of the editor debugger integration, registered by the plugin as the
## "GodotBridgeRuntime" autoload. It does nothing in the editor and in builds without an
## attached debugger (exports, bridge-managed runs), so shipping it is harmless.

const MAX_QUEUE := 2000 # Entries buffered between frames; the oldest are dropped first.
const MAX_BATCH := 200 # Entries sent per frame.
const MAX_TEXT := 4096 # Characters kept per text field.

## Logger callbacks can arrive from any thread and run inside the engine's logging path.
## This class must therefore never print, push errors or otherwise log.
class BridgeLogger:
	extends Logger
	var mutex := Mutex.new()
	var queue: Array[Dictionary] = []
	var dropped := 0

	func _log_message(message: String, error: bool) -> void:
		_push({"level": "stderr" if error else "info", "message": message.trim_suffix("\n").left(MAX_TEXT),
			"time": Time.get_unix_time_from_system()})

	func _log_error(function: String, file: String, line: int, code: String, rationale: String,
			_editor_notify: bool, error_type: int, script_backtraces: Array[ScriptBacktrace]) -> void:
		var warning := error_type == ERROR_TYPE_WARNING
		var entry := {"level": "warning" if warning else "error",
			"message": (rationale if not rationale.is_empty() else code).left(MAX_TEXT),
			"time": Time.get_unix_time_from_system(), "file": file.left(MAX_TEXT), "line": line,
			"function": function.left(MAX_TEXT), "code": code.left(MAX_TEXT), "error_type": error_type}
		# push_error/push_warning report the engine's C++ origin; prefer the innermost script frame.
		for backtrace in script_backtraces:
			if backtrace != null and backtrace.get_frame_count() > 0:
				entry.native_file = entry.file
				entry.native_line = entry.line
				entry.file = backtrace.get_frame_file(0).left(MAX_TEXT)
				entry.line = backtrace.get_frame_line(0)
				entry.function = backtrace.get_frame_function(0).left(MAX_TEXT)
				break
		_push(entry)

	func _push(entry: Dictionary) -> void:
		mutex.lock()
		if queue.size() >= MAX_QUEUE:
			queue.pop_front()
			dropped += 1
		queue.append(entry)
		mutex.unlock()

	func take(count: int) -> Dictionary:
		mutex.lock()
		var batch := queue.slice(0, count)
		queue = queue.slice(batch.size())
		var lost := dropped
		dropped = 0
		mutex.unlock()
		return {"entries": batch, "dropped": lost}

var bridge_logger: BridgeLogger

func _ready() -> void:
	if Engine.is_editor_hint() or not EngineDebugger.is_active():
		set_process(false)
		return
	bridge_logger = BridgeLogger.new()
	OS.add_logger(bridge_logger)

func _exit_tree() -> void:
	if bridge_logger:
		OS.remove_logger(bridge_logger)
		bridge_logger = null

func _process(_delta: float) -> void:
	if bridge_logger == null:
		return
	var batch := bridge_logger.take(MAX_BATCH)
	if not batch.entries.is_empty() or batch.dropped > 0:
		EngineDebugger.send_message("godotbridge:log", [batch])
