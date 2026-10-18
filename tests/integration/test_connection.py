import json
import socket
import struct

import pytest
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
