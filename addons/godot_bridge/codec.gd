@tool
extends RefCounted
## No Variant stringification, expressions, arbitrary resources or method calls.

const NODE_PROPERTIES := ["visible", "position", "rotation", "rotation_degrees", "scale", "transform",
	"top_level", "cast_shadow", "mesh", "material_override", "shape", "disabled", "light_color",
	"light_energy", "shadow_enabled", "omni_range", "spot_range", "spot_angle", "fov", "near", "far",
	"current", "projection", "size", "mass", "gravity_scale", "collision_layer", "collision_mask",
	"target_position", "enabled", "monitoring", "monitorable"]
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

static func compatible(object: Object, key: String, value: Variant) -> bool:
	for info in object.get_property_list():
		if info.name != key:
			continue
		if info.type == TYPE_OBJECT:
			return value == null or (value is Resource and value.is_class(info.hint_string) and value.get_script() == null)
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
			return true
		if key in ["size", "scale"] and value is Vector3 and (value.x <= 0 or value.y <= 0 or value.z <= 0):
			return false
		return typeof(value) == info.type
	return false
