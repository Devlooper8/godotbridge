@tool
extends RefCounted

const Wire = preload("transport_server.gd")
const Codec = preload("codec.gd")
const Nodes = preload("node_manager.gd")
var plugin: EditorPlugin

func _init(owner_plugin: EditorPlugin) -> void:
	plugin = owner_plugin

func camera_info() -> Dictionary:
	if DisplayServer.get_name() == "headless":
		return Wire.failure("CAPTURE_UNAVAILABLE", "Headless editors have no visible 3D viewport.")
	var viewport := EditorInterface.get_editor_viewport_3d(0)
	var camera := viewport.get_camera_3d()
	if camera == null:
		return Wire.failure("CAPTURE_UNAVAILABLE", "No active editor 3D camera.")
	return {"ok": true, "result": {"transform": Codec.encode(camera.global_transform),
		"fov": camera.fov, "near": camera.near, "far": camera.far, "projection": camera.projection,
		"viewport_size": [viewport.size.x, viewport.size.y], "control": "Use preview viewpoints; editor camera is read-only."}}

func capture(params: Dictionary) -> Dictionary:
	if DisplayServer.get_name() == "headless":
		return Wire.failure("CAPTURE_UNAVAILABLE", "Headless rendering has no image. Run a graphical editor for screenshots.")
	var root := EditorInterface.get_edited_scene_root()
	if root == null:
		return Wire.failure("SCENE_NOT_OPEN", "Open a scene before capturing.")
	var viewport: SubViewport
	var preview: bool = params.method == "preview"
	var warnings: Array[String] = []
	var camera_data := {}
	if preview:
		viewport = SubViewport.new()
		viewport.size = Vector2i(params.width, params.height)
		viewport.world_3d = World3D.new()
		viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
		viewport.transparent_bg = false
		var environment := Environment.new()
		environment.background_mode = Environment.BG_COLOR
		environment.background_color = Color(0.08, 0.1, 0.15)
		environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
		environment.ambient_light_color = Color(0.75, 0.8, 0.9)
		environment.ambient_light_energy = 0.45
		viewport.world_3d.environment = environment
		plugin.add_child(viewport)
		var pending: Array[Node] = [root]
		var count := 0
		while not pending.is_empty():
			var source: Node = pending.pop_back()
			count += 1
			if count > 10000:
				viewport.queue_free()
				return Wire.failure("CAPTURE_UNAVAILABLE", "Preview exceeds 10,000-node limit.")
			pending.append_array(source.get_children())
			var copy: Node3D
			if source is MeshInstance3D and source.is_visible_in_tree() and source.mesh != null:
				if source.mesh.get_script() != null or source.skin != null:
					warnings.append("Skipped scripted or skinned mesh: " + String(root.get_path_to(source)))
					continue
				copy = MeshInstance3D.new()
				copy.mesh = source.mesh
				copy.material_override = source.material_override
				for surface in source.get_surface_override_material_count():
					copy.set_surface_override_material(surface, source.get_surface_override_material(surface))
			elif source is Light3D and source.is_visible_in_tree():
				copy = ClassDB.instantiate(source.get_class())
				for key in ["light_color", "light_energy", "shadow_enabled"]:
					copy.set(key, source.get(key))
				if source is OmniLight3D:
					copy.omni_range = source.omni_range
				elif source is SpotLight3D:
					copy.spot_range = source.spot_range
					copy.spot_angle = source.spot_angle
			if copy:
				viewport.add_child(copy)
				copy.global_transform = source.global_transform
		var camera := Camera3D.new()
		viewport.add_child(camera)
		var target := Nodes.vector3(params.target)
		var distance: float = params.distance
		var position := Nodes.vector3(params.position)
		match params.viewpoint:
			"top": position = target + Vector3(0, distance, 0)
			"front": position = target + Vector3(0, 0, distance)
			"side": position = target + Vector3(distance, 0, 0)
			"perspective": position = target + Vector3(0.6, 0.52, 0.72).normalized() * distance
		if position.distance_to(target) < 0.001:
			viewport.queue_free()
			return Wire.failure("INVALID_ARGUMENT", "Camera position must differ from target.")
		camera.position = position
		var direction := (target - position).normalized()
		camera.look_at(target, Vector3.FORWARD if absf(direction.dot(Vector3.UP)) > 0.99 else Vector3.UP)
		camera.current = true
		if params.viewpoint in ["top", "front", "side"]:
			camera.projection = Camera3D.PROJECTION_ORTHOGONAL
			camera.size = distance
		camera_data = {"transform": Codec.encode(camera.transform), "viewpoint": params.viewpoint, "fov": camera.fov}
		warnings.append("Geometry-only preview: scripts, animation, particles, world environments and runtime logic are not reproduced.")
	else:
		EditorInterface.set_main_screen_editor("3D")
		viewport = EditorInterface.get_editor_viewport_3d(params.viewport)
		if viewport == null:
			return Wire.failure("CAPTURE_UNAVAILABLE", "Requested editor viewport is unavailable.")
		var camera := viewport.get_camera_3d()
		if camera:
			camera_data = {"transform": Codec.encode(camera.global_transform), "fov": camera.fov}
	# Idle editors do not guarantee frame_post_draw. Yield to process scene changes,
	# then use the public force_draw API so captures cannot wait indefinitely.
	await plugin.get_tree().process_frame
	RenderingServer.force_draw(false)
	await plugin.get_tree().process_frame
	RenderingServer.force_draw(false)
	var image := viewport.get_texture().get_image()
	if preview:
		viewport.queue_free()
	if image == null or image.is_empty():
		return Wire.failure("CAPTURE_UNAVAILABLE", "Renderer returned no pixels.")
	var native_size := [image.get_width(), image.get_height()]
	if image.get_width() != params.width or image.get_height() != params.height:
		image.resize(params.width, params.height, Image.INTERPOLATE_LANCZOS)
	var directory := "res://.godot/godotbridge/captures"
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(directory))
	var path := directory.path_join(Crypto.new().generate_random_bytes(12).hex_encode() + ".png")
	var err := image.save_png(path)
	if err != OK:
		return Wire.failure("FILE_ACCESS_DENIED", "Could not save screenshot: " + error_string(err))
	return {"ok": true, "result": {"artifact_path": ProjectSettings.globalize_path(path), "scene_path": root.scene_file_path,
		"width": image.get_width(), "height": image.get_height(), "native_size": native_size,
		"capture_method": "geometry_preview" if preview else "editor_viewport", "viewpoint": camera_data,
		"warnings": warnings, "status": "complete"}}
