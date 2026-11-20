"""One authenticated session per operation; never automatically replay mutations.

Only the connect phase (read credentials, TCP connect, handshake) is retried, and only until
`connect_wait` runs out, re-reading the credentials file on every attempt. The operation frame is
sent exactly once; a failure after that point is reported, never replayed. The operation's own
deadline starts when the connect phase succeeded.
"""

import json
import socket
import time
import uuid
from pathlib import Path
from typing import Any

from .config import Config
from .errors import BridgeError
from .protocol import VERSION, encode, receive

RETRY_INTERVAL = 0.2
RACE_INTERVAL = 0.1  # Extra attempt for failures that can be a half-finished credentials write.


class _Transient(Exception):
    """A connect-phase failure that may disappear on its own. `race` names a write race, if it is one."""

    def __init__(self, error: BridgeError, race: str | None = None):
        super().__init__(error.message)
        self.error, self.race = error, race


class Transport:
    def __init__(self, config: Config):
        self.config = config

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            sock, hello = self._connect()
            with sock:
                if method == "handshake":
                    return hello
                deadline = time.monotonic() + self.config.timeout
                return self._exchange(sock, method, params, deadline)
        except OSError as exc:
            raise self._translate(exc) from exc

    @staticmethod
    def _translate(exc: OSError) -> BridgeError:
        if isinstance(exc, TimeoutError):
            return BridgeError(
                "TIMEOUT",
                "Editor request timed out. Its outcome may be unknown; inspect before retrying.",
            )
        return BridgeError("EDITOR_DISCONNECTED", f"Cannot connect to the editor: {exc}")

    def _connect(self) -> tuple[socket.socket, dict[str, Any]]:
        wait = self.config.connect_wait
        wait_until = time.monotonic() + wait
        spent: set[str] = set()
        while True:
            try:
                return self._attempt()
            except _Transient as transient:
                remaining = wait_until - time.monotonic()
                if remaining > 0:
                    delay = min(RETRY_INTERVAL, remaining)
                elif transient.race and transient.race not in spent:
                    spent.add(transient.race)
                    delay = RACE_INTERVAL
                else:
                    error = transient.error
                    if wait:
                        error = BridgeError(
                            error.code, f"{error.message} (waited {wait:g} s)", error.details
                        )
                    raise error from transient
                time.sleep(delay)

    def _attempt(self) -> tuple[socket.socket, dict[str, Any]]:
        try:
            credentials = json.loads(self.config.connection_file.read_text(encoding="utf-8"))
            if not isinstance(credentials, dict):
                raise ValueError("Invalid connection data")
            if credentials.get("host") != "127.0.0.1":
                raise BridgeError(
                    "FILE_ACCESS_DENIED", "Only IPv4 loopback endpoints are permitted."
                )
            project = credentials.get("project", "")
            if not isinstance(project, str):
                raise ValueError("Invalid connection data")
            if Path(project).resolve() != self.config.project:
                raise BridgeError("FILE_ACCESS_DENIED", "Connection belongs to another project.")
            port = credentials["port"]
            token = credentials["token"]
            if type(port) is not int or not 0 < port < 65536 or not isinstance(token, str):
                raise ValueError("Invalid connection data")
        except FileNotFoundError as exc:
            raise _Transient(
                BridgeError(
                    "EDITOR_DISCONNECTED",
                    "Enable GodotBridge in the project's editor; no connection file exists.",
                )
            ) from exc
        except (KeyError, ValueError) as exc:
            raise _Transient(
                BridgeError("EDITOR_DISCONNECTED", "Invalid connection file; restart the plugin."),
                race="file",
            ) from exc
        try:
            sock = socket.create_connection(("127.0.0.1", port), self.config.timeout)
        except OSError as exc:
            raise _Transient(self._translate(exc)) from exc
        try:
            hello = self._exchange(
                sock, "handshake", {"token": token}, time.monotonic() + self.config.timeout
            )
        except BridgeError as exc:
            sock.close()
            if exc.code in {"AUTHENTICATION_FAILED", "EDITOR_DISCONNECTED"}:
                # A rotated token is a write race (read, then rewritten before connecting).
                raise _Transient(
                    exc, race="token" if exc.code == "AUTHENTICATION_FAILED" else None
                ) from exc
            raise
        except ConnectionError as exc:
            sock.close()
            raise _Transient(self._translate(exc)) from exc
        except BaseException:
            sock.close()
            raise
        return sock, hello

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
