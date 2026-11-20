import contextlib
import dataclasses
import json
import os
import re
import select
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

import pytest
from conftest import prepare_project
from godotbridge.client import Client
from godotbridge.discovery import discover
from godotbridge.errors import BridgeError
from godotbridge.protocol import encode, receive

pytestmark = pytest.mark.engine


def raw_connection(editor):
    credentials = json.loads(editor.config.connection_file.read_text(encoding="utf-8"))
    return socket.create_connection(("127.0.0.1", credentials["port"]), 5), credentials


def test_authenticated_connection_and_reconnect(editor):
    for _ in range(3):
        assert editor.call("project.info")["godot_version"].startswith("4.7")
        assert editor.call("editor.status")["connected"] is True


def test_wrong_token(editor):
    sock, _ = raw_connection(editor)
    with sock:
        sock.sendall(
            encode(
                {
                    "protocol_version": "1.0",
                    "request_id": "bad-token",
                    "method": "handshake",
                    "params": {"token": "wrong"},
                }
            )
        )
        result = receive(sock)
        assert result["error"]["code"] == "AUTHENTICATION_FAILED"


def test_malformed_json(editor):
    sock, _ = raw_connection(editor)
    with sock:
        sock.sendall(struct.pack("!I", 4) + b"nope")
        assert receive(sock)["error"]["code"] == "INVALID_ARGUMENT"
    assert editor.call("editor.status")["connected"]


def test_fragmented_frame(editor):
    sock, credentials = raw_connection(editor)
    with sock:
        frame = encode(
            {
                "protocol_version": "1.0",
                "request_id": "split",
                "method": "handshake",
                "params": {"token": credentials["token"]},
            }
        )
        for byte in frame:
            sock.sendall(bytes([byte]))
        assert receive(sock)["ok"]


def read_credentials(config):
    try:
        return json.loads(config.connection_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # missing, or caught mid-write


def test_credentials_file_is_restored_after_deletion(editor):
    before = read_credentials(editor.config)
    editor.config.connection_file.unlink()
    deadline = time.monotonic() + 6
    restored = None
    while restored is None and time.monotonic() < deadline:
        time.sleep(0.1)
        restored = read_credentials(editor.config)
    assert restored is not None, "the plugin did not rewrite connection.json within 6 s"
    assert restored["token"] == before["token"] and restored["port"] == before["port"]
    assert editor.call("editor.status")["connected"] is True


def test_connect_wait_spans_a_credentials_gap(editor):
    editor.config.connection_file.unlink()
    patient = Client(dataclasses.replace(editor.config, connect_wait=10))
    # No polling here: the client itself rides out the gap until the plugin rewrites the file.
    assert patient.call("editor.status")["connected"] is True


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_stale_owner_with_a_reused_pid_is_taken_over(extra_editor):
    seeded = {}

    def seed(config):
        # A dead editor's file whose pid now belongs to a live, unrelated process (this one).
        seeded.update(
            host="127.0.0.1",
            port=free_port(),
            token="dead-editor",
            pid=os.getpid(),
            project=str(config.project),
            protocol_version="1.0",
        )
        config.connection_file.parent.mkdir(parents=True, exist_ok=True)
        config.connection_file.write_text(json.dumps(seeded), encoding="utf-8")

    with extra_editor(seed) as client:
        assert client.call("editor.status")["connected"] is True
        current = read_credentials(client.config)
        assert current["token"] != seeded["token"] and current["port"] != seeded["port"]
        assert current["pid"] != os.getpid()


@contextlib.contextmanager
def unrelated_service(kind):
    """A loopback listener that is not a GodotBridge; yields its port.

    "silent" never accepts (the kernel still completes the TCP handshake), "close" drops each connection,
    "http" answers like a web server that rejects the request, "echo" sends every byte straight back.
    """
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    server.settimeout(0.1)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                if kind == "http":
                    connection.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                elif kind == "echo":
                    # The probe's own frame comes back: right protocol version and request id, but no verdict.
                    connection.settimeout(0.5)
                    with contextlib.suppress(OSError):
                        while chunk := connection.recv(65536):
                            connection.sendall(chunk)

    thread = threading.Thread(target=serve, daemon=True)
    if kind != "silent":
        thread.start()
    try:
        yield server.getsockname()[1]
    finally:
        stop.set()
        if thread.is_alive():
            thread.join(2)
        server.close()


@pytest.mark.parametrize("kind", ["silent", "close", "http", "echo"])
def test_stale_owner_whose_port_is_held_by_an_unrelated_service_is_taken_over(extra_editor, kind):
    with unrelated_service(kind) as service_port:

        def seed(config):
            # A dead editor's file whose ephemeral port was recycled by something else.
            config.connection_file.parent.mkdir(parents=True, exist_ok=True)
            config.connection_file.write_text(
                json.dumps(
                    {
                        "host": "127.0.0.1",
                        "port": service_port,
                        "token": "dead-editor",
                        "pid": os.getpid(),
                        "project": str(config.project),
                        "protocol_version": "1.0",
                    }
                ),
                encoding="utf-8",
            )

        # The listener stays up for the whole block: the editor has to decide against it being there.
        with extra_editor(seed) as client:
            assert client.call("editor.status")["connected"] is True
            current = read_credentials(client.config)
            assert current["token"] != "dead-editor" and current["port"] != service_port
            assert current["pid"] != os.getpid()


def test_live_owner_keeps_its_connection(extra_editor):
    with extra_editor() as owner:
        before = read_credentials(owner.config)
        log = owner.config.project / "second.log"
        with extra_editor(config=owner.config, name="second"):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if log.exists() and "Another editor owns" in log.read_text(
                    encoding="utf-8", errors="replace"
                ):
                    break
                time.sleep(0.5)
            else:
                pytest.fail("the second editor never reported the live owner")
        assert read_credentials(owner.config) == before
        assert owner.call("editor.status")["connected"] is True


def delay(seconds):
    return f"await (Engine.get_main_loop() as SceneTree).create_timer({seconds}).timeout"


def patch_addon(config, hooks, watchdog_ms=None):
    """Instrument the project's own copy of the addon before its editor starts; the repository stays untouched.

    `hooks` maps an operation to GDScript statements run at the top of dispatch(); `never_signal` never fires.
    """
    addon = config.project / "addons/godot_bridge"

    def substitute(path, pattern, replacement):
        text = path.read_bytes().decode("utf-8")
        newline = "\r\n" if "\r\n" in text else "\n"
        text, count = re.subn(pattern, lambda match: replacement(match, newline), text, count=1)
        assert count == 1, f"{path.name} no longer matches {pattern!r}; update the test"
        path.write_bytes(text.encode("utf-8"))

    def inject(match, newline):
        lines = ["signal never_signal", match.group(0).rstrip("\r\n")]
        for method, statements in hooks.items():
            lines.append(f'\tif method == "{method}":')
            lines.extend(f"\t\t{statement}" for statement in statements)
        return newline.join(lines) + newline

    substitute(
        addon / "command_dispatcher.gd",
        r"func dispatch\(method: String, params: Dictionary\) -> Dictionary:\r?\n",
        inject,
    )
    if watchdog_ms is not None:
        substitute(
            addon / "plugin.gd",
            r"const REQUEST_WATCHDOG_MS := \d+",
            lambda match, newline: f"const REQUEST_WATCHDOG_MS := {watchdog_ms}",
        )


def test_a_request_that_never_finishes_is_answered_and_the_editor_recovers(extra_editor):
    def before_launch(config):
        patch_addon(config, {"scene.list": ["await never_signal"]}, watchdog_ms=3000)

    with extra_editor(before_launch) as client:
        # The client waits far longer than the watchdog, so this TIMEOUT can only come from the plugin.
        patient = Client(dataclasses.replace(client.config, timeout=15))
        started = time.monotonic()
        with pytest.raises(BridgeError) as hung:
            patient.call("scene.list")
        assert hung.value.code == "TIMEOUT" and "did not finish" in hung.value.message
        assert time.monotonic() - started < 10
        assert client.call("editor.status")["connected"] is True


def test_a_handler_script_error_is_answered_instead_of_wedging_the_editor(extra_editor):
    def before_launch(config):
        patch_addon(config, {"scene.list": ["var broken = null", "broken.foo()"]})

    with extra_editor(before_launch) as client:
        started = time.monotonic()
        with pytest.raises(BridgeError) as failed:
            client.call("scene.list")
        assert failed.value.code == "INTERNAL_ERROR"
        assert time.monotonic() - started < 5
        assert client.call("editor.status")["connected"] is True


def test_an_abandoned_request_that_resumes_late_does_not_disturb_the_next_one(extra_editor):
    # Watchdog 4 s. A hangs 5.5 s: answered at 4 s, resumes at 5.5 s while B (3 s) runs from 4 s to 7 s.
    hooks = {"project.info": [delay(5.5)], "editor.diagnostics": [delay(3.0)]}

    def before_launch(config):
        patch_addon(config, hooks, watchdog_ms=4000)

    def connect(client):
        sock, credentials = raw_connection(client)
        sock.sendall(
            encode(
                {
                    "protocol_version": "1.0",
                    "request_id": "hs",
                    "method": "handshake",
                    "params": {"token": credentials["token"]},
                }
            )
        )
        assert receive(sock, time.monotonic() + 5)["ok"]
        return sock

    def send(sock, method, request_id):
        sock.sendall(
            encode(
                {
                    "protocol_version": "1.0",
                    "request_id": request_id,
                    "method": method,
                    "params": {},
                }
            )
        )

    with extra_editor(before_launch) as client:
        # Handshakes are queued like any request, so authenticate every socket before anything hangs.
        with connect(client) as a, connect(client) as b, connect(client) as c:
            start = time.monotonic()
            send(a, "project.info", "A")
            time.sleep(1)
            send(b, "editor.diagnostics", "B")
            reply = receive(a, start + 15)
            assert reply["request_id"] == "A" and reply["error"]["code"] == "TIMEOUT"
            assert 3.5 < time.monotonic() - start < 5.2, "the watchdog, not the hook, answered A"
            # A resumes at 5.5 s; C arrives after that while B is still running.
            time.sleep(max(0, start + 6.25 - time.monotonic()))
            send(c, "editor.status", "C")
            ready = select.select([b, c], [], [], 15)[0]
            assert b in ready, "C was served while B was still running"
            assert receive(b, time.monotonic() + 5)["request_id"] == "B"
            assert receive(c, time.monotonic() + 5)["request_id"] == "C"
            assert not select.select([a], [], [], 0.5)[0], (
                "the abandoned request answered a second time"
            )


def run_harness(request, tmp_path, name):
    """Run tests/harness/<name> against the transport alone: a headless script drives it instead of an editor."""
    if not request.config.getoption("--engine"):
        pytest.skip("Pass --engine to run actual Godot integration tests")
    config = prepare_project(tmp_path / "project")
    env = os.environ.copy()
    for variable in (
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        env[variable] = str(tmp_path / "user" / variable)
        (tmp_path / "user" / variable).mkdir(parents=True)
    harness = Path(__file__).resolve().parents[1] / "harness" / name
    result = subprocess.run(
        [
            str(discover().executable),
            "--headless",
            "--path",
            str(config.project),
            "--script",
            str(harness),
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        env=env,
    )
    output = result.stdout + result.stderr
    assert "SCRIPT ERROR" not in output and "Parse Error" not in output, output
    assert result.returncode == 0, output


def test_pending_request_is_not_dropped_as_idle(request, tmp_path):
    """poll() keeps a client with a queued or running request however long it takes, and respond() restarts its
    idle clock. The harness lowers the idle limit, which the plugin keeps at 30 s."""
    run_harness(request, tmp_path, "transport_idle.gd")


def test_live_owner_with_slow_frames_is_not_judged_stale(request, tmp_path):
    """A second editor probes the first one's port at startup. An owner running 400 ms frames (an unfocused or busy
    editor) must still answer within the probe's reply window, and a rejection must not wait for the next frame."""
    run_harness(request, tmp_path, "transport_probe.gd")
