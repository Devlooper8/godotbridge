extends SceneTree
## Drives the real transport_server.gd as an editor with slow frames and asks it, from a worker thread, the question a
## second editor asks at startup (the real _owner_alive). Run by test_connection.py as
## `godot --headless --path <project with the addon> --script transport_probe.gd`. Exit code 0 means success.

const Transport = preload("res://addons/godot_bridge/transport_server.gd")
const FRAME_MS := 400 # A busy or unfocused editor: past the probe's connect phase, well inside its reply phase.
const PROBES := 3

var transport = Transport.new()
var peer := StreamPeerTCP.new()

func _initialize() -> void:
	var failure := _run()
	if failure != "":
		printerr("TRANSPORT HARNESS FAILED: " + failure)
	transport.stop()
	quit(1 if failure != "" else 0)

func _wait(done: Callable) -> bool:
	for _i in 400:
		if done.call():
			return true
		OS.delay_msec(5)
	return false

func _connected() -> bool:
	peer.poll()
	return peer.get_status() == StreamPeerTCP.STATUS_CONNECTED

func _closing() -> bool:
	transport.poll()
	return not transport.clients.is_empty() and transport.clients[0].closing

func _answered() -> bool:
	peer.poll()
	return peer.get_available_bytes() > 4

## poll() must put a rejection on the wire in the frame that decides it, not one frame later.
func _rejection_is_flushed() -> String:
	peer.connect_to_host("127.0.0.1", transport.port)
	if not _wait(_connected):
		return "client never connected"
	var body := JSON.stringify({"protocol_version": "1.0", "request_id": "wrong", "method": "handshake",
		"params": {"token": "wrong"}}).to_utf8_buffer()
	var frame := PackedByteArray([0, 0, (body.size() >> 8) & 255, body.size() & 255])
	frame.append_array(body)
	peer.put_data(frame)
	if not _wait(_closing):
		return "the rejection never closed the client"
	if not transport.clients[0].out.is_empty():
		return "the rejection waited for the next poll() to be sent"
	if not _wait(_answered):
		return "the rejection never arrived"
	var bytes: PackedByteArray = peer.get_partial_data(peer.get_available_bytes())[1]
	var reply := bytes.slice(4).get_string_from_utf8()
	return "" if "AUTHENTICATION_FAILED" in reply else "unexpected answer: " + reply

func _probe_owner() -> Array:
	# A pid other than ours, or _owner_alive treats the file as this editor's own.
	var previous := {"pid": OS.get_process_id() + 1, "port": transport.port}
	var verdicts := []
	for _i in PROBES:
		var started := Time.get_ticks_msec()
		verdicts.append([transport._owner_alive(previous), Time.get_ticks_msec() - started])
	return verdicts

func _run() -> String:
	if transport.start() != OK:
		return "start failed: " + transport.start_error
	var failures := []
	var flushed := _rejection_is_flushed()
	if flushed != "":
		failures.append(flushed)
	var worker := Thread.new()
	worker.start(_probe_owner)
	while worker.is_alive():
		transport.poll()
		OS.delay_msec(FRAME_MS)
	var verdicts: Array = worker.wait_to_finish()
	print("owner probe verdicts [alive, ms]: ", verdicts)
	for verdict in verdicts:
		if not verdict[0]:
			failures.append("a live owner with %d ms frames was judged stale after %d ms" % [FRAME_MS, verdict[1]])
			break
	return "; ".join(failures)
