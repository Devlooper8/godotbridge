extends SceneTree
## Optional bridge-managed runtime: actual gameplay SceneTree and viewport.
## The only IPC command accepted here is capture into this run's private directory.

var run_directory := ""
var last_poll := 0

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2 or not args[0].begins_with("res://") or not args[1].begins_with("res://.godot/godotbridge/game/"):
		push_error("Invalid GodotBridge runtime arguments")
		quit(2)
		return
	run_directory = args[1]
	call_deferred("_start_scene", args[0])

func _start_scene(path: String) -> void:
	var err := change_scene_to_file(path)
	if err != OK:
		push_error("GodotBridge could not run scene: " + error_string(err))
		quit(1)

func _process(_delta: float) -> bool:
	# Unscaled time: a game that sets Engine.time_scale = 0 would otherwise never service a capture.
	var now := Time.get_ticks_msec()
	if now - last_poll < 100:
		return false
	last_poll = now
	var request := run_directory.path_join("capture.request")
	if FileAccess.file_exists(request):
		DirAccess.remove_absolute(ProjectSettings.globalize_path(request))
		var result := {}
		if DisplayServer.get_name() == "headless":
			result = {"ok": false, "error": {"code": "CAPTURE_UNAVAILABLE", "message": "Headless games have no visible viewport."}}
		else:
			RenderingServer.force_draw(false)
			var image := root.get_texture().get_image()
			if image == null or image.is_empty():
				result = {"ok": false, "error": {"code": "CAPTURE_UNAVAILABLE", "message": "Runtime viewport returned no pixels."}}
			else:
				var err := image.save_png(run_directory.path_join("capture.png"))
				result = {"ok": err == OK, "width": image.get_width(), "height": image.get_height(),
					"capture_method": "runtime_viewport"}
				if err != OK:
					result.error = {"code": "FILE_ACCESS_DENIED", "message": error_string(err)}
		var file := FileAccess.open(run_directory.path_join("capture.json"), FileAccess.WRITE)
		if file:
			file.store_string(JSON.stringify(result))
			file.close()
	return false
