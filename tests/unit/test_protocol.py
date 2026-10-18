import json
import socket
import struct

import pytest
from godotbridge.errors import BridgeError
from godotbridge.protocol import MAX_FRAME, encode, receive


def test_network_order_utf8():
    frame = encode({"text": "žluťoučký"})
    assert struct.unpack("!I", frame[:4])[0] == len(frame[4:])
    assert json.loads(frame[4:]) == {"text": "žluťoučký"}


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite(value):
    with pytest.raises(BridgeError, match="finite"):
        encode({"value": value})


def test_oversize_response():
    left, right = socket.socketpair()
    try:
        left.sendall(struct.pack("!I", MAX_FRAME + 1))
        with pytest.raises(BridgeError, match="frame size"):
            receive(right)
    finally:
        left.close()
        right.close()
