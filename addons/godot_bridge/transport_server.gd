@tool
extends RefCounted
## Main-thread, nonblocking framed transport. No socket operation waits for input.

const MAX_FRAME := 4 * 1024 * 1024
const MAX_CLIENTS := 8
const MAX_QUEUE := 32
const CONNECTION := "res://.godot/godotbridge/connection.json"
var server := TCPServer.new()
var clients: Array[Dictionary] = []
var queue: Array[Dictionary] = []
var token := ""
var port := 0
var start_error := ""

func start() -> Error:
	var project_dir := DirAccess.open("res://")
	var godot_dir := DirAccess.open("res://.godot")
	if project_dir.is_link(".godot") or (godot_dir and godot_dir.is_link("godotbridge")):
		start_error = "Connection storage must not be a symlink."
		return ERR_UNAUTHORIZED
	var private_dir := ProjectSettings.globalize_path(CONNECTION.get_base_dir())
	if DirAccess.make_dir_recursive_absolute(private_dir) != OK:
		start_error = "Cannot create private connection directory."
		return ERR_FILE_CANT_WRITE
	# Restrict the parent before ever writing credentials. Windows has no native
	# GDScript ACL API; the native ACL utility restricts the private directory.
	if OS.get_name() == "Windows":
		var output := []
		var system := OS.get_environment("SystemRoot").path_join("System32")
		if OS.execute(system.path_join("whoami.exe"), [], output, true, false) != 0 or output.is_empty():
			start_error = "Cannot identify the current Windows account."
			return ERR_UNAUTHORIZED
		var account: String = String(output[0]).strip_edges()
		output.clear()
		if OS.execute(system.path_join("icacls.exe"), [private_dir, "/inheritance:r", "/grant:r", account + ":(OI)(CI)F",
			"/remove:g", "*S-1-1-0", "*S-1-5-11", "*S-1-5-32-545", "*S-1-5-32-546"], output, true, false) != 0:
			start_error = "Cannot restrict connection directory ACL."
			return ERR_UNAUTHORIZED
	elif FileAccess.set_unix_permissions(private_dir, 448) != OK: # 0700
		start_error = "Cannot restrict connection directory permissions."
		return ERR_UNAUTHORIZED
	if FileAccess.file_exists(CONNECTION):
		var previous = JSON.parse_string(FileAccess.get_file_as_string(CONNECTION))
		if previous is Dictionary and OS.is_process_running(int(previous.get("pid", -1))):
			start_error = "Another editor owns this project's connection. Close it first."
			return ERR_ALREADY_IN_USE
	var err := server.listen(0, "127.0.0.1")
	if err != OK:
		start_error = "Cannot bind IPv4 loopback: " + error_string(err)
		return err
	port = server.get_local_port()
	token = Crypto.new().generate_random_bytes(32).hex_encode()
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(CONNECTION.get_base_dir()))
	var file := FileAccess.open(CONNECTION, FileAccess.WRITE)
	if file == null:
		server.stop()
		start_error = "Cannot write connection credentials."
		return ERR_FILE_CANT_WRITE
	file.store_string(JSON.stringify({"host": "127.0.0.1", "port": port, "token": token,
		"pid": OS.get_process_id(), "project": ProjectSettings.globalize_path("res://"), "protocol_version": "1.0"}))
	file.close()
	if OS.get_name() != "Windows":
		FileAccess.set_unix_permissions(CONNECTION, 384) # 0600
	return OK

func stop() -> void:
	server.stop()
	for client in clients:
		client.peer.disconnect_from_host()
	clients.clear()
	queue.clear()
	if FileAccess.file_exists(CONNECTION):
		var saved = JSON.parse_string(FileAccess.get_file_as_string(CONNECTION))
		if saved is Dictionary and saved.get("token") == token:
			DirAccess.remove_absolute(ProjectSettings.globalize_path(CONNECTION))
	token = ""
	port = 0

func poll() -> void:
	if server.is_connection_available():
		var peer := server.take_connection()
		if clients.size() >= MAX_CLIENTS:
			peer.disconnect_from_host()
		else:
			peer.set_no_delay(true)
			clients.append({"peer": peer, "in": PackedByteArray(), "out": PackedByteArray(),
				"authenticated": false, "closing": false, "last": Time.get_ticks_msec(), "pending": false})
	for client in clients.duplicate():
		var peer: StreamPeerTCP = client.peer
		peer.poll()
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED or Time.get_ticks_msec() - client.last > 30000:
			_drop(client)
			continue
		if not client.out.is_empty():
			var sent := peer.put_partial_data(client.out.slice(0, 65536))
			if sent[0] != OK:
				_drop(client)
				continue
			client.out = client.out.slice(sent[1])
		if client.closing:
			if client.out.is_empty():
				_drop(client)
			continue
		var available := mini(peer.get_available_bytes(), 65536)
		if available > 0:
			var received := peer.get_partial_data(available)
			if received[0] != OK:
				_drop(client)
				continue
			client["in"].append_array(received[1])
			if client["in"].size() > MAX_FRAME + 4:
				_drop(client)
				continue
		if client.pending or client["in"].size() < 4:
			continue
		var bytes: PackedByteArray = client["in"]
		var size: int = (int(bytes[0]) << 24) | (int(bytes[1]) << 16) | (int(bytes[2]) << 8) | int(bytes[3])
		if size <= 0 or size > MAX_FRAME:
			respond(client, "", failure("INVALID_ARGUMENT", "Invalid frame length."))
			client.closing = true
			continue
		if bytes.size() < size + 4:
			continue
		client["in"] = bytes.slice(size + 4)
		client.last = Time.get_ticks_msec()
		var parser := JSON.new()
		if parser.parse(bytes.slice(4, size + 4).get_string_from_utf8()) != OK or not parser.data is Dictionary:
			respond(client, "", failure("INVALID_ARGUMENT", "Expected a JSON request object."))
			client.closing = true
			continue
		var request: Dictionary = parser.data
		var id = request.get("request_id", "")
		if not id is String or id.length() > 128 or not request.get("method") is String or not request.get("params", {}) is Dictionary:
			respond(client, "", failure("INVALID_ARGUMENT", "Invalid request envelope."))
			continue
		if request.get("protocol_version") != "1.0":
			respond(client, id, failure("PROTOCOL_MISMATCH", "Expected protocol 1.0."))
			continue
		if not client.authenticated:
			var received_token = request.get("params", {}).get("token")
			if request.method != "handshake" or not received_token is String or not Crypto.new().constant_time_compare(token.to_utf8_buffer(), received_token.to_utf8_buffer()):
				respond(client, id, failure("AUTHENTICATION_FAILED", "Invalid session token."))
				client.closing = true
				continue
			client.authenticated = true
		if queue.size() >= MAX_QUEUE:
			respond(client, id, failure("EDITOR_BUSY", "Request queue is full."))
		else:
			client.pending = true
			queue.append({"client": client, "request": request})

func respond(client: Dictionary, id: String, payload: Dictionary) -> void:
	var envelope := {"protocol_version": "1.0", "request_id": id}
	envelope.merge(payload)
	var bytes := JSON.stringify(envelope).to_utf8_buffer()
	if bytes.size() > MAX_FRAME:
		bytes = JSON.stringify({"protocol_version": "1.0", "request_id": id, "ok": false,
			"error": {"code": "INTERNAL_ERROR", "message": "Response exceeds frame limit."}}).to_utf8_buffer()
	var size := bytes.size()
	var frame := PackedByteArray([(size >> 24) & 255, (size >> 16) & 255, (size >> 8) & 255, size & 255])
	frame.append_array(bytes)
	if client.out.size() + frame.size() > MAX_FRAME + 4:
		_drop(client)
		return
	client.out.append_array(frame)
	client.pending = false

func _drop(client: Dictionary) -> void:
	client.peer.disconnect_from_host()
	clients.erase(client)
	queue = queue.filter(func(item): return item.client != client)

static func failure(code: String, message: String) -> Dictionary:
	return {"ok": false, "error": {"code": code, "message": message}}
