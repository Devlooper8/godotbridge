@tool
extends RefCounted

const Wire = preload("transport_server.gd")
const Codec = preload("codec.gd")
const Scenes = preload("scene_manager.gd")
var undo: EditorUndoRedoManager
var root: Node
var error := {}
var base_cache := {} # root instance id -> parsed base-scene info, see base_info().
var memo := {}
var allow_tool := false # Per-request opt-in to mutate nodes whose script is @tool.

func _init(manager: EditorUndoRedoManager) -> void:
	undo = manager

func resolve(path: String) -> Node:
	if path.is_empty() or path.begins_with("/") or ":" in path or "\\" in path or "%" in path or ".." in path.split("/"):
		error = Wire.failure("INVALID_NODE_PATH", "Use a relative node path under the edited root; '.' selects the root.")
		return null
	var node := root.get_node_or_null(NodePath(path))
	if node == null:
		error = Wire.failure("NODE_NOT_FOUND", "Node does not exist: " + path)
	return node

## mode: "edit" (properties/transform), "child" (add a child) or "structure" (delete, rename, reparent, duplicate).
## The editor's own rules apply: a scene instance is one node owned by the edited root whose internals are
## owned by the instance. Those internals are only editable through "editable children".
func editable(node: Node, mode: String = "edit", subtree: bool = false) -> bool:
	if mode == "structure" and is_inherited(node):
		error = Wire.failure("READ_ONLY_RESOURCE", "Node is inherited from the base scene and cannot be deleted, renamed, reparented or duplicated; edit the base scene. " + base_info().get("reason", ""))
		return false
	if inside_instance(node):
		var host := instance_host(node)
		if mode == "structure":
			error = Wire.failure("READ_ONLY_RESOURCE", "Nodes inside a scene instance cannot be deleted, renamed, reparented or duplicated; edit the source scene.")
			return false
		if host == null or node.owner != host:
			error = Wire.failure("READ_ONLY_RESOURCE", "Unowned or nested-instance nodes are read-only; edit their source scene.")
			return false
		if not root.is_editable_instance(host):
			error = Wire.failure("READ_ONLY_RESOURCE", "Node is inside a scene instance; enable editable children on '%s' first." % root.get_path_to(host))
			return false
	# Non-@tool scripts only exist as placeholder instances in the editor: no setters, _ready or
	# _process run, so editing them is as safe as editing a built-in node.
	if is_tool_script(node) and not allow_tool:
		error = Wire.failure("READ_ONLY_RESOURCE", "Node has a @tool script that runs inside the editor; pass allow_tool_script to mutate it anyway.")
		return false
	if subtree and not allow_tool:
		# Removing or re-instantiating a subtree runs _exit_tree and _enter_tree/_ready of every @tool script in
		# it, including those inside scene instances, so the scan ignores ownership.
		for descendant in descendants(node):
			if is_tool_script(descendant):
				error = Wire.failure("READ_ONLY_RESOURCE", "The subtree contains a @tool script ('%s') that runs inside the editor; pass allow_tool_script to mutate it anyway." % root.get_path_to(descendant))
				return false
	return true

static func descendants(node: Node) -> Array[Node]:
	var out: Array[Node] = []
	var pending: Array[Node] = node.get_children()
	while not pending.is_empty():
		var current: Node = pending.pop_back()
		out.append(current)
		pending.append_array(current.get_children())
	return out

## Nodes of this subtree (including node) whose owner is the edited root, wherever they sit: that is exactly
## what Node.remove_child un-owns and what must be restored on re-attach.
func owned_nodes(node: Node) -> Array[Node]:
	var out: Array[Node] = []
	if node.owner == root:
		out.append(node)
	for descendant in descendants(node):
		if descendant.owner == root:
			out.append(descendant)
	return out

## Ownership of a new, never-attached subtree: unowned nodes belong to the scene, except below an instance root
## (whose unowned children are ambiguous). Anything owned by a scene instance stays out of this scene's file.
func fresh_nodes(node: Node) -> Array[Node]:
	var out: Array[Node] = [node]
	var instance := not node.scene_file_path.is_empty()
	for child in node.get_children():
		if child.owner == root or (child.owner == null and not instance):
			out.append_array(fresh_nodes(child))
	return out

## Duplication re-instantiates instances, which loses overrides and added children below them.
func has_instance_overrides(node: Node) -> bool:
	for candidate in [node] + descendants(node):
		if candidate != root and candidate.owner == root and not candidate.scene_file_path.is_empty():
			if root.is_editable_instance(candidate):
				return true
			for below in descendants(candidate):
				if below.owner == root:
					return true
	return false

## Inherited-scene support. The editor keeps no public record of which nodes came from the base scene
## (Node.get_scene_inherited_state() is not exposed to scripts), so the edited scene's saved file is the
## source: every node path found in its PackedScene's base-scene state chain is inherited. Properties and
## new children of those nodes are editable (the editor stores them as overrides); deleting, renaming,
## reparenting or duplicating them would corrupt the inheritance and is rejected.
## Conservative rules: a path in the base set is inherited even if the node is in fact derived-only, and
## if the base chain changed on disk since first use (the open tree can no longer be matched to it), or
## the file cannot be loaded, every node is treated as inherited. Unsaved scenes have no file and are
## treated as not inherited.
## Called when the editor switches or opens a scene: fixes the base-scene baseline at open time and drops
## cache entries of closed scenes.
func track(scene_root: Node) -> void:
	for id in base_cache.keys():
		if not is_instance_id_valid(id):
			base_cache.erase(id)
	if scene_root:
		var previous := root
		root = scene_root
		base_info()
		root = previous

func is_inherited(node: Node) -> bool:
	var info := base_info()
	if not info.get("inherited", false):
		return false
	if info.get("unknown", false):
		return true
	var path := String(root.get_path_to(node))
	return info.paths.has(path)

func base_info() -> Dictionary:
	var frame := Engine.get_process_frames()
	var id := root.get_instance_id()
	if memo.get("frame") == frame and memo.get("id") == id:
		return memo.info
	var info := _base_info(id)
	memo = {"frame": frame, "id": id, "info": info}
	return info

func _base_info(id: int) -> Dictionary:
	var path := root.scene_file_path
	var entry: Dictionary = base_cache.get(id, {})
	if path.is_empty():
		# An unsaved "New Inherited Scene" has no file, but packing the live root records the base chain the
		# editor loaded it with (the same data the editor saves), which is also exactly the open tree's base.
		if entry.is_empty():
			var packed := PackedScene.new()
			if packed.pack(root) == OK:
				entry = _from_state(packed.get_state())
			else:
				entry = {"inherited": true, "unknown": true, "files": {}, "reason": "The unsaved scene could not be packed to find its base scene."}
			entry.unsaved = true
			base_cache[id] = entry
		return entry
	var key := fingerprint(path)
	if entry.is_empty() or entry.get("key") != key:
		var fresh := _read_base(path)
		fresh.key = key
		# The first-seen base fingerprints stand for the tree the editor loaded; later differences mean it is outdated.
		fresh.first_files = entry.get("first_files", fresh.get("files", {}))
		fresh.stale = entry.get("stale", false) or (entry.has("first_files") and fresh.get("files", {}).keys() != entry.first_files.keys())
		entry = fresh
		base_cache[id] = entry
	if entry.get("inherited", false) and not entry.get("stale", false):
		for file in entry.first_files:
			if fingerprint(file) != entry.first_files[file]:
				entry.stale = true
				break
	if entry.get("inherited", false) and entry.stale:
		return {"inherited": true, "unknown": true, "reason": "The base scene changed on disk after this scene was opened; reopen the scene."}
	return entry

func _read_base(path: String) -> Dictionary:
	var scene = ResourceLoader.load(path, "PackedScene", ResourceLoader.CACHE_MODE_IGNORE)
	if not scene is PackedScene:
		return {"inherited": true, "unknown": true, "files": {}, "reason": "The scene file could not be loaded to find its base scene."}
	return _from_state(scene.get_state())

func _from_state(state: SceneState) -> Dictionary:
	if state.get_base_scene_state() == null:
		return {"inherited": false}
	var paths := {}
	var files := {}
	var current: SceneState = state
	for depth in 32:
		var base := current.get_base_scene_state()
		if base == null:
			break
		var source = current.get_node_instance(0)
		if source is PackedScene and not source.resource_path.is_empty():
			files[source.resource_path] = fingerprint(source.resource_path)
		for index in base.get_node_count():
			var node_path := String(base.get_node_path(index))
			paths[node_path.substr(2) if node_path.begins_with("./") else node_path] = true
		current = base
	return {"inherited": true, "paths": paths, "files": files}

static func fingerprint(path: String) -> String:
	var file := FileAccess.open(path, FileAccess.READ)
	return "" if file == null else "%d:%d" % [FileAccess.get_modified_time(path), file.get_length()]

func inside_instance(node: Node) -> bool:
	return node != root and node.owner != root

## Nearest ancestor that is an instance root of the edited scene, or null.
func instance_host(node: Node) -> Node:
	var ancestor := node.get_parent()
	while ancestor and ancestor != root:
		if ancestor.owner == root and not ancestor.scene_file_path.is_empty():
			return ancestor
		ancestor = ancestor.get_parent()
	return null

func is_instance_root(node: Node) -> bool:
	return node != root and node.owner == root and not node.scene_file_path.is_empty()

static func is_tool_script(node: Node) -> bool:
	var script: Script = node.get_script()
	return script != null and script.is_tool()

static func script_variables(node: Node) -> Dictionary:
	return Codec.script_variables(node)

func valid_name(parent: Node, value: String, exclude: Node = null) -> bool:
	if value.is_empty() or value.validate_node_name() != value or value in [".", ".."] or value.begins_with("@"):
		error = Wire.failure("INVALID_ARGUMENT", "Invalid node name.")
		return false
	for sibling in parent.get_children():
		if sibling != exclude and String(sibling.name) == value:
			error = Wire.failure("INVALID_ARGUMENT", "A sibling already has that name.")
			return false
	return true

func describe(node: Node) -> Dictionary:
	var result := {"node_path": String(root.get_path_to(node)), "name": String(node.name),
		"class": node.get_class(), "instance_id": str(node.get_instance_id()),
		"scene_file_path": node.scene_file_path, "selected": node in EditorInterface.get_selection().get_selected_nodes(),
		"script": node.get_script().resource_path if node.get_script() else null, "tool_script": is_tool_script(node),
		"groups": node.get_groups().filter(func(group): return not String(group).begins_with("_")),
		"instance": {"is_instance_root": is_instance_root(node), "editable_children": is_instance_root(node) and root.is_editable_instance(node),
			"inside_instance": inside_instance(node)}, "inherited": is_inherited(node)}
	if node is Node3D:
		result.merge({"position": Codec.encode(node.position), "rotation_degrees": Codec.encode(node.rotation_degrees),
			"scale": Codec.encode(node.scale), "local_transform": Codec.encode(node.transform),
			"global_transform": Codec.encode(node.global_transform), "visible": node.visible,
			"visible_in_tree": node.is_visible_in_tree()})
	if node is MeshInstance3D:
		result.mesh = Codec.encode(node.mesh)
		result.material_override = Codec.encode(node.material_override)
		result.local_aabb = Codec.encode(node.get_aabb())
		result.global_aabb = Codec.encode(node.global_transform * node.get_aabb())
	if node is Camera3D:
		result.camera = {"fov": node.fov, "near": node.near, "far": node.far, "current": node.current}
	if node is Light3D:
		result.light = {"color": Codec.encode(node.light_color), "energy": node.light_energy}
	if node is CollisionShape3D:
		result.shape = Codec.encode(node.shape)
	return result

func tree() -> Dictionary:
	var nodes: Array[Dictionary] = []
	var pending: Array[Node] = [root]
	while not pending.is_empty():
		var node: Node = pending.pop_back()
		if nodes.size() >= 10000:
			return Wire.failure("UNSUPPORTED_OPERATION", "Scene exceeds the 10,000-node inspection limit.")
		nodes.append(describe(node))
		var children := node.get_children()
		children.reverse()
		pending.append_array(children)
	var history := undo.get_history_undo_redo(undo.get_object_history_id(root))
	return success({"scene_path": root.scene_file_path, "root": String(root.name), "nodes": nodes,
		"revision": history.get_version() if history else 0})

func handle(method: String, params: Dictionary) -> Dictionary:
	root = EditorInterface.get_edited_scene_root()
	error = {}
	allow_tool = params.get("allow_tool_script", false)
	if root == null:
		return Wire.failure("SCENE_NOT_OPEN", "Open or create a scene first.")
	if method == "scene.tree":
		return tree()
	if method == "editor.undo" or method == "editor.redo":
		if undo.is_committing_action():
			return Wire.failure("EDITOR_BUSY", "An editor action is being committed.")
		var history := undo.get_history_undo_redo(undo.get_object_history_id(root))
		if history == null:
			return success({"changed": false})
		var changed := history.undo() if method == "editor.undo" else history.redo()
		return success({"changed": changed})
	if method == "node.create":
		var parent := resolve(params.get("parent", "."))
		if parent == null or not editable(parent, "child") or not valid_name(parent, params.name):
			return error
		var node: Node = ClassDB.instantiate(params.get("type", "Node3D"))
		node.name = params.name
		return add_node(parent, node)
	if method == "node.instantiate":
		return instantiate(params)
	var node := resolve(params.get("path", "."))
	if node == null:
		return error
	if method == "node.inspect":
		return success(describe(node))
	if method in ["editor.select", "editor.focus"]:
		EditorInterface.get_selection().clear()
		EditorInterface.get_selection().add_node(node)
		EditorInterface.inspect_object(node)
		if method == "editor.focus":
			EditorInterface.set_main_screen_editor("3D")
		return success(describe(node))
	if method in ["node.properties", "node.get_property"]:
		var properties := []
		var script_vars := script_variables(node)
		for info in node.get_property_list():
			var from_script := script_vars.has(info.name)
			if info.name in Codec.NODE_PROPERTIES or from_script:
				properties.append({"name": info.name, "type": type_string(info.type), "value": Codec.encode(node.get(info.name)), "script": from_script})
		if method == "node.properties":
			return success({"node_path": params.get("path", "."), "properties": properties})
		for info in properties:
			if info.name == params.property:
				return success({"value": info.value})
		return Wire.failure("UNSUPPORTED_PROPERTY", "Property is not exposed for this node.")
	var structural := method in ["node.delete", "node.duplicate", "node.reparent", "node.rename"]
	if not editable(node, "structure" if structural else "edit", method in ["node.delete", "node.duplicate", "node.reparent"]):
		return error
	match method:
		"node.delete":
			if node == root:
				return Wire.failure("INVALID_ARGUMENT", "Cannot delete the scene root.")
			undo.create_action("GodotBridge: delete " + String(node.name), 0, root)
			undo.add_do_method(node.get_parent(), "remove_child", node)
			undo.add_undo_method(self, "_attach", node.get_parent(), node, root, node.get_index(), owned_nodes(node))
			undo.add_undo_reference(node)
			undo.commit_action()
			return success({"deleted": params.get("path", ".")})
		"node.duplicate":
			if node == root:
				return Wire.failure("INVALID_ARGUMENT", "Cannot duplicate the scene root into itself.")
			var node_name: String = params.get("name") if params.get("name") != null else String(node.name) + "Copy"
			if not valid_name(node.get_parent(), node_name):
				return error
			if has_instance_overrides(node):
				return Wire.failure("UNSUPPORTED_OPERATION", "Duplicating would drop the editable-children flag or children added below a scene instance; duplicate the instance without them or re-create it with node.instantiate.")
			# Keep scripts (placeholder-safe unless allow_tool_script), persistent signals, groups and instancing.
			var copy := node.duplicate(Node.DUPLICATE_SIGNALS | Node.DUPLICATE_GROUPS | Node.DUPLICATE_SCRIPTS | Node.DUPLICATE_USE_INSTANTIATION)
			copy.name = node_name
			return add_node(node.get_parent(), copy)
		"node.rename":
			if node == root:
				return Wire.failure("INVALID_ARGUMENT", "Cannot rename the scene root.")
			if not valid_name(node.get_parent(), params.name, node):
				return error
			return set_properties(node, {"name": params.name})
		"node.set_property":
			var info := {} if params.property in Codec.NODE_PROPERTIES else script_variables(node).get(params.property, {})
			if info.is_empty() and not params.property in Codec.NODE_PROPERTIES:
				return Wire.failure("UNSUPPORTED_PROPERTY", "Property is not allowlisted or an exported script variable.")
			var value := Codec.decode(params.value)
			if not value.ok or not (Codec.compatible(node, params.property, value.get("value")) if info.is_empty() else Codec.fits(info, "", value.get("value"))):
				return Wire.failure("INVALID_ARGUMENT", "Property value has the wrong type or unsupported resource configuration.")
			return set_properties(node, {params.property: value.value if info.is_empty() else Codec.coerce(info, value.value)})
		"node.set_transform":
			return set_transform(node, params)
		"node.set_editable_children":
			if not is_instance_root(node):
				return Wire.failure("INVALID_ARGUMENT", "Editable children apply to scene instance roots only.")
			var was_editable := root.is_editable_instance(node)
			undo.create_action("GodotBridge: editable children " + String(node.name), 0, root)
			undo.add_do_method(root, "set_editable_instance", node, params.editable)
			undo.add_undo_method(root, "set_editable_instance", node, was_editable)
			undo.commit_action()
			return success(describe(node))
		"node.reparent":
			var parent := resolve(params.parent)
			if parent == null or not editable(parent, "child"):
				return error
			if node == root or node == parent or node.is_ancestor_of(parent):
				return Wire.failure("INVALID_ARGUMENT", "Reparent would move the root or create a cycle.")
			if not valid_name(parent, String(node.name), node):
				return error
			var old_transform: Transform3D = node.transform if node is Node3D else Transform3D.IDENTITY
			var new_transform := old_transform
			if node is Node3D and params.get("keep_global", true):
				new_transform = node.global_transform
				if parent is Node3D and not node.top_level:
					if absf(parent.global_transform.basis.determinant()) < 0.000001:
						return Wire.failure("INVALID_ARGUMENT", "Cannot invert the new parent's singular transform.")
					new_transform = parent.global_transform.affine_inverse() * new_transform
			if not new_transform.is_finite():
				return Wire.failure("INVALID_ARGUMENT", "Reparent transform exceeds the engine's numeric range.")
			undo.create_action("GodotBridge: reparent", 0, root)
			var owned := owned_nodes(node)
			undo.add_do_method(self, "_move", node, parent, root, parent.get_child_count(), new_transform, owned)
			undo.add_undo_method(self, "_move", node, node.get_parent(), root, node.get_index(), old_transform, owned)
			undo.commit_action()
			return success(describe(node))
	return Wire.failure("UNSUPPORTED_OPERATION", "Unknown node operation.")

func instantiate(params: Dictionary) -> Dictionary:
	var parent := resolve(params.get("parent", "."))
	if parent == null or not editable(parent, "child"):
		return error
	var path: String = params.scene
	if not Scenes.safe_path(path):
		return Wire.failure("FILE_ACCESS_DENIED", "Use a res:// .tscn path without traversal or symlinks.")
	if not FileAccess.file_exists(path):
		return Wire.failure("SCENE_NOT_FOUND", "Scene file does not exist: " + path)
	var found := dependency_closure(path)
	var closure: Array = found.files
	if not found.complete:
		return Wire.failure("INVALID_ARGUMENT", "The scene has too many dependencies to verify for recursion and @tool scripts.")
	if path == root.scene_file_path or root.scene_file_path in closure:
		return Wire.failure("INVALID_ARGUMENT", "A scene cannot be instanced into itself, directly or through another scene.")
	if not allow_tool:
		for dependency in closure:
			if dependency.get_extension() in ["gd", "cs"]:
				var script = ResourceLoader.load(dependency)
				while script is Script:
					if script.is_tool():
						return Wire.failure("READ_ONLY_RESOURCE", "The scene uses a @tool script that would run in the editor; pass allow_tool_script to instance it anyway.")
					script = script.get_base_script()
	var packed = ResourceLoader.load(path, "PackedScene")
	if not packed is PackedScene or not packed.can_instantiate():
		return Wire.failure("SCENE_NOT_FOUND", "File is not an instantiable PackedScene.")
	var node: Node = packed.instantiate(PackedScene.GEN_EDIT_STATE_INSTANCE)
	if node == null:
		return Wire.failure("INTERNAL_ERROR", "Scene instantiation failed.")
	if params.get("name") != null:
		node.name = params.name
		if not valid_name(parent, params.name):
			node.free()
			return error
	else:
		var base := String(node.name)
		var index := 2
		while parent.has_node(NodePath(String(node.name))):
			node.name = base + str(index)
			index += 1
	return add_node(parent, node)

## Every res:// file reachable from start through ResourceLoader dependencies and, for scripts, their base-script
## chain and quoted res:// paths in the source (preload/load targets). "complete" is false when the 512-file
## cap was hit; callers must then fail closed.
static func dependency_closure(start: String) -> Dictionary:
	var seen := {start: true}
	var pending := [start]
	var regex := RegEx.create_from_string("[\"'](res://[^\"']+)[\"']")
	while not pending.is_empty():
		if seen.size() >= 512:
			return {"files": seen.keys(), "complete": false}
		var current: String = pending.pop_back()
		var found: Array[String] = []
		var extension := current.get_extension()
		if extension in ["tscn", "scn", "tres", "res"]:
			for entry in ResourceLoader.get_dependencies(current):
				var parts: PackedStringArray = entry.split("::")
				var dependency: String = parts[parts.size() - 1]
				# A uid survives moves, so it wins when the recorded path no longer exists.
				if parts[0].begins_with("uid://") and (dependency.is_empty() or not FileAccess.file_exists(dependency)):
					var id := ResourceUID.text_to_id(parts[0])
					dependency = ResourceUID.get_id_path(id) if ResourceUID.has_id(id) else dependency
				if not dependency.is_empty():
					found.append(dependency)
		elif extension == "gd" and FileAccess.file_exists(current):
			for match in regex.search_all(FileAccess.get_file_as_string(current)):
				found.append(match.get_string(1))
			var script = ResourceLoader.load(current)
			var base = script.get_base_script() if script is Script else null
			while base != null and not base.resource_path.is_empty():
				found.append(base.resource_path)
				base = base.get_base_script()
		for dependency in found:
			if not seen.has(dependency):
				seen[dependency] = true
				pending.append(dependency)
	return {"files": seen.keys(), "complete": true}

func add_node(parent: Node, node: Node) -> Dictionary:
	undo.create_action("GodotBridge: create " + String(node.name), 0, root)
	undo.add_do_method(self, "_attach", parent, node, root, -1, fresh_nodes(node))
	undo.add_undo_method(parent, "remove_child", node)
	undo.add_do_reference(node)
	undo.commit_action()
	return success(describe(node))

func set_properties(node: Node, values: Dictionary) -> Dictionary:
	undo.create_action("GodotBridge: edit " + String(node.name), 0, root)
	for key in values:
		undo.add_do_property(node, key, values[key])
		undo.add_undo_property(node, key, node.get(key))
	undo.commit_action()
	return success(describe(node))

func set_transform(node: Node, params: Dictionary) -> Dictionary:
	if not node is Node3D:
		return Wire.failure("UNSUPPORTED_NODE_TYPE", "Transforms require Node3D.")
	var world: bool = params.get("world", false)
	var transform: Transform3D = node.global_transform if world else node.transform
	var position: Vector3 = transform.origin
	var rotation: Vector3 = transform.basis.get_euler()
	var scale: Vector3 = transform.basis.get_scale()
	if params.get("position") != null:
		var vector := vector3(params.position)
		position = position + vector if params.get("translate", false) else vector
	if params.get("rotation") != null:
		rotation = vector3(params.rotation) * (PI / 180.0)
	if params.get("scale") != null:
		scale = vector3(params.scale)
		if minf(absf(scale.x), minf(absf(scale.y), absf(scale.z))) < 0.00001:
			return Wire.failure("INVALID_ARGUMENT", "Scale components must be nonzero.")
	var updated := Transform3D(Basis.from_euler(rotation).scaled_local(scale), position)
	if world and not node.top_level and node.get_parent_node_3d():
		if absf(node.get_parent_node_3d().global_transform.basis.determinant()) < 0.000001:
			return Wire.failure("INVALID_ARGUMENT", "Cannot invert the parent's singular transform.")
		updated = node.get_parent_node_3d().global_transform.affine_inverse() * updated
	if not updated.is_finite():
		return Wire.failure("INVALID_ARGUMENT", "Transform exceeds the engine's finite numeric range.")
	return set_properties(node, {"transform": updated})

func _attach(parent: Node, node: Node, scene_root: Node, index: int, owned: Array) -> void:
	parent.add_child(node)
	# remove_child cleared the owner of every node owned from outside the removed branch; restore exactly those.
	for member in owned:
		member.owner = scene_root
	if index >= 0:
		parent.move_child(node, mini(index, parent.get_child_count() - 1))

func _move(node: Node, parent: Node, scene_root: Node, index: int, transform: Transform3D, owned: Array) -> void:
	node.get_parent().remove_child(node)
	_attach(parent, node, scene_root, index, owned)
	if node is Node3D:
		node.transform = transform

static func vector3(value: Array) -> Vector3:
	return Vector3(value[0], value[1], value[2])

static func success(result: Dictionary) -> Dictionary:
	return {"ok": true, "result": result}
