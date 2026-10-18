import json
import socket
import struct

import pytest
from godotbridge.protocol import MAX_FRAME, encode, receive

pytestmark = pytest.mark.engine


def raw(editor):
    credentials = json.loads(editor.config.connection_file.read_text(encoding="utf-8"))
    peer = socket.create_connection(("127.0.0.1", credentials["port"]), timeout=5)
    peer.sendall(
        encode(
            {
                "protocol_version": "1.0",
                "request_id": "hello",
                "method": "handshake",
                "params": {"token": credentials["token"]},
            }
        )
    )
    assert receive(peer)["ok"]
    return peer


@pytest.mark.parametrize(
    "method,params,code",
    [
        ("node.create", {"name": "Bad", "type": "OS"}, "INVALID_ARGUMENT"),
        ("node.set_transform", {"path": ".", "position": [1, 2]}, "INVALID_ARGUMENT"),
        ("node.set_transform", {"path": ".", "position": [1e300, 0, 0]}, "INVALID_ARGUMENT"),
        ("node.create", {"name": "Bad", "unexpected": True}, "INVALID_ARGUMENT"),
        (
            "node.set_property",
            {"path": ".", "property": "script", "value": {"type": "GDScript"}},
            "UNSUPPORTED_PROPERTY",
        ),
        ("object.call", {"method": "queue_free"}, "UNSUPPORTED_OPERATION"),
    ],
)
def test_plugin_validates_untrusted_requests(editor, method, params, code):
    with raw(editor) as peer:
        peer.sendall(
            encode(
                {
                    "protocol_version": "1.0",
                    "request_id": "direct",
                    "method": method,
                    "params": params,
                }
            )
        )
        assert receive(peer)["error"]["code"] == code


def test_oversize_and_protocol_mismatch(editor):
    with raw(editor) as peer:
        peer.sendall(struct.pack("!I", MAX_FRAME + 1))
        assert receive(peer)["error"]["code"] == "INVALID_ARGUMENT"
    with raw(editor) as peer:
        peer.sendall(
            encode(
                {
                    "protocol_version": "2.0",
                    "request_id": "wrong-version",
                    "method": "editor.status",
                    "params": {},
                }
            )
        )
        assert receive(peer)["error"]["code"] == "PROTOCOL_MISMATCH"
    assert editor.call("editor.status")["connected"]


def test_instance_and_inherited_boundaries(editor):
    base = editor.config.project / "scenes"
    (base / "instance-source.tscn").write_text(
        '[gd_scene format=3]\n[node name="Source" type="Node3D"]\n[node name="Child" type="Node3D" parent="."]\n',
        encoding="utf-8",
    )
    (base / "instance-parent.tscn").write_text(
        '[gd_scene load_steps=2 format=3]\n[ext_resource type="PackedScene" path="res://scenes/instance-source.tscn" id="1"]\n[node name="Root" type="Node3D"]\n[node name="Instance" parent="." instance=ExtResource("1")]\n',
        encoding="utf-8",
    )
    (base / "inherited.tscn").write_text(
        '[gd_scene load_steps=2 format=3]\n[ext_resource type="PackedScene" path="res://scenes/instance-source.tscn" id="1"]\n[node name="Inherited" instance=ExtResource("1")]\n',
        encoding="utf-8",
    )
    from godotbridge.errors import BridgeError

    editor.call("scene.open", path="res://scenes/instance-parent.tscn")
    for path in ("Instance", "Instance/Child"):
        with pytest.raises(BridgeError) as error:
            editor.call("node.delete", path=path)
        assert error.value.code == "READ_ONLY_RESOURCE"
    editor.call("scene.open", path="res://scenes/inherited.tscn")
    with pytest.raises(BridgeError) as error:
        editor.call("node.create", name="Restricted")
    assert error.value.code == "READ_ONLY_RESOURCE"
