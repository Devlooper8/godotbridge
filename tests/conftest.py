import contextlib
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


def prepare_project(directory: Path) -> Config:
    """Copy the demo project into `directory` and install the plugin from this checkout."""
    source = Path(__file__).resolve().parents[1] / "examples/3d_demo"
    shutil.copytree(
        source,
        directory,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".godot", "addons", "snapshots"),
    )
    # CI runners have no sound device; real audio drivers log ERR_CANT_OPEN before falling
    # back, which the managed-game tests would report as a runtime error.
    (directory / "override.cfg").write_text('[audio]\n\ndriver/driver="Dummy"\n', encoding="utf-8")
    config = Config.load(directory, timeout=10)
    install(config)
    return config


@contextlib.contextmanager
def running_editor(config: Config, graphical: bool, name: str = "editor"):
    """Run an editor on the project until the block ends; yields a Client once its scene is open.

    `name` keeps the log and the isolated user directories of several editors on one project apart.
    """
    project = config.project
    log_path = project / f"{name}.log"
    env = os.environ.copy()
    for variable in (
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ):
        directory = project / "test-user" / name / variable
        directory.mkdir(parents=True, exist_ok=True)
        env[variable] = str(directory)
    args = [
        str(discover().executable),
        "--path",
        str(project),
        "--editor",
        "res://scenes/main.tscn",
    ]
    if not graphical:
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


@pytest.fixture(scope="session")
def editor(request, tmp_path_factory):
    if not request.config.getoption("--engine"):
        pytest.skip("Pass --engine to run actual Godot integration tests")
    graphical = request.config.getoption("--graphical")
    config = prepare_project(tmp_path_factory.mktemp("godot-project"))
    try:
        with running_editor(config, graphical) as client:
            yield client
    finally:
        log_path = config.project / "editor.log"
        if log_path.exists():
            artifact_dir = Path(__file__).resolve().parents[1] / ".artifacts"
            artifact_dir.mkdir(exist_ok=True)
            shutil.copy2(
                log_path,
                artifact_dir / ("editor-graphical.log" if graphical else "editor-headless.log"),
            )


@pytest.fixture
def extra_editor(request, tmp_path_factory):
    """Factory for one more headless editor on its own project copy, next to the session editor.

    `extra_editor(before_launch)` is a context manager; `before_launch(config)` may seed files first.
    Pass `config` to start another editor on an existing project instead of a fresh copy.
    """
    if not request.config.getoption("--engine"):
        pytest.skip("Pass --engine to run actual Godot integration tests")

    @contextlib.contextmanager
    def start(before_launch=None, *, config=None, name="extra"):
        if config is None:
            config = prepare_project(tmp_path_factory.mktemp("godot-extra"))
        if before_launch:
            before_launch(config)
        with running_editor(config, graphical=False, name=name) as client:
            yield client

    return start
