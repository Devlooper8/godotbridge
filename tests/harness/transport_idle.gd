extends SceneTree
## Drives the real transport_server.gd with a lowered idle limit (the plugin's is 30 s); run by test_connection.py as
## `godot --headless --path <project with the addon> --script transport_idle.gd`. Exit code 0 means success.

const Transport = preload("res://addons/godot_bridge/transport_server.gd")
const IDLE_MS := 300

var transport = Transport.new()
var peer := StreamPeerTCP.new()
var reply := PackedByteArray()

func _initialize() -> void:
	var failure := _run()
	if failure != "":
		printerr("TRANSPORT HARNESS FAILED: " + failure)
	transport.stop()
	quit(1 if failure != "" else 0)

## Pumps both ends for `ms`, or until `done` is true.
func _pump(ms: int, done := Callable()) -> bool:
	var give_up := Time.get_ticks_msec() + ms
	while Time.get_ticks_msec() < give_up:
		transport.poll()
		peer.poll()
		if done.is_valid() and done.call():
			return true
		OS.delay_msec(5)
	return false

func _reply_complete() -> bool:
	if peer.get_status() == StreamPeerTCP.STATUS_CONNECTED and peer.get_available_bytes() > 0:
		reply.append_array(peer.get_partial_data(peer.get_available_bytes())[1])
	return reply.size() >= 4 and reply.size() >= 4 + ((reply[2] << 8) | reply[3])

func _run() -> String:
	transport.idle_ms = IDLE_MS
	if transport.start() != OK:
		return "start failed: " + transport.start_error
	peer.connect_to_host("127.0.0.1", transport.port)
	if not _pump(2000, func(): return peer.get_status() == StreamPeerTCP.STATUS_CONNECTED):
		return "client never connected"
	var body := JSON.stringify({"protocol_version": "1.0", "request_id": "r1", "method": "handshake",
		"params": {"token": transport.token}}).to_utf8_buffer()
	var frame := PackedByteArray([0, 0, (body.size() >> 8) & 255, body.size() & 255])
	frame.append_array(body)
	peer.put_data(frame)
	if not _pump(2000, func(): return transport.queue.size() == 1):
		return "the request was never queued"
	var client: Dictionary = transport.clients[0]
	# The plugin is not running, so nothing answers: the request stays pending for three idle limits.
	_pump(3 * IDLE_MS)
	if transport.clients.size() != 1 or peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		return "a client with a pending request was dropped as idle"
	transport.respond(client, "r1", {"ok": true, "result": {}})
	_pump(2000, _reply_complete)
	if reply.size() < 4:
		return "the answer to a long-pending request never arrived (respond() must restart the idle clock)"
	var parsed = JSON.parse_string(reply.slice(4).get_string_from_utf8())
	if not parsed is Dictionary or parsed.get("request_id") != "r1" or parsed.get("ok") != true:
		return "unexpected answer: " + reply.get_string_from_utf8()
	# Control: once nothing is pending the idle limit still applies.
	if not _pump(3 * IDLE_MS, func(): return transport.clients.is_empty()):
		return "an idle client without a pending request was never dropped"
	return ""
