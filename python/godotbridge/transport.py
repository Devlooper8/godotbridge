"""One authenticated session per operation; never automatically replay mutations."""

import json
import socket
import time
import uuid
from pathlib import Path
from typing import Any

from .config import Config
from .errors import BridgeError
from .protocol import VERSION, encode, receive


class Transport:
    def __init__(self, config: Config):
        self.config = config

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.timeout
        try:
            credentials = json.loads(self.config.connection_file.read_text(encoding="utf-8"))
            if credentials.get("host") != "127.0.0.1":
                raise BridgeError(
                    "FILE_ACCESS_DENIED", "Only IPv4 loopback endpoints are permitted."
                )
            if Path(credentials.get("project", "")).resolve() != self.config.project:
                raise BridgeError("FILE_ACCESS_DENIED", "Connection belongs to another project.")
            port = credentials["port"]
            token = credentials["token"]
            if type(port) is not int or not 0 < port < 65536 or not isinstance(token, str):
                raise ValueError("Invalid connection data")
            with socket.create_connection(("127.0.0.1", port), self.config.timeout) as sock:
                hello = self._exchange(sock, "handshake", {"token": token}, deadline)
                if method == "handshake":
                    return hello
                return self._exchange(sock, method, params, deadline)
        except FileNotFoundError as exc:
            raise BridgeError(
                "EDITOR_DISCONNECTED",
                "Enable GodotBridge in the project's editor; no connection file exists.",
            ) from exc
        except (KeyError, ValueError) as exc:
            raise BridgeError(
                "EDITOR_DISCONNECTED", "Invalid connection file; restart the plugin."
            ) from exc
        except TimeoutError as exc:
            raise BridgeError(
                "TIMEOUT",
                "Editor request timed out. Its outcome may be unknown; inspect before retrying.",
            ) from exc
        except OSError as exc:
            raise BridgeError(
                "EDITOR_DISCONNECTED", f"Cannot connect to the editor: {exc}"
            ) from exc

    @staticmethod
    def _exchange(
        sock: socket.socket, method: str, params: dict[str, Any], deadline: float | None = None
    ) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        sock.sendall(
            encode(
                {
                    "protocol_version": VERSION,
                    "request_id": request_id,
                    "method": method,
                    "params": params,
                }
            )
        )
        response = receive(sock, deadline)
        if response.get("protocol_version") != VERSION:
            raise BridgeError("PROTOCOL_MISMATCH", "Editor uses an incompatible protocol.")
        if response.get("request_id") != request_id:
            raise BridgeError("INTERNAL_ERROR", "Response request ID does not match.")
        if response.get("ok") is not True:
            error = response.get("error", {})
            raise BridgeError(
                error.get("code", "INTERNAL_ERROR"),
                error.get("message", "Invalid response"),
                error.get("details"),
            )
        return response["result"]
