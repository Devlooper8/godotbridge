"""Engine-free checks of game.run scene selection in managed mode."""

import pytest
from godotbridge import game, process_manager
from godotbridge.errors import BridgeError

MAIN = "res://scenes/main.tscn"


class StubClient:
    config = None

    def __init__(self, current):
        self.current = current

    def call(self, operation, **params):
        if operation == "scene.current":
            return {"scene_path": self.current, "root": "x"}
        assert operation == "project.info"
        return {"main_scene": MAIN}


@pytest.fixture
def started(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        process_manager, "start", lambda config, scene, *rest: recorded.append(scene) or {}
    )
    return recorded


def run(open_scene, **overrides):
    arguments = {"mode": "managed", "scene": None, "current": True, "headless": True}
    arguments |= {"max_seconds": 5} | overrides
    return game.dispatch(StubClient(open_scene), "game.run", arguments)


def test_unsaved_current_scene_is_rejected_not_replaced_by_the_main_scene(started):
    with pytest.raises(BridgeError) as caught:
        run("")
    assert caught.value.code == "SCENE_NOT_FOUND"
    assert "save" in caught.value.message.lower()
    assert started == []


def test_saved_current_scene_is_started(started):
    run("res://scenes/a.tscn")
    assert started == ["res://scenes/a.tscn"]


def test_main_scene_is_the_fallback_only_without_current(started):
    run("", current=False)
    assert started == [MAIN]
