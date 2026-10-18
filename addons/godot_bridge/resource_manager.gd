@tool
extends RefCounted

const Wire = preload("transport_server.gd")
const Nodes = preload("node_manager.gd")

static func handle(method: String, params: Dictionary, nodes: RefCounted) -> Dictionary:
	nodes.root = EditorInterface.get_edited_scene_root()
	if nodes.root == null:
		return Wire.failure("SCENE_NOT_OPEN", "Open or create a scene first.")
	nodes.allow_tool = params.get("allow_tool_script", false)
	var parent: Node = nodes.resolve(params.parent)
	if parent == null or not nodes.editable(parent) or not nodes.valid_name(parent, params.name):
		return nodes.error
	var node: Node3D
	if method == "3d.create_primitive":
		var mesh: PrimitiveMesh
		var shape: Shape3D
		match params.kind:
			"box":
				mesh = BoxMesh.new()
				mesh.size = Nodes.vector3(params.size)
				shape = BoxShape3D.new()
				shape.size = mesh.size
			"sphere":
				mesh = SphereMesh.new()
				mesh.radius = params.radius
				mesh.height = params.radius * 2
				shape = SphereShape3D.new()
				shape.radius = params.radius
			"cylinder":
				mesh = CylinderMesh.new()
				mesh.top_radius = params.radius
				mesh.bottom_radius = params.radius
				mesh.height = params.height
				shape = CylinderShape3D.new()
				shape.radius = params.radius
				shape.height = params.height
			"plane":
				mesh = PlaneMesh.new()
				mesh.size = Vector2(params.size[0], params.size[2])
				shape = BoxShape3D.new()
				shape.size = Vector3(params.size[0], 0.05, params.size[2])
		var material := StandardMaterial3D.new()
		material.albedo_color = Color(params.color[0], params.color[1], params.color[2], params.color[3])
		node = MeshInstance3D.new()
		node.mesh = mesh
		node.material_override = material
		if params.collision:
			var body := StaticBody3D.new()
			body.name = "Body"
			node.add_child(body)
			var collision := CollisionShape3D.new()
			collision.name = "Collision"
			collision.shape = shape
			body.add_child(collision)
	elif method == "3d.create_light":
		node = ClassDB.instantiate({"directional": "DirectionalLight3D", "omni": "OmniLight3D", "spot": "SpotLight3D"}[params.type])
		node.light_color = Color(params.color[0], params.color[1], params.color[2], params.color[3])
		node.light_energy = params.energy
		node.rotation_degrees = Nodes.vector3(params.rotation)
		node.shadow_enabled = true
	elif method == "3d.create_camera":
		var position := Nodes.vector3(params.position)
		var target := Nodes.vector3(params.target)
		if position.distance_to(target) < 0.001:
			return Wire.failure("INVALID_ARGUMENT", "Camera position and target must differ.")
		node = Camera3D.new()
		node.fov = params.fov
		node.current = params.current
		var direction := (target - position).normalized()
		node.basis = Basis.looking_at(direction, Vector3.FORWARD if absf(direction.dot(Vector3.UP)) > 0.99 else Vector3.UP)
	else:
		return Wire.failure("UNSUPPORTED_OPERATION", "Unknown 3D helper.")
	node.name = params.name
	node.position = Nodes.vector3(params.position)
	return nodes.add_node(parent, node)
