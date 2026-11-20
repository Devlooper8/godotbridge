"""Engine-free checks of the managed-game state files under Windows sharing violations."""

import json
import sys
from pathlib import Path

import pytest
from godotbridge import process_manager
from godotbridge.config import Config


@pytest.fixture
def config(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n")
    return Config.load(tmp_path)


def deny(monkeypatch, owner, name, times):
    """Make the first `times` calls of `owner.name` raise PermissionError, like a file a reader has open."""
    original = getattr(owner, name)
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) <= times:
            raise PermissionError(5, "Access is denied")
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, flaky)
    return calls


def test_atomic_json_retries_a_replace_denied_by_a_concurrent_reader(tmp_path, monkeypatch):
    calls = deny(monkeypatch, Path, "replace", 3)
    target = tmp_path / "status.json"
    process_manager.atomic_json(target, {"state": "stopped"})
    assert json.loads(target.read_text()) == {"state": "stopped"}
    assert len(calls) == 4


def test_status_retries_a_read_denied_during_a_replace(config, monkeypatch):
    process_manager.atomic_json(process_manager.directory(config) / "status.json", {"state": "x"})
    deny(monkeypatch, Path, "read_text", 2)
    assert process_manager.status(config)["state"] == "x"


def test_supervisor_releases_the_run_lock_when_the_final_state_cannot_be_written(
    config, monkeypatch
):
    base = process_manager.directory(config)
    (base / "run.lock").touch()
    run_id = "0" * 32
    (base / run_id).mkdir()
    # Python stands in for the engine: it rejects the engine's flags and exits at once.
    arguments = {
        "scene": "res://scenes/main.tscn",
        "headless": True,
        "max_seconds": 30,
        "godot": sys.executable,
    }
    (base / run_id / "arguments.json").write_text(json.dumps(arguments))
    real = process_manager.atomic_json

    def refuse_final(path, value):
        if value["state"] in ("stopped", "failed"):
            raise PermissionError(5, "Access is denied")
        real(path, value)

    monkeypatch.setattr(process_manager, "atomic_json", refuse_final)
    with pytest.raises(PermissionError):
        process_manager.supervise(config, run_id)
    assert not (base / "run.lock").exists()
