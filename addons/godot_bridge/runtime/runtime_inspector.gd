extends RefCounted
## Live-node inspection inside the played game, used by bridge_runtime.gd. Mirrors the editor-side node
## rules: relative paths under the running scene, allowlisted properties and exported script variables
## only, typed values through codec.gd. Changes are runtime-only and never saved.

const Codec = preload("../codec.gd")
const BRIDGE_DIR := "res://addons/godot_bridge/"
const MAX_VARIABLES := 200
const MAX_STRING := 2000
const MAX_TREE_NODES := 5000 # 10,000 nodes overflowed the debugger channel in testing.

static func failure(code: String, message: String) -> Dictionary:
	return {"ok": false, "error": {"code": code, "message": message}}

static func success(result: Dictionary) -> Dictionary:
	return {"ok": true, "result": result}

## Same path rules as node_manager.resolve; "." is the running scene's root.
static func resolve(root: Node, path: String) -> Variant:
	if path.is_empty() or path.begins_with("/") or ":" in path or "\\" in path or "%" in path or ".." in path.split("/"):
		return failure("INVALID_NODE_PATH", "Use a relative node path under the running scene root; '.' selects the root.")
	var node := root.get_node_or_null(NodePath(path))
	if node == null:
		return failure("NODE_NOT_FOUND", "Node does not exist: " + path)
	return node

static func describe(root: Node, node: Node) -> Dictionary:
	var script: Script = node.get_script()
	var result := {"node_path": String(root.get_path_to(node)), "name": String(node.name),
		"class": node.get_class(), "instance_id": str(node.get_instance_id()),
		"scene_file_path": node.scene_file_path, "script": script.resource_path if script else null,
		"groups": node.get_groups().filter(func(group): return not String(group).begins_with("_")),
		"child_count": node.get_child_count()}
	if node is Node3D:
		result.merge({"position": Codec.encode(node.position), "rotation_degrees": Codec.encode(node.rotation_degrees),
			"scale": Codec.encode(node.scale), "local_transform": Codec.encode(node.transform),
			"global_transform": Codec.encode(node.global_transform), "visible": node.visible,
			"visible_in_tree": node.is_visible_in_tree()})
	return result

static func tree(root: Node, params: Dictionary) -> Dictionary:
	var start = resolve(root, params.get("path", "."))
	if start is Dictionary:
		return start
	var limit := clampi(int(params.get("max_nodes", 2000)), 1, MAX_TREE_NODES)
	var nodes: Array[Dictionary] = []
	var pending: Array[Node] = [start]
	var truncated := false
	while not pending.is_empty():
		if nodes.size() >= limit:
			truncated = true
			break
		var node: Node = pending.pop_back()
		nodes.append(describe(root, node))
		var children := node.get_children()
		children.reverse()
		pending.append_array(children)
	return success({"scene_path": root.scene_file_path, "root": String(root.name), "nodes": nodes,
		"truncated": truncated, "frame": Engine.get_process_frames()})

static func properties(root: Node, node: Node) -> Array:
	var result := []
	var script_vars := Codec.script_variables(node)
	for info in node.get_property_list():
		var from_script := script_vars.has(info.name)
		if info.name in Codec.NODE_PROPERTIES or from_script:
			result.append({"name": info.name, "type": type_string(info.type), "value": Codec.encode(node.get(info.name)), "script": from_script})
	return result

static func handle(root: Node, command: String, params: Dictionary) -> Dictionary:
	var node = resolve(root, params.get("path", "."))
	if node is Dictionary:
		return node
	match command:
		"inspect":
			return success(describe(root, node))
		"properties":
			return success({"node_path": params.get("path", "."), "properties": properties(root, node)})
		"get_property":
			for info in properties(root, node):
				if info.name == params.get("property"):
					return success({"value": info.value, "type": info.type, "script": info.script})
			return failure("UNSUPPORTED_PROPERTY", "Property is not exposed for this node.")
		"set_property":
			var key = params.get("property")
			if not key is String:
				return failure("INVALID_ARGUMENT", "A property name is required.")
			var info := {} if key in Codec.NODE_PROPERTIES else Codec.script_variables(node).get(key, {})
			if info.is_empty() and not key in Codec.NODE_PROPERTIES:
				return failure("UNSUPPORTED_PROPERTY", "Property is not allowlisted or an exported script variable.")
			var value := Codec.decode(params.get("value"))
			if not value.ok or not (Codec.compatible(node, key, value.get("value")) if info.is_empty() else Codec.fits(info, "", value.get("value"))):
				return failure("INVALID_ARGUMENT", "Property value has the wrong type or unsupported resource configuration.")
			node.set(key, value.value if info.is_empty() else Codec.coerce(info, value.value))
			return success({"node_path": params.get("path", "."), "property": key, "value": Codec.encode(node.get(key))})
	return failure("UNSUPPORTED_OPERATION", "Unknown runtime operation: " + command)

## Script frames of the stopped game, innermost first. Called from a debugger message handler, so the bridge's
## own handler frames sit on top of the stack; they are recognised by their script path and dropped.
static func user_frames() -> Array:
	var frames := []
	for backtrace in Engine.capture_script_backtraces(true):
		for index in backtrace.get_frame_count():
			if not backtrace.get_frame_file(index).begins_with(BRIDGE_DIR):
				frames.append({"backtrace": backtrace, "index": index})
	return frames

static func encode_value(value: Variant) -> Variant:
	var encoded = Codec.encode(value)
	if encoded is String and encoded.length() > MAX_STRING:
		return {"type": "String", "truncated": true, "value": encoded.left(MAX_STRING)}
	if encoded is Dictionary and encoded.get("supported", true) == false:
		encoded.repr = str(value).left(MAX_STRING)
	return encoded

static func stack() -> Dictionary:
	var frames := []
	for entry in user_frames():
		var backtrace: ScriptBacktrace = entry.backtrace
		frames.append({"index": frames.size(), "file": backtrace.get_frame_file(entry.index),
			"line": backtrace.get_frame_line(entry.index), "function": backtrace.get_frame_function(entry.index)})
		if frames.size() >= 100:
			break
	return success({"frames": frames})

static func variables(params: Dictionary) -> Dictionary:
	var frames := user_frames()
	var frame := int(params.get("frame", 0))
	if frame < 0 or frame >= frames.size():
		return failure("INVALID_ARGUMENT", "No such stack frame: %d (the stopped game has %d script frames)." % [frame, frames.size()])
	var backtrace: ScriptBacktrace = frames[frame].backtrace
	var index: int = frames[frame].index
	var scope: String = params.get("scope", "locals")
	var count := 0
	match scope:
		"locals":
			count = backtrace.get_local_variable_count(index)
		"members":
			count = backtrace.get_member_variable_count(index)
		"globals":
			count = backtrace.get_global_variable_count()
		_:
			return failure("INVALID_ARGUMENT", "Scope must be locals, members or globals.")
	var result := []
	for variable in mini(count, MAX_VARIABLES):
		match scope:
			"locals":
				result.append({"name": backtrace.get_local_variable_name(index, variable), "value": encode_value(backtrace.get_local_variable_value(index, variable))})
			"members":
				result.append({"name": backtrace.get_member_variable_name(index, variable), "value": encode_value(backtrace.get_member_variable_value(index, variable))})
			_:
				result.append({"name": backtrace.get_global_variable_name(variable), "value": encode_value(backtrace.get_global_variable_value(variable))})
	return success({"frame": frame, "scope": scope, "variables": result, "truncated": count > MAX_VARIABLES})
