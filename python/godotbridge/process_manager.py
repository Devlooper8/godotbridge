"""A detached supervisor owns the game process, bounded logs and stop requests.

We never signal a PID loaded from disk. Only the supervisor's own Popen child can
be terminated, so PID reuse cannot cause a later CLI call to kill another app.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from .config import Config
from .diagnostics import classify
from .discovery import discover
from .errors import BridgeError
from .headless import worker_environment
from .install import addon_source


def directory(config: Config) -> Path:
    path = config.private_path("game")
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_json(path: Path, value: Any):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def status(config: Config) -> dict:
    path = directory(config) / "status.json"
    if not path.exists():
        return {"state": "stopped", "running": False, "exit_code": None}
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BridgeError("INTERNAL_ERROR", "Cannot read managed game state.") from exc
    if result.get("running") and time.time() - result.get("heartbeat", 0) > 15:
        result.update(
            state="unresponsive",
            running=False,
            warning="Supervisor heartbeat expired. Inspect the game before removing a stale game/run.lock.",
        )
    return result


def start(config: Config, scene: str, headless: bool, max_seconds: float) -> dict:
    target = config.resource_path(scene, suffix=".tscn")
    if not target.is_file():
        raise BridgeError("SCENE_NOT_FOUND", f"Scene does not exist: {scene}")
    engine = discover(config.godot)
    base = directory(config)
    try:
        lock = (base / "run.lock").open("x")
        lock.close()
    except FileExistsError as exc:
        raise BridgeError(
            "EDITOR_BUSY",
            "A managed game is running, starting, or left a stale run.lock. Stop it before starting another.",
        ) from exc
    run_id = uuid.uuid4().hex
    run = base / run_id
    run.mkdir()
    arguments = {
        "scene": scene,
        "headless": headless,
        "max_seconds": max_seconds,
        "godot": str(engine.executable),
        "run_id": run_id,
    }
    atomic_json(run / "arguments.json", arguments)
    flags = (
        subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    )
    try:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "godotbridge.process_manager",
                "--project",
                str(config.project),
                "--run-id",
                run_id,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            start_new_session=os.name != "nt",
        )
    except OSError:
        (base / "run.lock").unlink(missing_ok=True)
        raise
    deadline = time.monotonic() + config.timeout
    while time.monotonic() < deadline:
        result = status(config)
        if result.get("run_id") == run_id:
            if result["state"] == "failed":
                raise BridgeError("TRANSACTION_FAILED", "Managed game failed to start.", result)
            return result
        time.sleep(0.1)
    raise BridgeError(
        "TIMEOUT", "Supervisor startup timed out; inspect game status before retrying."
    )


def current_run(config: Config) -> tuple[Path, dict]:
    state = status(config)
    run_id = state.get("run_id", "")
    if (
        not isinstance(run_id, str)
        or len(run_id) != 32
        or any(c not in "0123456789abcdef" for c in run_id)
    ):
        raise BridgeError("UNSUPPORTED_OPERATION", "No managed game session exists.")
    return directory(config) / run_id, state


def stop(config: Config) -> dict:
    run, state = current_run(config)
    if not state.get("running"):
        return state
    (run / "stop.request").touch()
    deadline = time.monotonic() + config.timeout
    while time.monotonic() < deadline:
        state = status(config)
        if not state.get("running"):
            return state
        time.sleep(0.1)
    raise BridgeError(
        "TIMEOUT", "Supervisor has not acknowledged stop; no unrelated process was signalled."
    )


def logs(config: Config) -> dict:
    run, state = current_run(config)
    file = run / "recent.log"
    text = file.read_text(encoding="utf-8", errors="replace") if file.exists() else ""
    return {"process": state, "source": "managed_stdout_stderr", **classify(text)}


def screenshot(client, output: str) -> dict:
    from .artifacts import output_path, png_dimensions

    run, state = current_run(client.config)
    if not state.get("running"):
        raise BridgeError("CAPTURE_UNAVAILABLE", "Start a graphical managed game first.")
    if state.get("headless"):
        raise BridgeError("CAPTURE_UNAVAILABLE", "Headless managed games cannot capture pixels.")
    destination = output_path(client, output)
    if destination.exists():
        raise BridgeError("FILE_ACCESS_DENIED", "Screenshot destination already exists.")
    # One outstanding screenshot per managed session, enforced across CLI processes.
    try:
        lock = (run / "capture.lock").open("x")
        lock.close()
    except FileExistsError as exc:
        raise BridgeError("EDITOR_BUSY", "A runtime capture is already pending.") from exc
    try:
        (run / "capture.json").unlink(missing_ok=True)
        (run / "capture.request").touch()
        deadline = time.monotonic() + client.config.timeout
        while time.monotonic() < deadline:
            response = run / "capture.json"
            if response.exists():
                try:
                    result = json.loads(response.read_text(encoding="utf-8"))
                except ValueError:
                    time.sleep(0.05)
                    continue
                if not result["ok"]:
                    raise BridgeError(**result["error"])
                source = run / "capture.png"
                dimensions = png_dimensions(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as file:
                    file.write(source.read_bytes())
                return {
                    "artifact_path": str(destination),
                    "capture_method": "runtime_viewport",
                    "width": dimensions[0],
                    "height": dimensions[1],
                    "run_id": state["run_id"],
                }
            time.sleep(0.05)
        raise BridgeError("TIMEOUT", "Runtime did not return a screenshot before the deadline.")
    finally:
        (run / "capture.lock").unlink(missing_ok=True)


def supervise(config: Config, run_id: str):
    base = directory(config)
    run = base / run_id
    arguments = json.loads((run / "arguments.json").read_text(encoding="utf-8"))
    state = {
        "run_id": run_id,
        "scene": arguments["scene"],
        "headless": arguments["headless"],
        "running": False,
        "state": "starting",
        "exit_code": None,
        "heartbeat": time.time(),
    }
    process = None
    chunks: deque[bytes] = deque(maxlen=128)
    reader = None
    try:
        command = [
            arguments["godot"],
            "--path",
            str(config.project),
            "--script",
            str(addon_source() / "runtime_runner.gd"),
        ]
        if arguments["headless"]:
            command.append("--headless")
        command.extend(["--", arguments["scene"], f"res://.godot/godotbridge/game/{run_id}"])
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=worker_environment(config),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        def drain():
            while chunk := process.stdout.read1(4096):
                chunks.append(chunk)

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        state.update(running=True, state="running", pid=process.pid)
        started = time.monotonic()
        while process.poll() is None:
            state["heartbeat"] = time.time()
            atomic_json(base / "status.json", state)
            (run / "recent.log").write_text(
                b"".join(list(chunks)).decode("utf-8", errors="replace"), encoding="utf-8"
            )
            if (run / "stop.request").exists() or time.monotonic() - started >= arguments[
                "max_seconds"
            ]:
                state["stop_reason"] = "requested" if (run / "stop.request").exists() else "timeout"
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                break
            time.sleep(0.2)
        process.wait(timeout=10)
        reader.join(timeout=5)
        state.update(
            running=False,
            state="stopped" if state.get("stop_reason") or process.returncode == 0 else "failed",
            exit_code=process.returncode,
            heartbeat=time.time(),
        )
    except Exception as exc:
        state.update(running=False, state="failed", error=str(exc), heartbeat=time.time())
    finally:
        if process and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        if reader:
            reader.join(timeout=5)
        if process and process.stdout:
            process.stdout.close()
        (run / "recent.log").write_text(
            b"".join(list(chunks)).decode("utf-8", errors="replace"), encoding="utf-8"
        )
        atomic_json(base / "status.json", state)
        (base / "run.lock").unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if len(args.run_id) != 32 or any(c not in "0123456789abcdef" for c in args.run_id):
        parser.error("Invalid run identifier")
    supervise(Config.load(args.project), args.run_id)
