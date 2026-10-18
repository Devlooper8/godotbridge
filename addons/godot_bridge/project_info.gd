extends SceneTree

func _initialize() -> void:
	var main_scene: String = ProjectSettings.get_setting("application/run/main_scene", "")
	if main_scene.begins_with("uid://"):
		var id := ResourceUID.text_to_id(main_scene)
		main_scene = ResourceUID.get_id_path(id) if ResourceUID.has_id(id) else ""
	print("GODOTBRIDGE_RESULT=" + JSON.stringify({"project": ProjectSettings.globalize_path("res://"),
		"project_name": ProjectSettings.get_setting("application/config/name", ""),
		"main_scene": main_scene, "godot_version": Engine.get_version_info().string,
		"connected": false, "source": "headless_project_settings", "capabilities": []}))
	quit()
