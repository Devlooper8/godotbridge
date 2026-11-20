"""Connect-phase retries against an in-process fake editor speaking the real framing."""

import json
import socket
import threading
import time
import types

import pytest
from godotbridge import transport
from godotbridge.config import Config
from godotbridge.errors import BridgeError
from godotbridge.protocol import VERSION, encode, receive
from godotbridge.transport import RACE_INTERVAL, RETRY_INTERVAL, Transport


class FakeEditor:
    """Accepts sessions, authenticates the handshake, and records every frame's method."""

    def __init__(self, token="secret", *, close_after_operation=False):
        self.token = token
        self.close_after_operation = close_after_operation
        self.requests: list[str] = []
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self.port = self._listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        self._listener.close()

    def _accept(self):
        while True:
            try:
                connection, _ = self._listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(connection,), daemon=True).start()

    def _serve(self, connection):
        with connection:
            try:
                while True:
                    request = receive(connection)
                    self.requests.append(request["method"])
                    base = {"protocol_version": VERSION, "request_id": request["request_id"]}
                    if request["method"] == "handshake":
                        if request["params"].get("token") != self.token:
                            error = {"code": "AUTHENTICATION_FAILED", "message": "Invalid token."}
                            connection.sendall(encode({**base, "ok": False, "error": error}))
                            return
                        connection.sendall(encode({**base, "ok": True, "result": {"hello": 1}}))
                    elif self.close_after_operation:
                        return
                    else:
                        connection.sendall(encode({**base, "ok": True, "result": {"done": True}}))
            except (BridgeError, OSError):
                return


class Sleeper:
    """Replaces time.sleep: records the delay and runs one scripted action per call."""

    def __init__(self, *actions):
        self.calls: list[float] = []
        self.actions = list(actions)

    def __call__(self, seconds):
        self.calls.append(seconds)
        if self.actions:
            self.actions.pop(0)()


@pytest.fixture
def editor():
    fake = FakeEditor()
    yield fake
    fake.close()


@pytest.fixture
def sleeper(monkeypatch):
    def install(*actions):
        sleeper = Sleeper(*actions)
        monkeypatch.setattr(
            transport, "time", types.SimpleNamespace(monotonic=time.monotonic, sleep=sleeper)
        )
        return sleeper

    return install


def make_config(tmp_path, **settings):
    (tmp_path / "project.godot").write_text("config_version=5\n")
    return Config.load(tmp_path, timeout=5, **settings)


def write_credentials(config, port, token, **overrides):
    data = {
        "host": "127.0.0.1",
        "port": port,
        "token": token,
        "pid": 1,
        "project": str(config.project),
        "protocol_version": VERSION,
    } | overrides
    config.connection_file.parent.mkdir(parents=True, exist_ok=True)
    config.connection_file.write_text(json.dumps(data), encoding="utf-8")


def test_waits_for_the_credentials_file_to_appear(tmp_path, editor, sleeper):
    config = make_config(tmp_path, connect_wait=5)
    pause = sleeper(lambda: write_credentials(config, editor.port, editor.token))
    assert Transport(config).request("editor.status", {}) == {"done": True}
    assert pause.calls == [RETRY_INTERVAL]
    assert editor.requests == ["handshake", "editor.status"]


def test_no_wait_by_default_reports_a_missing_file_immediately(tmp_path, sleeper):
    config = make_config(tmp_path)
    pause = sleeper()
    with pytest.raises(BridgeError) as caught:
        Transport(config).request("editor.status", {})
    assert caught.value.code == "EDITOR_DISCONNECTED"
    assert "no connection file" in caught.value.message
    assert pause.calls == []


def test_wait_runs_out_with_the_same_error_code(tmp_path):
    config = make_config(tmp_path, connect_wait=0.25)
    started = time.monotonic()
    with pytest.raises(BridgeError) as caught:
        Transport(config).request("editor.status", {})
    assert caught.value.code == "EDITOR_DISCONNECTED"
    assert "waited 0.25 s" in caught.value.message
    assert time.monotonic() - started >= 0.25


def test_rotated_token_is_read_again_once_without_a_wait(tmp_path, editor, sleeper):
    config = make_config(tmp_path)
    write_credentials(config, editor.port, "stale-token")
    pause = sleeper(lambda: write_credentials(config, editor.port, editor.token))
    assert Transport(config).request("editor.status", {}) == {"done": True}
    assert pause.calls == [RACE_INTERVAL]
    assert editor.requests == ["handshake", "handshake", "editor.status"]


def test_persistent_authentication_failure_gets_one_extra_attempt(tmp_path, editor, sleeper):
    config = make_config(tmp_path)
    write_credentials(config, editor.port, "wrong")
    pause = sleeper()
    with pytest.raises(BridgeError) as caught:
        Transport(config).request("editor.status", {})
    assert caught.value.code == "AUTHENTICATION_FAILED"
    assert pause.calls == [RACE_INTERVAL]
    assert editor.requests == ["handshake", "handshake"]


def test_half_written_file_is_read_again_once_without_a_wait(tmp_path, editor, sleeper):
    config = make_config(tmp_path)
    config.connection_file.parent.mkdir(parents=True)
    config.connection_file.write_text('{"host": "127.0.0.1", "po', encoding="utf-8")
    pause = sleeper(lambda: write_credentials(config, editor.port, editor.token))
    assert Transport(config).request("editor.status", {}) == {"done": True}
    assert pause.calls == [RACE_INTERVAL]


def test_persistently_invalid_file_is_reported(tmp_path, sleeper):
    config = make_config(tmp_path)
    config.connection_file.parent.mkdir(parents=True)
    config.connection_file.write_text("[]", encoding="utf-8")
    pause = sleeper()
    with pytest.raises(BridgeError) as caught:
        Transport(config).request("editor.status", {})
    assert caught.value.code == "EDITOR_DISCONNECTED"
    assert "Invalid connection file" in caught.value.message
    assert pause.calls == [RACE_INTERVAL]


def test_connection_refused_is_retried_within_the_wait(tmp_path, editor, sleeper, monkeypatch):
    config = make_config(tmp_path, connect_wait=5)
    write_credentials(config, editor.port, editor.token)
    real = socket.create_connection
    attempts = []

    def refuse_once(address, timeout=None):
        attempts.append(address)
        if len(attempts) == 1:
            raise ConnectionRefusedError("refused")
        return real(address, timeout)

    monkeypatch.setattr(socket, "create_connection", refuse_once)
    pause = sleeper()
    assert Transport(config).request("editor.status", {}) == {"done": True}
    assert len(attempts) == 2 and pause.calls == [RETRY_INTERVAL]


def test_connection_refused_is_final_without_a_wait(tmp_path, sleeper, monkeypatch):
    config = make_config(tmp_path)
    write_credentials(config, 1, "token")

    def refuse(address, timeout=None):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(socket, "create_connection", refuse)
    pause = sleeper()
    with pytest.raises(BridgeError) as caught:
        Transport(config).request("editor.status", {})
    assert caught.value.code == "EDITOR_DISCONNECTED"
    assert "refused" in caught.value.message
    assert pause.calls == []


def test_operation_is_never_replayed(tmp_path, sleeper):
    fake = FakeEditor(close_after_operation=True)
    try:
        config = make_config(tmp_path, connect_wait=5)
        write_credentials(config, fake.port, fake.token)
        pause = sleeper()
        with pytest.raises(BridgeError) as caught:
            Transport(config).request("node.create", {"name": "A"})
        assert caught.value.code == "EDITOR_DISCONNECTED"
        assert pause.calls == []
        assert fake.requests == ["handshake", "node.create"]
    finally:
        fake.close()


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"host": "10.0.0.5"}, "loopback"),
        ({"project": "somewhere-else"}, "another project"),
    ],
)
def test_denied_connections_are_never_retried(tmp_path, editor, sleeper, overrides, message):
    config = make_config(tmp_path, connect_wait=5)
    write_credentials(config, editor.port, editor.token, **overrides)
    pause = sleeper()
    with pytest.raises(BridgeError) as caught:
        Transport(config).request("editor.status", {})
    assert caught.value.code == "FILE_ACCESS_DENIED" and message in caught.value.message
    assert pause.calls == [] and editor.requests == []


def test_protocol_mismatch_is_never_retried(tmp_path, sleeper):
    class OldEditor(FakeEditor):
        def _serve(self, connection):
            with connection:
                request = receive(connection)
                self.requests.append(request["method"])
                connection.sendall(
                    encode({"protocol_version": "0.9", "request_id": request["request_id"]})
                )

    fake = OldEditor()
    try:
        config = make_config(tmp_path, connect_wait=5)
        write_credentials(config, fake.port, fake.token)
        pause = sleeper()
        with pytest.raises(BridgeError) as caught:
            Transport(config).request("editor.status", {})
        assert caught.value.code == "PROTOCOL_MISMATCH"
        assert pause.calls == [] and fake.requests == ["handshake"]
    finally:
        fake.close()
