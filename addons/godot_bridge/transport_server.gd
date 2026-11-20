@tool
extends RefCounted
## Main-thread, nonblocking framed transport. No socket operation waits for input.

const MAX_FRAME := 4 * 1024 * 1024
const MAX_CLIENTS := 8
const MAX_QUEUE := 32
const CONNECTION := "res://.godot/godotbridge/connection.json"
const CHECK_MS := 2000 # How often maintain() looks at the credentials file.
const PROBE_CONNECT_MS := 300 # Owner probe, connect and send: a live loopback listener completes the handshake at once.
const PROBE_REPLY_MS := 1000 # Owner probe, reply: it comes from the owner's main loop, so it needs whole editor frames.
const PROBE_REPLY_MAX := 4096
const PROBE_ID := "owner-probe" # Request id and token of the probe; real tokens are 64 hex characters, so it never matches.
const IDLE_MS := 30000
var server := TCPServer.new()
var idle_ms := IDLE_MS # Per instance only so the transport harness can lower it; nothing on the wire sets it.
var clients: Array[Dictionary] = []
var queue: Array[Dictionary] = []
var token := ""
var port := 0
var start_error := ""
var next_check := 0

func is_up() -> bool:
	return port != 0 and server.is_listening()

## Safe to call again after a failure: every failure path leaves the server stopped with no port or token.
func start() -> Error:
	if is_up():
		return OK
	var err := _start()
	if err == OK:
		start_error = ""
		next_check = Time.get_ticks_msec() + CHECK_MS
	else:
		server.stop()
		port = 0
		token = ""
	return err

func _storage_ready() -> Error:
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
	return OK

func _start() -> Error:
	var err := _storage_ready()
	if err != OK:
		return err
	if FileAccess.file_exists(CONNECTION):
		var previous = JSON.parse_string(FileAccess.get_file_as_string(CONNECTION))
		if previous is Dictionary and _owner_alive(previous):
			start_error = "Another editor owns this project's connection. Close it first."
			return ERR_ALREADY_IN_USE
	err = server.listen(0, "127.0.0.1")
	if err != OK:
		start_error = "Cannot bind IPv4 loopback: " + error_string(err)
		return err
	port = server.get_local_port()
	token = Crypto.new().generate_random_bytes(32).hex_encode()
	if _write_credentials() != OK:
		start_error = "Cannot write connection credentials."
		return ERR_FILE_CANT_WRITE
	return OK

func _write_credentials() -> Error:
	var file := FileAccess.open(CONNECTION, FileAccess.WRITE)
	if file == null:
		return ERR_FILE_CANT_WRITE
	file.store_string(JSON.stringify({"host": "127.0.0.1", "port": port, "token": token,
		"pid": OS.get_process_id(), "project": ProjectSettings.globalize_path("res://"), "protocol_version": "1.0"}))
	file.close()
	if OS.get_name() != "Windows":
		FileAccess.set_unix_permissions(CONNECTION, 384) # 0600
	return OK

## Whether the editor that wrote `previous` still owns the connection. The decisive evidence is a GodotBridge on its
## port answering a handshake within PROBE_REPLY_MS: OS.is_process_running only knows processes this editor spawned itself
## (false for any other pid on Windows), a dead editor's pid can be reused, and a bare TCP connect succeeds against
## any listener, so an unrelated service on a recycled port would otherwise block takeover. The handshake carries an
## unmatchable token, never the previous one: poll() answers that rejection without the request queue even while an
## operation runs, whereas a valid token would be queued behind it and the live owner judged stale. Anything
## unparseable or unproven counts as stale; a refused loopback port can stay CONNECTING for many seconds on Windows,
## so connecting and sending share PROBE_CONNECT_MS and the reply gets PROBE_REPLY_MS from the send. The reply needs
## the owner's main loop (poll() sends the rejection in the frame that reads it), so an unfocused editor sleeping
## 100 ms per frame is still found; only a silent listener pays the full wait. Accepted limits: an owner that runs
## no frame within PROBE_REPLY_MS (a blocked main thread), or one already at MAX_CLIENTS (it closes the probe
## unanswered), is taken over, and a foreign GodotBridge on the port counts as alive (fail closed).
func _owner_alive(previous: Dictionary) -> bool:
	var pid = previous.get("pid")
	var previous_port = previous.get("port")
	if not (pid is int or pid is float) or not (previous_port is int or previous_port is float):
		return false
	if previous_port < 1 or previous_port > 65535 or previous_port != int(previous_port):
		return false
	if int(pid) == OS.get_process_id():
		return false
	var probe := StreamPeerTCP.new()
	if probe.connect_to_host("127.0.0.1", int(previous_port)) != OK:
		return false
	var alive := _probe_handshake(probe, Time.get_ticks_msec() + PROBE_CONNECT_MS)
	probe.disconnect_from_host()
	return alive

## Sends one handshake frame, which must be connected and sent by `connect_by`, and returns true iff a GodotBridge
## reply to it arrives within PROBE_REPLY_MS. Any answer to the unmatchable token qualifies (AUTHENTICATION_FAILED,
## EDITOR_BUSY); what the owner does with the token is moot.
func _probe_handshake(probe: StreamPeerTCP, connect_by: int) -> bool:
	while probe.get_status() == StreamPeerTCP.STATUS_CONNECTING and Time.get_ticks_msec() < connect_by:
		probe.poll()
		OS.delay_msec(5)
	if probe.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		return false
	var body := JSON.stringify({"protocol_version": "1.0", "request_id": PROBE_ID, "method": "handshake",
		"params": {"token": PROBE_ID}}).to_utf8_buffer()
	var frame := PackedByteArray([(body.size() >> 24) & 255, (body.size() >> 16) & 255, (body.size() >> 8) & 255, body.size() & 255])
	frame.append_array(body)
	while not frame.is_empty():
		if Time.get_ticks_msec() >= connect_by:
			return false
		var sent := probe.put_partial_data(frame)
		if sent[0] != OK:
			return false
		frame = frame.slice(sent[1])
	var give_up := Time.get_ticks_msec() + PROBE_REPLY_MS
	var reply := PackedByteArray()
	while Time.get_ticks_msec() < give_up:
		probe.poll()
		# poll() keeps a peer with unread bytes connected and only reports the close once they are drained, so a
		# reply that arrives together with the owner's close is still read here.
		if probe.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			return false
		var available := mini(probe.get_available_bytes(), PROBE_REPLY_MAX)
		if available > 0:
			var received := probe.get_partial_data(available)
			if received[0] != OK:
				return false
			reply.append_array(received[1])
		if reply.size() >= 4:
			var size := (int(reply[0]) << 24) | (int(reply[1]) << 16) | (int(reply[2]) << 8) | int(reply[3])
			# An HTTP error page decodes as a ~1.2 GB length; do not wait for it.
			if size <= 0 or size > PROBE_REPLY_MAX:
				return false
			if reply.size() >= size + 4:
				var parser := JSON.new()
				if parser.parse(reply.slice(4, size + 4).get_string_from_utf8()) != OK:
					return false
				var data = parser.data
				# A bridge answers the bogus token with a failure envelope; an echo of our own frame has no verdict.
				return data is Dictionary and data.get("protocol_version") == "1.0" and data.get("request_id") == PROBE_ID \
						and data.get("ok") == false and data.get("error") is Dictionary
		OS.delay_msec(5)
	return false

## Called every frame while the plugin wants the endpoint up. Detects a dead listener and a credentials file that
## vanished or now belongs to another editor, so the caller's retry loop can recover.
func maintain() -> void:
	if port == 0:
		return
	if not server.is_listening():
		stop()
		start_error = "The listener stopped unexpectedly."
		return
	var now := Time.get_ticks_msec()
	if now < next_check:
		return
	next_check = now + CHECK_MS
	var saved = null
	if FileAccess.file_exists(CONNECTION):
		saved = JSON.parse_string(FileAccess.get_file_as_string(CONNECTION))
	if saved is Dictionary and saved.get("token") != token:
		# stop() leaves a file with a foreign token alone.
		stop()
		start_error = "Another editor took over this project's connection."
	elif not saved is Dictionary and _storage_ready() == OK:
		_write_credentials()

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
		# A queued or running request keeps its client alive however long it takes; respond() restarts the idle clock.
		if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED or (not client.pending and Time.get_ticks_msec() - client.last > idle_ms):
			_drop(client)
			continue
		if not _flush(client):
			continue
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
				_flush(client) # _owner_alive waits for this rejection: send it now, not one frame later.
				client.closing = true
				continue
			client.authenticated = true
		if queue.size() >= MAX_QUEUE:
			respond(client, id, failure("EDITOR_BUSY", "Request queue is full."))
		else:
			client.pending = true
			queue.append({"client": client, "request": request})

## Sends what the peer takes of client.out; false if the write failed and the client was dropped.
func _flush(client: Dictionary) -> bool:
	if client.out.is_empty():
		return true
	var sent: Array = client.peer.put_partial_data(client.out.slice(0, 65536))
	if sent[0] != OK:
		_drop(client)
		return false
	client.out = client.out.slice(sent[1])
	return true

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
	client.last = Time.get_ticks_msec()

func _drop(client: Dictionary) -> void:
	client.peer.disconnect_from_host()
	clients.erase(client)
	queue = queue.filter(func(item): return item.client != client)

static func failure(code: String, message: String) -> Dictionary:
	return {"ok": false, "error": {"code": code, "message": message}}
