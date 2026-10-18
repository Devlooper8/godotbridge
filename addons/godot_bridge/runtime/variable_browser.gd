extends RefCounted
## Lazy, path-based browsing of the variables of a stopped game (used by runtime_inspector.gd).
## Nothing is retained between calls: every request walks its path from freshly captured roots, so a path that
## no longer resolves is a clear error rather than a stale handle. Replies are bounded by paging, an entry
## budget and string limits. Scripts are never executed: script properties that have a custom getter are
## reported as `unread`, because reading one would run user code inside the debugger break.

const Codec = preload("../codec.gd")
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
	var ctx := {"left": MAX_ENTRIES, "bytes": 0, "exhausted": false}
	var result := {"offset": offset, "limit": limit}
	var page: Dictionary
	if path.is_empty():
		page = _page_roots(roots, offset, limit, depth, ctx)
		result.variables = page.items
	else:
		var walked := _walk(roots, path)
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

static func _walk(roots: Array, path: Array) -> Dictionary:
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
			for candidate in _properties(current):
				if candidate.name == wanted:
					property = candidate
					break
			if property.is_empty():
				return fail("VARIABLE_NOT_FOUND", "%s has no listed property %s (%s)." % [current.get_class(), wanted, where])
			if property.unread:
				return fail("UNSUPPORTED_OPERATION", "Property %s has a custom getter; reading it would run script code in the debugger." % wanted)
			current = current.get(wanted)
		else:
			return fail("INVALID_ARGUMENT", "Path segments after the first are {\"index\": n} or {\"property\": name}.")
	return {"ok": true, "value": current}

## One value: type, class, count, expandable and the encoded value where the codec has one.
static func summarize(value: Variant, ctx: Dictionary) -> Dictionary:
	var kind := typeof(value)
	var entry := {"type": type_string(kind), "expandable": false}
	match kind:
		TYPE_OBJECT:
			return _summarize_object(value, entry)
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

static func _summarize_object(value: Variant, entry: Dictionary) -> Dictionary:
	if not is_instance_valid(value):
		entry.freed = true
		return entry
	entry.class = value.get_class()
	entry.instance_id = value.get_instance_id()
	entry.expandable = true
	var script: Script = value.get_script()
	if script != null and script.resource_path != "":
		entry.script = script.resource_path
	if value is Node:
		entry.node_name = String(value.name)
		if value.is_inside_tree():
			entry.node_path = String(value.get_path())
	elif value is Resource:
		entry.resource_path = value.resource_path
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
		var properties := _properties(value)
		total = properties.size()
		for i in range(offset, mini(total, offset + limit)):
			if not _take(ctx):
				break
			var property: Dictionary = properties[i]
			var item: Dictionary
			if property.unread:
				item = {"type": type_string(property.type), "expandable": false, "unread": true,
					"reason": "custom getter: reading it would run script code"}
			else:
				item = _entry(value.get(property.name), depth, ctx, ancestors)
			item.name = property.name
			items.append(item)
	return {"items": items, "total": total, "truncated": offset + items.size() < total}

## Listable properties of an object, in engine order: [{name, type, unread}].
static func _properties(object: Object) -> Array:
	var risky := _getter_names(object)
	var result := []
	for info in object.get_property_list():
		if info.usage & SKIPPED_USAGE != 0 or info.usage & LISTED_USAGE == 0:
			continue
		var unknown: bool = risky.has("*") and info.usage & PROPERTY_USAGE_SCRIPT_VARIABLE != 0
		result.append({"name": info.name, "type": info.type, "unread": unknown or risky.has(info.name)})
	return result

## Names of script variables that must not be read because they may have a `get` accessor, found by reading
## the source of the object's script chain (the engine does not expose accessors). Fails closed: a script
## whose source is missing or is not GDScript (binary-tokenized, C#, ...) cannot be inspected, so every
## variable it declares, and every script variable of the object, is treated as having a getter.
static func _getter_names(object: Object) -> Dictionary:
	var names := {}
	var script: Script = object.get_script()
	while script != null:
		if script is GDScript and script.source_code.strip_edges() != "":
			_scan_getters(script.source_code, names)
		else:
			names["*"] = true
			for info in script.get_script_property_list():
				names[info.name] = true
		script = script.get_base_script()
	return names

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
					names[found.get_string(2)] = true
					break
		else:
			var inline := RegEx.new()
			inline.compile("[:,]\\s*get\\b")
			if inline.search(rest) != null:
				names[found.get_string(2)] = true
