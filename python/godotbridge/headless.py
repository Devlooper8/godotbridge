"""Supported engine command-line operations with bounded diagnostics and deadlines."""

import json
import os
import subprocess
import threading
from collections import deque

from .config import Config
from .diagnostics import classify
from .discovery import discover
from .errors import BridgeError
from .install import addon_source
from .transport import Transport


def worker_environment(config: Config) -> dict[str, str]:
    """Keep automation workers' settings and user:// data inside this project."""
    env = os.environ.copy()
    for variable in (
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        directory = config.private_path("worker-user") / variable
        directory.mkdir(parents=True, exist_ok=True)
        env[variable] = str(directory)
    return env


def run_engine(config: Config, args: list[str]) -> dict:
    engine = discover(config.godot)
    command = [str(engine.executable), "--headless", "--path", str(config.project), *args]
    chunks: deque[bytes] = deque(maxlen=256)  # At most 1 MiB of recent logs.
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=worker_environment(config),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as exc:
        raise BridgeError("GODOT_NOT_FOUND", f"Cannot launch Godot: {exc}") from exc

    def drain():
        assert process.stdout is not None
        while chunk := process.stdout.read(4096):
            chunks.append(chunk)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=config.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait(timeout=10)
    reader.join(timeout=10)
    output = b"".join(chunks).decode("utf-8", errors="replace")
    if process.stdout:
        process.stdout.close()
    result = {"exit_code": process.returncode, "godot_version": engine.version, **classify(output)}
    if timed_out:
        raise BridgeError(
            "TIMEOUT", "Headless engine deadline exceeded; process was stopped.", result
        )
    return result


def require_offline(config: Config):
    if not config.connection_file.exists():
        return
    try:
        Transport(config).request("handshake", {})
    except BridgeError as exc:
        if exc.code == "EDITOR_DISCONNECTED":
            return
        raise
    raise BridgeError("EDITOR_BUSY", "Close this project's editor before importing or installing.")


def import_project(config: Config) -> dict:
    require_offline(config)
    result = run_engine(config, ["--editor", "--import"])
    if result["exit_code"] or result["errors"]:
        raise BridgeError("TRANSACTION_FAILED", "Godot import failed; see diagnostics.", result)
    return result


def validate_project(config: Config) -> dict:
    # This runner reads existing imported resources. It does not launch another editor.
    result = run_engine(config, ["--script", str(addon_source() / "validate_project.gd")])
    summary = None
    for line in result["log"].splitlines():
        if line.startswith("GODOTBRIDGE_RESULT="):
            summary = json.loads(line.split("=", 1)[1])
    result["validation"] = summary
    if result["exit_code"] or result["errors"] or not summary or not summary["valid"]:
        raise BridgeError(
            "TRANSACTION_FAILED",
            "Project validation failed; import missing resources or fix reported errors.",
            result,
        )
    return result


def project_info(config: Config) -> dict:
    result = run_engine(config, ["--script", str(addon_source() / "project_info.gd")])
    if not result["exit_code"] and not result["errors"]:
        for line in result["log"].splitlines():
            if line.startswith("GODOTBRIDGE_RESULT="):
                return json.loads(line.split("=", 1)[1])
    raise BridgeError("TRANSACTION_FAILED", "Could not read project settings with Godot.", result)


def check_script(config: Config, path: str) -> dict:
    target = config.resource_path(path, suffix=".gd")
    if not target.is_file():
        raise BridgeError("RESOURCE_NOT_FOUND", f"Script does not exist: {path}")
    result = run_engine(config, ["--check-only", "--script", str(target)])
    if result["exit_code"] or result["errors"]:
        raise BridgeError("TRANSACTION_FAILED", "Script parsing failed.", result)
    return result


def open_project(config: Config) -> dict:
    engine = discover(config.godot)
    process = subprocess.Popen(
        [str(engine.executable), "--editor", "--path", str(config.project)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return {"pid": process.pid, "project": str(config.project), "godot_version": engine.version}
