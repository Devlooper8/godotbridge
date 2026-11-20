@tool
extends RefCounted
## No Variant stringification, expressions, arbitrary resources or method calls.

const NODE_PROPERTIES := ["visible", "position", "rotation", "rotation_degrees", "scale", "transform",
	"top_level", "cast_shadow", "mesh", "material_override", "shape", "disabled", "light_color",
	"light_energy", "shadow_enabled", "omni_range", "spot_range", "spot_angle", "fov", "near", "far",
	"current", "projection", "size", "mass", "gravity_scale", "collision_layer", "collision_mask",
	"target_position", "enabled", "monitoring", "monitorable"]
# AVOIDANCE is not contiguous with the other layer hints.
const LAYER_HINTS := [PROPERTY_HINT_LAYERS_2D_RENDER, PROPERTY_HINT_LAYERS_2D_PHYSICS, PROPERTY_HINT_LAYERS_2D_NAVIGATION,
	PROPERTY_HINT_LAYERS_3D_RENDER, PROPERTY_HINT_LAYERS_3D_PHYSICS, PROPERTY_HINT_LAYERS_3D_NAVIGATION, PROPERTY_HINT_LAYERS_AVOIDANCE]
const RESOURCE_PROPERTIES := {
	"BoxMesh": ["size"], "SphereMesh": ["radius", "height", "radial_segments", "rings"],
	"CylinderMesh": ["top_radius", "bottom_radius", "height", "radial_segments"], "PlaneMesh": ["size"],
	"StandardMaterial3D": ["albedo_color", "roughness", "metallic"],
	"BoxShape3D": ["size"], "SphereShape3D": ["radius"], "CapsuleShape3D": ["radius", "height"]}

static func encode(value: Variant) -> Variant:
	if value == null:
		return null
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_FLOAT, TYPE_STRING:
			return value
		TYPE_STRING_NAME:
			return String(value)
		TYPE_VECTOR2:
			return {"type": "Vector2", "value": [value.x, value.y]}
		TYPE_VECTOR3:
			return {"type": "Vector3", "value": [value.x, value.y, value.z]}
		TYPE_COLOR:
			return {"type": "Color", "value": [value.r, value.g, value.b, value.a]}
		TYPE_NODE_PATH:
			return {"type": "NodePath", "value": String(value)}
		TYPE_BASIS:
			return {"type": "Basis", "value": [encode(value.x).value, encode(value.y).value, encode(value.z).value]}
		TYPE_TRANSFORM3D:
			return {"type": "Transform3D", "basis": encode(value.basis), "origin": encode(value.origin)}
		TYPE_AABB:
			return {"type": "AABB", "position": encode(value.position), "size": encode(value.size)}
		TYPE_OBJECT:
			if value is Resource:
				var properties := {}
				for key in RESOURCE_PROPERTIES.get(value.get_class(), []):
					properties[key] = encode(value.get(key))
				return {"type": value.get_class(), "path": value.resource_path, "properties": properties}
	return {"type": type_string(typeof(value)), "supported": false}

static func decode(value: Variant, depth: int = 0) -> Dictionary:
	if depth > 8:
		return {"ok": false}
	if value == null or value is bool or value is String or value is int or value is float:
		return {"ok": true, "value": value}
	if not value is Dictionary or not value.get("type") is String:
		return {"ok": false}
	var data = value.get("value")
	match value.type:
		"Vector2", "Vector3", "Color":
			var count: int = {"Vector2": 2, "Vector3": 3, "Color": 4}[value.type]
			if not data is Array or data.size() != count:
				return {"ok": false}
			for component in data:
				if not (component is int or component is float) or not is_finite(float(component)) or absf(float(component)) > 1000000000.0:
					return {"ok": false}
			if count == 2:
				return {"ok": true, "value": Vector2(data[0], data[1])}
			if count == 3:
				return {"ok": true, "value": Vector3(data[0], data[1], data[2])}
			return {"ok": true, "value": Color(data[0], data[1], data[2], data[3])}
		"NodePath":
			if data is String and not data.begins_with("/") and not ".." in data and not ":" in data:
				return {"ok": true, "value": NodePath(data)}
		"Basis":
			if not data is Array or data.size() != 3:
				return {"ok": false}
			var axes: Array[Vector3] = []
			for axis in data:
				var vector := decode({"type": "Vector3", "value": axis}, depth + 1)
				if not vector.ok:
					return {"ok": false}
				axes.append(vector.value)
			var basis := Basis(axes[0], axes[1], axes[2])
			if absf(basis.determinant()) < 0.000001:
				return {"ok": false}
			return {"ok": true, "value": basis}
		"Transform3D":
			var basis := decode(value.get("basis"), depth + 1)
			var origin := decode(value.get("origin"), depth + 1)
			if basis.get("value") is Basis and origin.get("value") is Vector3:
				return {"ok": true, "value": Transform3D(basis.value, origin.value)}
		_:
			if RESOURCE_PROPERTIES.has(value.type) and value.get("properties", {}) is Dictionary:
				var resource: Resource = ClassDB.instantiate(value.type)
				for key in value.get("properties", {}):
					if not key in RESOURCE_PROPERTIES[value.type]:
						return {"ok": false}
					var decoded := decode(value.properties[key], depth + 1)
					if not decoded.ok or not compatible(resource, key, decoded.value):
						return {"ok": false}
					resource.set(key, decoded.value)
				return {"ok": true, "value": resource}
	return {"ok": false}

## Takes a Script.get_script_property_list entry.
static func is_script_variable(info: Dictionary) -> bool:
	return info.usage & PROPERTY_USAGE_SCRIPT_VARIABLE != 0 and info.usage & (PROPERTY_USAGE_EDITOR | PROPERTY_USAGE_STORAGE) != 0

## Exported script variables (name -> property info), the only non-allowlisted properties exposed.
## A placeholder instance lists them without PROPERTY_USAGE_SCRIPT_VARIABLE, so the flag is read from the script itself.
static func script_variables(node: Node) -> Dictionary:
	var result := {}
	var script: Script = node.get_script()
	if script == null:
		return result
	var names := {}
	for info in script.get_script_property_list():
		if is_script_variable(info):
			names[info.name] = true
	for info in node.get_property_list():
		if names.has(info.name):
			result[info.name] = info
	return result

## Placeholder script instances store values verbatim, so normalise what the engine would convert.
static func coerce(info: Dictionary, value: Variant) -> Variant:
	if info.type == TYPE_FLOAT and value is int:
		return float(value)
	if info.type == TYPE_INT and value is float:
		return int(value) # JSON numbers arrive as floats; fits() has already required an integral value.
	if info.type == TYPE_STRING_NAME and value is String:
		return StringName(value)
	return value

static func compatible(object: Object, key: String, value: Variant) -> bool:
	for info in object.get_property_list():
		if info.name == key:
			return fits(info, key, value)
	return false

## Checks a decoded value against one property_list entry; an empty key skips the per-name range rules.
static func fits(info: Dictionary, key: String, value: Variant) -> bool:
	if info.type == TYPE_NIL: # Untyped Variant script variable.
		return not value is Object or (value is Resource and value.get_script() == null)
	if info.type == TYPE_STRING_NAME:
		return value is String
	if info.type == TYPE_OBJECT:
		return value == null or (value is Resource and is_any_class(value, info.hint_string) and value.get_script() == null)
	if info.type == TYPE_FLOAT or info.type == TYPE_INT:
		if not (value is int or value is float) or not is_finite(float(value)):
			return false
		if info.type == TYPE_INT and float(value) != floor(float(value)):
			return false
		if absf(float(value)) > (4294967295.0 if info.type == TYPE_INT else 1000000000.0):
			return false
		if key == "fov" and (value <= 1 or value >= 179):
			return false
		if key in ["radius", "height", "near", "far", "size", "mass"] and value <= 0:
			return false
		if key in ["radial_segments", "rings"] and (value < 4 or value > 256):
			return false
		return hint_allows(info, value)
	if info.type == TYPE_STRING and key == "" and info.hint == PROPERTY_HINT_ENUM:
		return value is String and value in enum_entries(info.hint_string).keys()
	if key in ["size", "scale"] and value is Vector3 and (value.x <= 0 or value.y <= 0 or value.z <= 0):
		return false
	return typeof(value) == info.type

## Resource properties list their accepted classes in the hint string ("BaseMaterial3D,ShaderMaterial"); an empty hint matches nothing.
static func is_any_class(object: Object, hint_string: String) -> bool:
	for name in hint_string.split(","):
		if object.is_class(name.strip_edges()):
			return true
	return false

## The inspector's range, enum, flags and layer limits (the engine setters clamp or wrap instead of rejecting).
## The hint bounds are in degrees for "radians_as_degrees" while the value is radians.
static func hint_allows(info: Dictionary, value: Variant) -> bool:
	if info.hint == PROPERTY_HINT_RANGE:
		var parts: PackedStringArray = info.hint_string.split(",")
		if parts.size() >= 2 and parts[0].is_valid_float() and parts[1].is_valid_float():
			var unit := deg_to_rad(1.0) if "radians_as_degrees" in parts else 1.0
			var slack := 0.000000001 if unit != 1.0 else 0.0 # A bound such as 360 degrees must accept TAU.
			if value < float(parts[0]) * unit - slack and not "or_less" in parts:
				return false
			if value > float(parts[1]) * unit + slack and not "or_greater" in parts:
				return false
	elif info.hint == PROPERTY_HINT_ENUM and info.type == TYPE_INT:
		return int(value) in enum_entries(info.hint_string).values() # Array.has is type-strict.
	elif info.type == TYPE_INT and info.hint == PROPERTY_HINT_FLAGS:
		return value >= 0 and (int(value) & ~flags_mask(info.hint_string)) == 0
	elif info.type == TYPE_INT and info.hint in LAYER_HINTS:
		return value >= 0 # The engine wraps a negative mask to unsigned; fits() already caps it at 32 bits.
	return true

## "A,B:4,C" -> 1 | 4 | 4: an entry without a value is the bit 1 << its index (that is how the inspector reads @export_flags).
static func flags_mask(hint_string: String) -> int:
	var mask := 0
	var entries := hint_string.split(",")
	for index in entries.size():
		var pair := entries[index].rsplit(":", true, 1)
		mask |= int(pair[1]) if pair.size() == 2 and pair[1].is_valid_int() else 1 << index
	return mask

## "A,B:5,C" -> {"A": 0, "B": 5, "C": 6}
static func enum_entries(hint_string: String) -> Dictionary:
	var result := {}
	var next := 0
	for entry in hint_string.split(","):
		var pair := entry.rsplit(":", true, 1)
		if pair.size() == 2 and pair[1].is_valid_int():
			next = int(pair[1])
			result[pair[0]] = next
		else:
			result[entry] = next
		next += 1
	return result
