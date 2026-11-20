"""Engine-free CLI checks: a stub client records what each command would send to the editor."""

import pytest
from godotbridge.cli import app
from godotbridge.commands import common
from godotbridge.models import OPERATIONS
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def calls(monkeypatch, tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n")
    monkeypatch.setenv("GODOTBRIDGE_PROJECT", str(tmp_path))
    recorded = []

    class StubClient:
        def __init__(self, config):
            pass

        def call(self, operation, **params):
            # Names and ranges must satisfy the shared model, as the real client enforces.
            OPERATIONS[operation].arguments.model_validate(params)
            recorded.append((operation, params))
            return {}

    monkeypatch.setattr(common, "Client", StubClient)
    return recorded


def help_text(*command):
    result = runner.invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())


@pytest.mark.parametrize(
    ("command", "operation"),
    [(("editor", "screenshot"), "viewport.capture"), (("scene", "snapshot"), "scene.snapshot")],
)
def test_capture_commands_pass_the_viewport_index(calls, command, operation):
    assert runner.invoke(app, ["--json", *command]).exit_code == 0
    assert runner.invoke(app, ["--json", *command, "--viewport", "3"]).exit_code == 0
    assert [(op, params["viewport"]) for op, params in calls] == [(operation, 0), (operation, 3)]
    assert "--viewport" in help_text(*command)


@pytest.mark.parametrize("command", [("editor", "screenshot"), ("scene", "snapshot")])
@pytest.mark.parametrize("value", ["-1", "4", "x"])
def test_capture_commands_reject_a_bad_viewport(calls, command, value):
    result = runner.invoke(app, ["--json", *command, "--viewport", value])
    assert result.exit_code == 2 and not calls


def test_create_camera_is_current_by_default_and_can_opt_out(calls):
    for flags in ([], ["--no-current"], ["--current"]):
        assert runner.invoke(app, ["--json", "3d", "create-camera", *flags]).exit_code == 0
    assert [params["current"] for _, params in calls] == [True, False, True]
    assert "--no-current" in help_text("3d", "create-camera")


@pytest.mark.parametrize(
    "command", [("editor", "inspect"), ("node", "select"), ("editor", "focus")]
)
def test_selection_commands_say_they_change_the_editor_selection(command):
    assert "editor selection" in help_text(*command)


def test_focus_help_mentions_the_workspace_switch():
    assert "3D workspace" in help_text("editor", "focus")
