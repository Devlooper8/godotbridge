@tool
extends VBoxContainer

signal connection_toggled(enabled: bool)
var summary := Label.new()
var control := CheckButton.new()

func _init() -> void:
	name = "GodotBridge"
	custom_minimum_size = Vector2(220, 100)
	add_child(summary)
	control.text = "Accept local connections"
	control.button_pressed = true
	control.toggled.connect(func(enabled): connection_toggled.emit(enabled))
	add_child(control)

func update_status(port: int, count: int, command: String, error: String) -> void:
	summary.text = "GodotBridge 0.1.0\n%s\n%s\nClients: %d\nLast: %s\n%s" % [
		ProjectSettings.get_setting("application/config/name", ""),
		"127.0.0.1:%d" % port if port else "Disconnected", count, command, error.left(160)]
