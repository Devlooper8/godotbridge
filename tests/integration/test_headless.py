import shutil
from pathlib import Path

import pytest
from godotbridge.client import Client
from godotbridge.config import Config
from godotbridge.errors import BridgeError
from godotbridge.install import install

pytestmark = pytest.mark.engine


def test_project_validation_and_script_checks(editor):
    result = editor.call("project.validate")
    assert result["validation"]["valid"]
    scripts = editor.config.project / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "valid.gd").write_text("extends Node3D\n", encoding="utf-8")
    assert editor.call("project.check_script", path="res://scripts/valid.gd")["exit_code"] == 0
    (scripts / "bad.gd").write_text("extends Node3D\nthis is invalid syntax\n", encoding="utf-8")
    try:
        with pytest.raises(BridgeError) as caught:
            editor.call("project.check_script", path="res://scripts/bad.gd")
        assert caught.value.code == "TRANSACTION_FAILED"
        with pytest.raises(BridgeError) as caught:
            editor.call("project.validate")
        assert caught.value.code == "TRANSACTION_FAILED"
    finally:
        (scripts / "bad.gd").unlink()


def test_project_validation_skips_gdignore_directories(editor):
    ignored = editor.config.project / "ignored-by-godot"
    ignored.mkdir()
    try:
        (ignored / ".gdignore").write_text("", encoding="utf-8")
        (ignored / "broken.gd").write_text(
            "extends Node3D\nthis is invalid syntax\n", encoding="utf-8"
        )
        assert editor.call("project.validate")["validation"]["valid"]
    finally:
        shutil.rmtree(ignored)


def test_import_refuses_live_editor(editor):
    with pytest.raises(BridgeError) as caught:
        editor.call("project.import")
    assert caught.value.code == "EDITOR_BUSY"


def test_offline_import_and_demo_validation(editor, tmp_path):
    source = Path(__file__).resolve().parents[2] / "examples/3d_demo"
    shutil.copytree(
        source,
        tmp_path,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".godot", "addons", "snapshots"),
    )
    config = Config.load(tmp_path, timeout=60)
    install(config)
    client = Client(config)
    assert client.call("project.import")["exit_code"] == 0
    info = client.call("project.info")
    assert info["connected"] is False
    assert info["main_scene"] == "res://scenes/main.tscn"
    assert client.call("project.validate")["validation"]["valid"]
