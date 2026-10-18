@tool
extends RefCounted

const Wire = preload("transport_server.gd")
var plugin: EditorPlugin
var fingerprints := {}
var save_events := 0

func _init(owner_plugin: EditorPlugin) -> void:
	plugin = owner_plugin
	plugin.scene_changed.connect(track)
	plugin.scene_saved.connect(_saved)

func _saved(path: String) -> void:
	save_events += 1
	var root := EditorInterface.get_edited_scene_root()
	if root and root.scene_file_path == path:
		fingerprints[root.get_instance_id()] = FileAccess.get_sha256(path)

static func safe_path(path: String, extension: String = "tscn") -> bool:
	if not path.begins_with("res://") or "\\" in path or ":" in path.substr(6) or path.get_extension() != extension:
		return false
	var current := "res://"
	for component in path.substr(6).split("/"):
		if component.is_empty() or component.begins_with("."):
			return false
		var directory := DirAccess.open(current)
		if directory and directory.is_link(component):
			return false
		current = current.path_join(component)
	return true

func track(root: Node) -> void:
	if root and not root.scene_file_path.is_empty() and not fingerprints.has(root.get_instance_id()):
		fingerprints[root.get_instance_id()] = FileAccess.get_sha256(root.scene_file_path)

func handle(method: String, params: Dictionary) -> Dictionary:
	var root := EditorInterface.get_edited_scene_root()
	track(root)
	if method == "scene.list":
		return success({"scenes": Array(EditorInterface.get_open_scenes())})
	if method == "scene.open" or method == "scene.create":
		var path: String = params.path
		if not safe_path(path):
			return Wire.failure("FILE_ACCESS_DENIED", "Use a res:// .tscn path without traversal or symlinks.")
		if method == "scene.create":
			if FileAccess.file_exists(path):
				return Wire.failure("FILE_ACCESS_DENIED", "Scene already exists; no file was overwritten.")
			if DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(path.get_base_dir())) != OK:
				return Wire.failure("FILE_ACCESS_DENIED", "Cannot create scene directory.")
			var node: Node = ClassDB.instantiate(params.get("root", "Node3D"))
			node.name = path.get_file().get_basename().validate_node_name()
			var packed := PackedScene.new()
			var err := packed.pack(node)
			node.free()
			if err == OK:
				err = ResourceSaver.save(packed, path)
			if err != OK:
				return Wire.failure("FILE_ACCESS_DENIED", "Failed to save new scene: " + error_string(err))
			EditorInterface.get_resource_filesystem().update_file(path)
		elif not FileAccess.file_exists(path):
			return Wire.failure("SCENE_NOT_FOUND", "Scene file does not exist: " + path)
		var packed = ResourceLoader.load(path, "PackedScene")
		if not packed is PackedScene:
			return Wire.failure("SCENE_NOT_FOUND", "File is not a loadable PackedScene.")
		var inherited: bool = method == "scene.open" and params.get("inherited", false)
		var previous_root := root
		EditorInterface.open_scene_from_path(path, inherited)
		for attempt in 60:
			await plugin.get_tree().process_frame
			root = EditorInterface.get_edited_scene_root()
			if inherited and root and root != previous_root and root.scene_file_path.is_empty():
				# A new inherited scene is unsaved: it has no path until saved with scene.save_as.
				return success({"scene_path": "", "root": String(root.name), "inherited_from": path})
			if not inherited and root and root.scene_file_path == path:
				track(root)
				return success({"scene_path": path, "root": String(root.name)})
		return Wire.failure("EDITOR_BUSY", "Editor did not finish switching scenes; inspect current scene before retrying.")
	if root == null:
		return Wire.failure("SCENE_NOT_OPEN", "Open or create a scene first.")
	if method == "scene.current":
		return success({"scene_path": root.scene_file_path, "root": String(root.name)})
	if method == "scene.close":
		if root.scene_file_path.is_empty() or root.scene_file_path in EditorInterface.get_unsaved_scenes():
			return Wire.failure("EDITOR_BUSY", "Save the scene before closing it.")
		var err := EditorInterface.close_scene()
		return success({"closed": true}) if err == OK else Wire.failure("INTERNAL_ERROR", error_string(err))
	if method == "scene.save" or method == "scene.save_as":
		var path: String = params.get("path", root.scene_file_path)
		if not safe_path(path):
			return Wire.failure("FILE_ACCESS_DENIED", "A project-local .tscn path is required.")
		if method == "scene.save_as" and FileAccess.file_exists(path):
			return Wire.failure("FILE_ACCESS_DENIED", "Save-as destination already exists.")
		if method == "scene.save" and fingerprints.get(root.get_instance_id(), "") != FileAccess.get_sha256(path):
			return Wire.failure("FILE_ACCESS_DENIED", "Scene changed on disk since opening; resolve external modifications before saving.")
		if DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(path.get_base_dir())) != OK:
			return Wire.failure("FILE_ACCESS_DENIED", "Cannot create scene directory.")
		var previous_save_events := save_events
		if method == "scene.save_as" or DisplayServer.get_name() == "headless":
			# save_scene() always requests a thumbnail, which errors on the dummy
			# renderer. The public save-as API can explicitly suppress that preview.
			EditorInterface.save_scene_as(path, false)
		else:
			var err := EditorInterface.save_scene()
			if err != OK:
				return Wire.failure("FILE_ACCESS_DENIED", "Editor save failed: " + error_string(err))
		if save_events == previous_save_events or not FileAccess.file_exists(path) or root.scene_file_path != path:
			return Wire.failure("FILE_ACCESS_DENIED", "Editor did not save the requested scene.")
		fingerprints[root.get_instance_id()] = FileAccess.get_sha256(path)
		return success({"scene_path": path, "saved": true})
	return Wire.failure("UNSUPPORTED_OPERATION", "Unknown scene operation.")

static func success(result: Dictionary) -> Dictionary:
	return {"ok": true, "result": result}
