@tool
extends RefCounted
## Validate the subset of JSON Schema emitted by our Pydantic models.
## Recursion and string/array sizes are bounded independently of the wire frame.

static func validate(value: Variant, schema: Dictionary, defs: Dictionary = {}, depth: int = 0) -> bool:
	if depth > 24:
		return false
	if schema.has("$defs"):
		defs = schema["$defs"]
	if schema.has("$ref"):
		return validate(value, defs.get(String(schema["$ref"]).get_file(), {}), defs, depth + 1)
	if schema.has("anyOf"):
		for option in schema.anyOf:
			if validate(value, option, defs, depth + 1):
				return true
		return false
	if schema.has("enum") and not value in schema.enum:
		return false
	if schema.has("const") and value != schema.const:
		return false
	match schema.get("type", ""):
		"object":
			if not value is Dictionary or value.size() > 128:
				return false
			for key in schema.get("required", []):
				if not value.has(key):
					return false
			for key in value:
				if schema.get("properties", {}).has(key):
					if not validate(value[key], schema.properties[key], defs, depth + 1):
						return false
				elif schema.get("additionalProperties", true) == false:
					return false
				elif schema.get("additionalProperties") is Dictionary:
					if not validate(value[key], schema.additionalProperties, defs, depth + 1):
						return false
		"array":
			if not value is Array or value.size() > schema.get("maxItems", 4096) or value.size() < schema.get("minItems", 0):
				return false
			for i in value.size():
				var item_schema: Dictionary = schema.get("prefixItems", [])[i] if i < schema.get("prefixItems", []).size() else schema.get("items", {})
				if not validate(value[i], item_schema, defs, depth + 1):
					return false
		"string":
			if not value is String or value.length() < schema.get("minLength", 0) or value.length() > schema.get("maxLength", 4096):
				return false
		"boolean":
			if not value is bool:
				return false
		"number", "integer":
			if not (value is float or value is int) or not is_finite(float(value)):
				return false
			if schema.get("type") == "integer" and float(value) != floor(float(value)):
				return false
			if value < schema.get("minimum", -INF) or value > schema.get("maximum", INF):
				return false
			if value <= schema.get("exclusiveMinimum", -INF) or value >= schema.get("exclusiveMaximum", INF):
				return false
		"null":
			if value != null:
				return false
	return true
