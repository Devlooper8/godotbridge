extends SceneTree
## Standalone engine validation; never writes scenes or enters their SceneTree.

var failures: Array[String] = []
var checked := 0

func _initialize() -> void:
	_scan("res://")
	print("GODOTBRIDGE_RESULT=" + JSON.stringify({"checked": checked, "failures": failures, "valid": failures.is_empty()}))
	quit(0 if failures.is_empty() else 1)

func _scan(path: String) -> void:
	var dir := DirAccess.open(path)
	if dir == null:
		failures.append("Cannot read " + path)
		return
	for name in dir.get_directories():
		if name.begins_with(".") or name in ["addons", "test-user", "snapshots"] or dir.is_link(name):
			continue
		_scan(path.path_join(name))
	for name in dir.get_files():
		if dir.is_link(name) or not name.get_extension() in ["tscn", "tres", "gd"]:
			continue
		var file := path.path_join(name)
		checked += 1
		var resource = ResourceLoader.load(file, "", ResourceLoader.CACHE_MODE_IGNORE)
		if resource == null:
			failures.append(file)
		elif resource is GDScript and not resource.can_instantiate():
			failures.append(file)
		elif resource is PackedScene:
			var instance: Node = resource.instantiate()
			if instance == null:
				failures.append(file)
			else:
				instance.free()
