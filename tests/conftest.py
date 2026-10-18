import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from godotbridge.client import Client
from godotbridge.config import Config
from godotbridge.discovery import discover
from godotbridge.errors import BridgeError
from godotbridge.install import install


def pytest_addoption(parser):
    parser.addoption(
        "--engine", action="store_true", help="Run actual Godot editor integration tests"
    )
    parser.addoption(
        "--graphical", action="store_true", help="Run editor with real graphics and capture tests"
    )


@pytest.fixture(scope="session")
def editor(request, tmp_path_factory):
    if not request.config.getoption("--engine"):
        pytest.skip("Pass --engine to run actual Godot integration tests")
    project = tmp_path_factory.mktemp("godot-project")
    source = Path(__file__).resolve().parents[1] / "examples/3d_demo"
    shutil.copytree(
        source,
        project,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".godot", "addons", "snapshots"),
    )
    config = Config.load(project, timeout=10)
    install(config)
    engine = discover()
    log_path = project / "editor.log"
    env = os.environ.copy()
    for variable in (
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        directory = project / "test-user" / variable
        directory.mkdir(parents=True, exist_ok=True)
        env[variable] = str(directory)
    args = [str(engine.executable), "--path", str(project), "--editor", "res://scenes/main.tscn"]
    if not request.config.getoption("--graphical"):
        args.insert(1, "--headless")
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        args,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    client = Client(config)
    deadline = time.monotonic() + 90
    try:
        while time.monotonic() < deadline:
            if "SCRIPT ERROR:" in log_path.read_text(encoding="utf-8", errors="replace"):
                pytest.fail(
                    f"Plugin script error: {log_path.read_text(encoding='utf-8', errors='replace')}"
                )
            if process.poll() is not None:
                pytest.fail(
                    f"Editor exited {process.returncode}: {log_path.read_text(encoding='utf-8')}"
                )
            try:
                status = client.call("editor.status")
                if status.get("scene_path"):
                    break
            except BridgeError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail(f"Editor did not connect: {log_path.read_text(encoding='utf-8')}")
        yield client
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        log.close()
        artifact_dir = Path(__file__).resolve().parents[1] / ".artifacts"
        artifact_dir.mkdir(exist_ok=True)
        shutil.copy2(
            log_path,
            artifact_dir
            / (
                "editor-graphical.log"
                if request.config.getoption("--graphical")
                else "editor-headless.log"
            ),
        )
