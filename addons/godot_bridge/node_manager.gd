@tool
extends RefCounted

const Wire = preload("transport_server.gd")
const Codec = preload("codec.gd")
var undo: EditorUndoRedoManager
var root: Node
var error := {}

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

func editable(node: Node, subtree: bool = false) -> bool:
	if not root.scene_file_path.is_empty():
		var scene = ResourceLoader.load(root.scene_file_path, "PackedScene")
		if scene is PackedScene and scene.get_state().get_base_scene_state() != null:
			error = Wire.failure("READ_ONLY_RESOURCE", "Inherited scenes are read-only in this release; edit the base scene.")
			return false
	var ancestor := node
	while ancestor and ancestor != root:
		if ancestor.owner != root or not ancestor.scene_file_path.is_empty():
			error = Wire.failure("READ_ONLY_RESOURCE", "Scene instances and unowned nodes are read-only; edit their source scene.")
			return false
		ancestor = ancestor.get_parent()
	if node.get_script() != null:
		error = Wire.failure("READ_ONLY_RESOURCE", "Scripted nodes are read-only to avoid executing custom setters or lifecycle code.")
		return false
	if subtree:
		for child in node.get_children():
			if not editable(child, true):
				return false
	return true

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
		"scene_file_path": node.scene_file_path, "selected": node in EditorInterface.get_selection().get_selected_nodes()}
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
		if parent == null or not editable(parent) or not valid_name(parent, params.name):
			return error
		var node: Node = ClassDB.instantiate(params.get("type", "Node3D"))
		node.name = params.name
		return add_node(parent, node)
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
		for info in node.get_property_list():
			if info.name in Codec.NODE_PROPERTIES:
				properties.append({"name": info.name, "type": type_string(info.type), "value": Codec.encode(node.get(info.name))})
		if method == "node.properties":
			return success({"node_path": params.get("path", "."), "properties": properties})
		for info in properties:
			if info.name == params.property:
				return success({"value": info.value})
		return Wire.failure("UNSUPPORTED_PROPERTY", "Property is not exposed for this node.")
	if not editable(node, method in ["node.delete", "node.duplicate", "node.reparent"]):
		return error
	match method:
		"node.delete":
			if node == root:
				return Wire.failure("INVALID_ARGUMENT", "Cannot delete the scene root.")
			undo.create_action("GodotBridge: delete " + String(node.name), 0, root)
			undo.add_do_method(node.get_parent(), "remove_child", node)
			undo.add_undo_method(self, "_attach", node.get_parent(), node, root, node.get_index())
			undo.add_undo_reference(node)
			undo.commit_action()
			return success({"deleted": params.get("path", ".")})
		"node.duplicate":
			if node == root:
				return Wire.failure("INVALID_ARGUMENT", "Cannot duplicate the scene root into itself.")
			var node_name: String = params.get("name") if params.get("name") != null else String(node.name) + "Copy"
			if not valid_name(node.get_parent(), node_name):
				return error
			var copy := node.duplicate(0) # No scripts, connections, groups or instantiation.
			copy.name = node_name
			return add_node(node.get_parent(), copy)
		"node.rename":
			if not valid_name(node.get_parent(), params.name, node):
				return error
			return set_properties(node, {"name": params.name})
		"node.set_property":
			if not params.property in Codec.NODE_PROPERTIES:
				return Wire.failure("UNSUPPORTED_PROPERTY", "Property is not allowlisted.")
			var value := Codec.decode(params.value)
			if not value.ok or not Codec.compatible(node, params.property, value.get("value")):
				return Wire.failure("INVALID_ARGUMENT", "Property value has the wrong type or unsupported resource configuration.")
			return set_properties(node, {params.property: value.value})
		"node.set_transform":
			return set_transform(node, params)
		"node.reparent":
			var parent := resolve(params.parent)
			if parent == null or not editable(parent):
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
			undo.add_do_method(self, "_move", node, parent, root, parent.get_child_count(), new_transform)
			undo.add_undo_method(self, "_move", node, node.get_parent(), root, node.get_index(), old_transform)
			undo.commit_action()
			return success(describe(node))
	return Wire.failure("UNSUPPORTED_OPERATION", "Unknown node operation.")

func add_node(parent: Node, node: Node) -> Dictionary:
	undo.create_action("GodotBridge: create " + String(node.name), 0, root)
	undo.add_do_method(self, "_attach", parent, node, root, -1)
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

func _attach(parent: Node, node: Node, scene_root: Node, index: int) -> void:
	parent.add_child(node)
	_own(node, scene_root)
	if index >= 0:
		parent.move_child(node, mini(index, parent.get_child_count() - 1))

func _own(node: Node, scene_root: Node) -> void:
	node.owner = scene_root
	for child in node.get_children():
		_own(child, scene_root)

func _move(node: Node, parent: Node, scene_root: Node, index: int, transform: Transform3D) -> void:
	node.get_parent().remove_child(node)
	_attach(parent, node, scene_root, index)
	if node is Node3D:
		node.transform = transform

static func vector3(value: Array) -> Vector3:
	return Vector3(value[0], value[1], value[2])

static func success(result: Dictionary) -> Dictionary:
	return {"ok": true, "result": result}
