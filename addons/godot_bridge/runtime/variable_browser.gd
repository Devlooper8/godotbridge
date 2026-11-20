extends RefCounted
## Lazy, path-based browsing of the variables of a stopped game (used by runtime_inspector.gd).
## Nothing is retained between calls: every request walks its path from freshly captured roots, so a path that
## no longer resolves is a clear error rather than a stale handle. Replies are bounded by paging, an entry
## budget and string limits. Scripts are never executed, because that would run user code inside the debugger
## break (and a `breakpoint` there re-enters the debugger and wedges the game). Script properties that have a
## custom getter are reported as `unread`. Objects whose script defines `_get`, `_get_property_list` or
## `_validate_property` carry `hooks` on their summary: they are listed from ClassDB and the script API
## instead of get_property_list(), so properties those hooks would add are not listed, and the engine's
## native property validation does not apply (order and hidden properties can differ from the live list).

const Codec = preload("../codec.gd")
const HOOKS := ["_get", "_get_property_list", "_validate_property"]
const UNVERIFIED := "unverified" # `hooks` entry for a script that cannot be checked (not GDScript)
const REASON_GETTER := "custom getter: reading it would run script code"
const REASON_SOURCE := "script source unavailable: inner class whose owning script was not found among loaded scripts, or a runtime-created or non-GDScript script"
const MAX_TREE_NODES := 5000 # as in runtime_inspector.gd: bounds the owner search of a huge tree
const MAX_CANDIDATES := 2000
const MAX_INNER_DEPTH := 16
const MAX_STRING := 2000
const DEFAULT_LIMIT := 100
const MAX_LIMIT := 200
const INLINE_LIMIT := 20
const MAX_DEPTH := 2
const MAX_ENTRIES := 500 # entries (including inlined ones) in one reply
const MAX_BYTES := 100000 # approximate characters of scalar text in one reply
const MAX_PATH := 32
const PACKED := [TYPE_PACKED_BYTE_ARRAY, TYPE_PACKED_INT32_ARRAY, TYPE_PACKED_INT64_ARRAY,
	TYPE_PACKED_FLOAT32_ARRAY, TYPE_PACKED_FLOAT64_ARRAY, TYPE_PACKED_STRING_ARRAY,
	TYPE_PACKED_VECTOR2_ARRAY, TYPE_PACKED_VECTOR3_ARRAY, TYPE_PACKED_COLOR_ARRAY,
	TYPE_PACKED_VECTOR4_ARRAY]
const SKIPPED_USAGE := PROPERTY_USAGE_CATEGORY | PROPERTY_USAGE_GROUP | PROPERTY_USAGE_SUBGROUP
const LISTED_USAGE := PROPERTY_USAGE_EDITOR | PROPERTY_USAGE_STORAGE | PROPERTY_USAGE_SCRIPT_VARIABLE

static func fail(code: String, message: String) -> Dictionary:
	return {"ok": false, "error": {"code": code, "message": message}}

## `roots` is an array of {name, value}. Returns {ok, ...} like the other inspector handlers.
static func browse(roots: Array, params: Dictionary) -> Dictionary:
	var path: Array = params.get("path") if params.get("path") != null else []
	var offset := maxi(int(params.get("offset", 0)), 0)
	var limit := clampi(int(params.get("limit", DEFAULT_LIMIT)), 1, MAX_LIMIT)
	var depth := clampi(int(params.get("depth", 0)), 0, MAX_DEPTH)
	# `hooks` and `owners` are per-call caches (object id -> hook names, inner script id -> owner sources).
	var ctx := {"left": MAX_ENTRIES, "bytes": 0, "exhausted": false, "roots": roots, "hooks": {}, "owners": null}
	var result := {"offset": offset, "limit": limit}
	var page: Dictionary
	if path.is_empty():
		page = _page_roots(roots, offset, limit, depth, ctx)
		result.variables = page.items
	else:
		var walked := _walk(roots, path, ctx)
		if not walked.ok:
			return walked
		var target: Variant = walked.value
		result.path = path
		result.target = _entry(target, 0, ctx, [])
		page = _page_children(target, offset, limit, depth, ctx, [target])
		result.children = page.items
	result.total = page.total
	result.truncated = page.truncated
	result.budget_exhausted = ctx.exhausted
	return {"ok": true, "result": result}

static func _page_roots(roots: Array, offset: int, limit: int, depth: int, ctx: Dictionary) -> Dictionary:
	var items := []
	for i in range(offset, mini(roots.size(), offset + limit)):
		if not _take(ctx):
			break
		var item := _entry(roots[i].value, depth, ctx, [])
		item.name = roots[i].name
		items.append(item)
	return {"items": items, "total": roots.size(), "truncated": offset + items.size() < roots.size()}

static func _take(ctx: Dictionary) -> bool:
	if ctx.left <= 0 or ctx.bytes > MAX_BYTES:
		ctx.exhausted = true
		return false
	ctx.left -= 1
	return true

static func _walk(roots: Array, path: Array, ctx: Dictionary) -> Dictionary:
	if path.size() > MAX_PATH or not path[0] is String:
		return fail("INVALID_ARGUMENT", "A path starts with a variable name and has at most %d segments." % MAX_PATH)
	var current: Variant
	var found := false
	for root in roots:
		if root.name == path[0]:
			current = root.value
			found = true
			break
	if not found:
		var names := []
		for root in roots.slice(0, 20):
			names.append(root.name)
		return fail("VARIABLE_NOT_FOUND", "No variable named %s in this frame and scope (first names: %s)." % [path[0], ", ".join(names)])
	for i in range(1, path.size()):
		var segment: Variant = path[i]
		var where := "at path segment %d" % i
		if not segment is Dictionary:
			return fail("INVALID_ARGUMENT", "Path segments after the first are {\"index\": n} or {\"property\": name}.")
		if segment.has("index"):
			var index := int(segment.index)
			var kind := typeof(current)
			if kind == TYPE_DICTIONARY:
				if index < 0 or index >= current.size():
					return fail("VARIABLE_NOT_FOUND", "Dictionary has %d entries, no entry %d (%s)." % [current.size(), index, where])
				current = current[current.keys()[index]]
			elif kind == TYPE_ARRAY or kind in PACKED:
				if index < 0 or index >= current.size():
					return fail("VARIABLE_NOT_FOUND", "Array has %d elements, no element %d (%s)." % [current.size(), index, where])
				current = current[index]
			else:
				return fail("VARIABLE_NOT_FOUND", "A %s has no indexed children (%s)." % [type_string(kind), where])
		elif segment.has("property"):
			if typeof(current) != TYPE_OBJECT or not is_instance_valid(current):
				return fail("VARIABLE_NOT_FOUND", "Not a live object (%s)." % where)
			var wanted := String(segment.property)
			var property: Dictionary = {}
			for candidate in _properties(current, ctx):
				if candidate.name == wanted:
					property = candidate
					break
			if property.is_empty():
				return fail("VARIABLE_NOT_FOUND", "%s has no listed property %s (%s)." % [current.get_class(), wanted, where])
			if property.unread:
				return fail("UNSUPPORTED_OPERATION", "Property %s was not read, it would run script code in the debugger (%s)." % [wanted, property.reason])
			current = _read(current, property)
		else:
			return fail("INVALID_ARGUMENT", "Path segments after the first are {\"index\": n} or {\"property\": name}.")
	return {"ok": true, "value": current}

## One value: type, class, count, expandable and the encoded value where the codec has one.
static func summarize(value: Variant, ctx: Dictionary) -> Dictionary:
	var kind := typeof(value)
	var entry := {"type": type_string(kind), "expandable": false}
	match kind:
		TYPE_OBJECT:
			return _summarize_object(value, entry, ctx)
		TYPE_ARRAY:
			entry.count = value.size()
			entry.expandable = value.size() > 0
			if value.is_typed():
				var element := type_string(value.get_typed_builtin())
				entry.element_type = String(value.get_typed_class_name()) if value.get_typed_builtin() == TYPE_OBJECT else element
		TYPE_DICTIONARY:
			entry.count = value.size()
			entry.expandable = value.size() > 0
		_:
			if kind in PACKED:
				entry.count = value.size()
				entry.expandable = value.size() > 0
				return entry
			var encoded: Variant = Codec.encode(value)
			if encoded is String:
				ctx.bytes += encoded.length()
				if encoded.length() > MAX_STRING:
					encoded = {"type": "String", "truncated": true, "value": encoded.left(MAX_STRING)}
			elif encoded is Dictionary and encoded.get("supported", true) == false:
				encoded.repr = str(value).left(MAX_STRING)
				ctx.bytes += encoded.repr.length()
			entry.value = encoded
	return entry

## Only native accessors (get_name, get_path): `.name` and `.resource_path` are Object.get() and would run `_get`.
static func _summarize_object(value: Variant, entry: Dictionary, ctx: Dictionary) -> Dictionary:
	if not is_instance_valid(value):
		entry.freed = true
		return entry
	entry.class = value.get_class()
	entry.instance_id = value.get_instance_id()
	entry.expandable = true
	var script: Script = value.get_script()
	if script != null and script.resource_path != "":
		entry.script = script.resource_path
	var hooks := _hooks(value, ctx)
	if not hooks.is_empty():
		entry.hooks = hooks
	if value is Node:
		entry.node_name = String(value.get_name())
		if value.is_inside_tree():
			entry.node_path = String(value.get_path())
	elif value is Resource:
		entry.resource_path = value.get_path()
		if hooks.is_empty(): # Codec.encode reads properties with get(), which runs `_get`
			entry.value = Codec.encode(value)
	return entry

## A value plus, when depth allows, an inline page of its children. Containers and objects that
## contain themselves are marked `cycle` and never inlined; they can still be drilled into by path.
static func _entry(value: Variant, depth: int, ctx: Dictionary, ancestors: Array) -> Dictionary:
	var entry := summarize(value, ctx)
	if not entry.expandable:
		return entry
	for ancestor in ancestors:
		if typeof(ancestor) == typeof(value) and is_same(ancestor, value):
			entry.cycle = true
			return entry
	if depth > 0:
		var page := _page_children(value, 0, INLINE_LIMIT, depth - 1, ctx, ancestors + [value])
		entry.children = page.items
		entry.child_total = page.total
		if page.truncated:
			entry.children_truncated = true
	return entry

static func _page_children(value: Variant, offset: int, limit: int, depth: int, ctx: Dictionary, ancestors: Array) -> Dictionary:
	var items := []
	var total := 0
	var kind := typeof(value)
	if kind == TYPE_DICTIONARY:
		var keys: Array = value.keys()
		total = keys.size()
		for i in range(offset, mini(total, offset + limit)):
			if not _take(ctx):
				break
			var item := _entry(value[keys[i]], depth, ctx, ancestors)
			item.index = i
			item.key = summarize(keys[i], ctx)
			items.append(item)
	elif kind == TYPE_ARRAY or kind in PACKED:
		total = value.size()
		for i in range(offset, mini(total, offset + limit)):
			if not _take(ctx):
				break
			var item := _entry(value[i], depth, ctx, ancestors)
			item.index = i
			items.append(item)
	elif kind == TYPE_OBJECT and is_instance_valid(value):
		var properties := _properties(value, ctx)
		total = properties.size()
		for i in range(offset, mini(total, offset + limit)):
			if not _take(ctx):
				break
			var property: Dictionary = properties[i]
			var item: Dictionary
			if property.unread:
				item = {"type": type_string(property.type), "expandable": false, "unread": true, "reason": property.reason}
			else:
				item = _entry(_read(value, property), depth, ctx, ancestors)
			item.name = property.name
			items.append(item)
	return {"items": items, "total": total, "truncated": offset + items.size() < total}

## Listable properties of an object, in engine order: [{name, type, unread, reason, native, hooked}].
static func _properties(object: Object, ctx: Dictionary) -> Array:
	var risky := _getter_names(object, ctx)
	var hooked := not _hooks(object, ctx).is_empty()
	var result := []
	var seen := {}
	for info in _property_infos(object, hooked):
		if info.usage & SKIPPED_USAGE != 0 or info.usage & LISTED_USAGE == 0 or seen.has(info.name):
			continue
		seen[info.name] = true
		var native: bool = info.get("native", false)
		var script_variable: bool = not native if hooked else info.usage & PROPERTY_USAGE_SCRIPT_VARIABLE != 0
		var reason: String = risky.get(info.name, risky.get("*", "") if script_variable else "")
		result.append({"name": info.name, "type": info.type, "unread": reason != "", "reason": reason,
			"native": native, "hooked": hooked})
	return result

## get_property_list() runs the script's `_get_property_list` and `_validate_property`, so a hooked object is
## listed from ClassDB (its native class), a synthetic `script` entry and Script.get_script_property_list()
## (declared variables of the whole chain) instead, none of which run script code. Tagged `native` by origin.
static func _property_infos(object: Object, hooked: bool) -> Array:
	if not hooked:
		return object.get_property_list()
	var infos: Array = []
	for info in ClassDB.class_get_property_list(object.get_class()):
		info.native = true
		infos.append(info)
	infos.append({"name": "script", "type": TYPE_OBJECT, "usage": PROPERTY_USAGE_DEFAULT, "native": true})
	var script: Script = object.get_script()
	for info in script.get_script_property_list():
		info.native = false
		infos.append(info)
	return infos

## The one place a property value is read. Object.get() on a hooked object runs `_get` first for every name the
## script does not declare, even native ones such as `process_mode`, so natives go through ClassDB. Declared
## script variables are not intercepted by `_get`; the caller has already excluded `unread` ones (getters).
static func _read(object: Object, property: Dictionary) -> Variant:
	if property.hooked and property.native:
		return object.get_script() if property.name == "script" else ClassDB.class_get_property(object, property.name)
	return object.get(property.name)

## Names of the hook methods (HOOKS) defined anywhere in the object's script chain, found with
## Script.get_script_method_list(), which needs no source and runs nothing. A script that is not GDScript
## cannot be checked and reports UNVERIFIED, so it is treated as hooked.
static func _hooks(object: Object, ctx: Dictionary) -> Array:
	var id := object.get_instance_id()
	if ctx.hooks.has(id):
		return ctx.hooks[id]
	var found := []
	var script: Script = object.get_script()
	while script != null:
		if not script is GDScript:
			if not UNVERIFIED in found:
				found.append(UNVERIFIED)
		else:
			for method in script.get_script_method_list():
				if method.name in HOOKS and not method.name in found:
					found.append(String(method.name))
		script = script.get_base_script()
	ctx.hooks[id] = found
	return found

## Reasons by name, for the script variables that must not be read because they may have a `get` accessor,
## found by reading the source of the object's script chain (the engine does not expose accessors). Fails
## closed: a script whose source cannot be found (binary-tokenized, C#, an inner class whose owner is not
## among the loaded scripts, ...) cannot be inspected, so every variable it declares, and every script
## variable of the object (`*`), is treated as having a getter.
static func _getter_names(object: Object, ctx: Dictionary) -> Dictionary:
	var names := {}
	var script: Script = object.get_script()
	while script != null:
		var sources := _sources(script, ctx)
		if sources.is_empty():
			names["*"] = REASON_SOURCE
			for info in script.get_script_property_list():
				names[info.name] = names.get(info.name, REASON_SOURCE)
		for source in sources:
			_scan_getters(source, names)
		script = script.get_base_script()
	return names

## Source to scan for one script of a chain: its own, or for an inner class (no source, no path) the whole
## file of every script found to declare it (see _owners). Empty when there is none.
static func _sources(script: Script, ctx: Dictionary) -> Array:
	if not script is GDScript:
		return []
	if script.source_code.strip_edges() != "":
		return [script.source_code]
	if script.resource_path != "":
		return []
	return _owners(ctx).get(script.get_instance_id(), [])

static func _scan_getters(source: String, names: Dictionary) -> void:
	var declaration := RegEx.new()
	declaration.compile("^(\\s*)(?:@\\w+(?:\\([^)]*\\))?\\s*)*(?:static\\s+)?var\\s+(\\w+)(.*)$")
	var lines := source.split("\n")
	for i in lines.size():
		var found := declaration.search(lines[i])
		if found == null:
			continue
		var rest := found.get_string(3)
		var comment := rest.find("#")
		if comment >= 0:
			rest = rest.left(comment)
		rest = rest.strip_edges()
		if rest.ends_with(":"):
			var indent := found.get_string(1).length()
			for j in range(i + 1, lines.size()):
				var line := lines[j]
				if line.strip_edges() == "":
					continue
				if line.length() - line.lstrip(" \t").length() <= indent:
					break
				if line.strip_edges().begins_with("get") and not line.strip_edges().substr(3, 1).is_valid_identifier():
					names[found.get_string(2)] = REASON_GETTER
					break
		else:
			var inline := RegEx.new()
			inline.compile("[:,]\\s*get\\b")
			if inline.search(rest) != null:
				names[found.get_string(2)] = REASON_GETTER

## An inner class's script has no source and nothing that points to its outer script, but the outer script holds
## it as a constant, so the owner is found by identity: {inner script id: [source of each script declaring it]},
## built once per call. Only scripts that are already loaded are searched (load() of an uncached script would
## run its static initialisers). A match also needs `class <constant name>` in the source: a script that only
## aliases the class (`const Alias = Other.Inner`) is not its owner and its source would lack the getters.
static func _owners(ctx: Dictionary) -> Dictionary:
	if ctx.owners != null:
		return ctx.owners
	var found := _loaded_scripts(ctx)
	var owners := {}
	var scanned := {}
	var pending := true
	while pending: # preloaded scripts join `found` while it is scanned
		pending = false
		for id in found.keys():
			if not scanned.has(id):
				scanned[id] = true
				pending = true
				_index_constants(found[id], found[id].source_code, found, owners, {}, 0)
	ctx.owners = owners
	return owners

## Starting points of the owner search: scripts of the roots, of the scene tree, of the stack and of the
## global classes, restricted to those already in the resource cache.
static func _loaded_scripts(ctx: Dictionary) -> Dictionary:
	var found := {}
	for root in ctx.roots:
		if typeof(root.value) == TYPE_OBJECT and is_instance_valid(root.value):
			var object: Object = root.value
			_add_script(object.get_script(), found)
	var tree := Engine.get_main_loop() as SceneTree
	if tree != null and tree.root != null:
		var nodes: Array[Node] = [tree.root]
		var budget := MAX_TREE_NODES
		while not nodes.is_empty() and budget > 0:
			var node: Node = nodes.pop_back()
			budget -= 1
			_add_script(node.get_script(), found)
			nodes.append_array(node.get_children())
	var paths := []
	for backtrace in Engine.capture_script_backtraces(false):
		for index in backtrace.get_frame_count():
			paths.append(backtrace.get_frame_file(index))
	for entry in ProjectSettings.get_global_class_list():
		paths.append(entry.path)
	for path in paths:
		if path != "" and ResourceLoader.has_cached(path):
			_add_script(ResourceLoader.load(path), found)
	return found

## Adds a script and its base chain. Scripts without a path or source (inner classes) cannot own anything.
static func _add_script(script: Variant, found: Dictionary) -> void:
	while script is GDScript and found.size() < MAX_CANDIDATES:
		if script.resource_path != "" or script.source_code.strip_edges() != "":
			found[script.get_instance_id()] = script
		script = script.get_base_script()

## Records, for the inner classes held as constants (nested ones too) by `script`, that `source` declares them.
## Constants with a path are preloaded scripts: they become search candidates, not inner classes.
static func _index_constants(script: GDScript, source: String, found: Dictionary, owners: Dictionary, seen: Dictionary, depth: int) -> void:
	if depth > MAX_INNER_DEPTH or seen.has(script.get_instance_id()):
		return
	seen[script.get_instance_id()] = true
	var constants := script.get_script_constant_map()
	for key in constants:
		var value: Variant = constants[key]
		if not value is GDScript:
			continue
		if value.resource_path != "":
			_add_script(value, found)
		elif source.strip_edges() != "" and _declares_class(source, String(key)):
			var sources: Array = owners.get_or_add(value.get_instance_id(), [])
			if not source in sources:
				sources.append(source)
			_index_constants(value, source, found, owners, seen, depth + 1)

static func _declares_class(source: String, name: String) -> bool:
	if not name.is_valid_identifier():
		return false
	return RegEx.create_from_string("(?m)^[ \\t]*class[ \\t]+" + name + "\\b").search(source) != null
