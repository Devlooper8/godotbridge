import json
import subprocess
import sys
from pathlib import Path

import pytest
from godotbridge.config import Config
from godotbridge.errors import BridgeError
from godotbridge.models import schemas


@pytest.fixture
def project(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n")
    return Config.load(tmp_path)


@pytest.mark.parametrize(
    "path",
    [
        "res://../escape.tscn",
        "res://.git/config",
        "C:/outside.tscn",
        "res://C:/escape.tscn",
        "res://\\escape.tscn",
    ],
)
def test_reject_unsafe_resource_paths(project, path):
    with pytest.raises(BridgeError) as error:
        project.resource_path(path)
    assert error.value.code == "FILE_ACCESS_DENIED"


def test_symlink_escape(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "project"
    root.mkdir()
    (root / "project.godot").write_text("config_version=5\n")
    config = Config.load(root)
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or privilege")
    with pytest.raises(BridgeError):
        config.resource_path("res://linked/escape.tscn")


def test_generated_schema_matches_registry():
    file = Path(__file__).resolve().parents[2] / "addons/godot_bridge/schemas.json"
    assert json.loads(file.read_text(encoding="utf-8")) == schemas()


def test_cli_help_and_json_validation():
    result = subprocess.run(
        [sys.executable, "-m", "godotbridge.cli", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "godot" in result.stdout.lower()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "godotbridge.cli",
            "--json",
            "node",
            "position",
            "A",
            "bad",
            "2",
            "3",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_ARGUMENT"


def test_config_timeout_validation(project):
    with pytest.raises(BridgeError):
        Config.load(project.project, timeout=float("nan"))


def test_timeout_precedence_argument_then_toml_then_default(project):
    assert Config.load(project.project).timeout == 15.0
    assert Config.load(project.project, default_timeout=30).timeout == 30.0
    (project.project / "godotbridge.toml").write_text("timeout = 20\n")
    assert Config.load(project.project).timeout == 20
    assert Config.load(project.project, default_timeout=30).timeout == 20
    assert Config.load(project.project, timeout=5, default_timeout=30).timeout == 5


@pytest.mark.parametrize("value", ["0", "-1", "601", '"5"'])
def test_timeout_range_is_enforced_in_toml(project, value):
    (project.project / "godotbridge.toml").write_text(f"timeout = {value}\n")
    with pytest.raises(BridgeError) as error:
        Config.load(project.project, default_timeout=30)
    assert error.value.code == "INVALID_ARGUMENT" and "Timeout" in error.value.message


@pytest.mark.parametrize("value", [0, -1, 600.1])
def test_timeout_range_is_enforced_in_arguments(project, value):
    with pytest.raises(BridgeError):
        Config.load(project.project, timeout=value)


def test_connect_wait_defaults_to_no_wait(project):
    assert project.connect_wait == 0.0


def test_connect_wait_comes_from_toml_and_arguments_win(project):
    (project.project / "godotbridge.toml").write_text("connect_wait = 7\n")
    loaded = Config.load(project.project)
    assert loaded.connect_wait == 7.0 and isinstance(loaded.connect_wait, float)
    assert Config.load(project.project, connect_wait=2.5).connect_wait == 2.5
    assert Config.load(project.project, connect_wait=0).connect_wait == 0.0


@pytest.mark.parametrize("value", [-0.1, 600.1, float("nan"), "5"])
def test_connect_wait_range_is_enforced(project, value):
    with pytest.raises(BridgeError) as error:
        Config.load(project.project, connect_wait=value)
    assert error.value.code == "INVALID_ARGUMENT" and "connect_wait" in error.value.message


def test_connect_wait_range_is_enforced_in_toml(project):
    (project.project / "godotbridge.toml").write_text("connect_wait = 601\n")
    with pytest.raises(BridgeError):
        Config.load(project.project)


def test_connect_wait_bounds_are_valid(project):
    assert Config.load(project.project, connect_wait=600).connect_wait == 600.0


def test_cli_rejects_an_out_of_range_connect_wait(project):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "godotbridge.cli",
            "--connect-wait",
            "601",
            "--project",
            str(project.project),
            "--json",
            "editor",
            "status",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_ARGUMENT"
