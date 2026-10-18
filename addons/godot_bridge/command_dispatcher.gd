@tool
extends RefCounted

const Transport = preload("transport_server.gd")
const Validator = preload("schema_validator.gd")
const Scenes = preload("scene_manager.gd")
const Nodes = preload("node_manager.gd")
const Resources = preload("resource_manager.gd")
const Visual = preload("visual_capture.gd")
var plugin: EditorPlugin
var scenes: RefCounted
var nodes: RefCounted
var schemas: Dictionary
var visual: RefCounted

func _init(owner_plugin: EditorPlugin) -> void:
	plugin = owner_plugin
	scenes = Scenes.new(plugin)
	nodes = Nodes.new(plugin.get_undo_redo())
	visual = Visual.new(plugin)
	var data = JSON.parse_string(FileAccess.get_file_as_string("res://addons/godot_bridge/schemas.json"))
	schemas = data if data is Dictionary else {}

func dispatch(method: String, params: Dictionary) -> Dictionary:
	if method != "handshake":
		if not schemas.has(method):
			return Transport.failure("UNSUPPORTED_OPERATION", "Unknown operation: " + method)
		if not Validator.validate(params, schemas[method]):
			return Transport.failure("INVALID_ARGUMENT", "Arguments do not match the operation schema.")
		for key in schemas[method].get("properties", {}):
			if not params.has(key) and schemas[method].properties[key].has("default"):
				params[key] = schemas[method].properties[key].default
	if method.begins_with("3d."):
		return Resources.handle(method, params, nodes)
	if method == "editor.camera_info":
		return visual.camera_info()
	if method == "viewport.capture":
		return await visual.capture(params)
	if method.begins_with("game."):
		if params.get("mode") != "editor":
			return Transport.failure("UNSUPPORTED_OPERATION", "Managed games are controlled by the Python client.")
		if method == "game.logs":
			return plugin.debugger.logs(params)
		if method == "game.stop":
			EditorInterface.stop_playing_scene()
		elif method == "game.run":
			if params.get("headless", false):
				return Transport.failure("UNSUPPORTED_OPERATION", "Use managed mode for headless games.")
			if params.get("scene") != null:
				if not Scenes.safe_path(params.scene) or not FileAccess.file_exists(params.scene):
					return Transport.failure("SCENE_NOT_FOUND", "Provide an existing project-local .tscn scene.")
				EditorInterface.play_custom_scene(params.scene)
			elif params.get("current", false):
				EditorInterface.play_current_scene()
			else:
				EditorInterface.play_main_scene()
		return {"ok": true, "result": {"running": EditorInterface.is_playing_scene(), "mode": "editor", "scene": EditorInterface.get_playing_scene()}}
	if method.begins_with("node.") or method in ["scene.tree", "editor.select", "editor.focus", "editor.undo", "editor.redo"]:
		return nodes.handle(method, params)
	if method.begins_with("scene."):
		return await scenes.handle(method, params)
	match method:
		"editor.diagnostics":
			return {"ok": true, "result": {"source": "bridge_commands", "errors": plugin.recent_errors}}
		"handshake", "project.info":
			var main_scene: String = ProjectSettings.get_setting("application/run/main_scene", "")
			if main_scene.begins_with("uid://"):
				var id := ResourceUID.text_to_id(main_scene)
				main_scene = ResourceUID.get_id_path(id) if ResourceUID.has_id(id) else ""
			return {"ok": true, "result": {"godot_version": Engine.get_version_info().string,
				"plugin_version": "0.1.0", "project": ProjectSettings.globalize_path("res://"),
				"project_name": ProjectSettings.get_setting("application/config/name", ""),
				"main_scene": main_scene, "connected": true,
				"capabilities": schemas.keys(), "protocol_version": "1.0"}}
		"editor.status":
			var root := EditorInterface.get_edited_scene_root()
			return {"ok": true, "result": {"connected": true, "scene_path": root.scene_file_path if root else "",
				"playing": EditorInterface.is_playing_scene(), "display_server": DisplayServer.get_name()}}
	return Transport.failure("UNSUPPORTED_OPERATION", "Unknown operation: " + method)
