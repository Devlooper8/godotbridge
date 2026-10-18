@tool
extends EditorPlugin

const Transport = preload("transport_server.gd")
const Dispatcher = preload("command_dispatcher.gd")
const Dock = preload("dock/bridge_dock.gd")
var transport: RefCounted
var dispatcher: RefCounted
var dock: VBoxContainer
var last_command := ""
var last_error := ""
var busy := false
var recent_errors: Array[Dictionary] = []

func _enter_tree() -> void:
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

func _toggle(enabled: bool) -> void:
	if enabled:
		if transport.start() != OK:
			last_error = transport.start_error
			push_error("GodotBridge: " + last_error)
	else:
		transport.stop()

func _process(_delta: float) -> void:
	transport.poll()
	if not busy and not transport.queue.is_empty():
		_execute(transport.queue.pop_front())
	dock.update_status(transport.port, transport.clients.size(), last_command, last_error)

func _execute(item: Dictionary) -> void:
	busy = true
	last_command = item.request.method
	var result: Dictionary = await dispatcher.dispatch(item.request.method, item.request.get("params", {}))
	if not result.get("ok", false):
		last_error = result.error.message
		recent_errors.append({"method": last_command, "timestamp": Time.get_datetime_string_from_system(true), "error": result.error})
		if recent_errors.size() > 50:
			recent_errors.pop_front()
	transport.respond(item.client, item.request.request_id, result)
	busy = false
