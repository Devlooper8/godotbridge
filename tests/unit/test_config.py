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
