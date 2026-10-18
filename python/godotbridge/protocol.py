"""Protocol 1.0: unsigned network-order length followed by UTF-8 JSON."""

import json
import socket
import struct
import time
from typing import Any

from .errors import BridgeError

VERSION = "1.0"
MAX_FRAME = 4 * 1024 * 1024


def encode(value: dict[str, Any]) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    except (ValueError, TypeError) as exc:
        raise BridgeError("INVALID_ARGUMENT", "Request must contain finite JSON values.") from exc
    if len(data) > MAX_FRAME:
        raise BridgeError("INVALID_ARGUMENT", "Frame exceeds the 4 MiB limit.")
    return struct.pack("!I", len(data)) + data


def _read(sock: socket.socket, size: int, deadline: float | None = None) -> bytes:
    data = bytearray()
    while len(data) < size:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Request deadline exceeded")
            sock.settimeout(remaining)
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise BridgeError(
                "EDITOR_DISCONNECTED",
                "Editor closed the connection; inspect state before retrying a mutation.",
            )
        data.extend(chunk)
    return bytes(data)


def receive(sock: socket.socket, deadline: float | None = None) -> dict[str, Any]:
    size = struct.unpack("!I", _read(sock, 4, deadline))[0]
    if not 0 < size <= MAX_FRAME:
        raise BridgeError("INVALID_ARGUMENT", "Invalid response frame size.")
    try:
        result = json.loads(_read(sock, size, deadline).decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise BridgeError("INVALID_ARGUMENT", "Editor sent malformed JSON.") from exc
    if not isinstance(result, dict):
        raise BridgeError("INVALID_ARGUMENT", "Response must be an object.")
    return result
