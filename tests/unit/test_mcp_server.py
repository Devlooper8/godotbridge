"""The MCP server starts without a project and builds its client on the first call that can."""

import asyncio
import sys

import pytest
from godotbridge import mcp_server
from godotbridge.config import Config
from godotbridge.errors import BridgeError
from godotbridge.mcp_server import LazyClient, create_server
from mcp import Client


def test_client_is_built_lazily_and_cached(tmp_path):
    root = tmp_path / "game"

    async def exercise():
        lazy = LazyClient(lambda: Config.load(root))
        async with Client(create_server(lazy)) as client:
            assert "EDITOR_DISCONNECTED" in client.instructions
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert "godot_editor_status" in tools

            before = await client.call_tool("godot_editor_status", {})
            assert before.is_error
            assert before.structured_content["error"]["code"] == "PROJECT_NOT_FOUND"

            root.mkdir()
            (root / "project.godot").write_text("config_version=5\n")
            after = await client.call_tool("godot_editor_status", {})
            assert after.is_error
            assert after.structured_content["error"]["code"] == "EDITOR_DISCONNECTED"

            built = lazy.get()
            await client.call_tool("godot_editor_status", {})
            assert lazy.get() is built

    asyncio.run(exercise())


@pytest.fixture
def game(tmp_path):
    (tmp_path / "project.godot").write_text("config_version=5\n")
    return tmp_path


def server_config(monkeypatch, game, *flags):
    """The Config the server would load per call, built through main()'s real argument handling."""
    loaders = []

    async def capture(load_config):
        loaders.append(load_config)

    monkeypatch.setattr(mcp_server, "serve", capture)
    monkeypatch.setattr(sys, "argv", ["godotbridge-mcp", "--project", str(game), *flags])
    mcp_server.main()
    return loaders[0]()


def test_timeout_defaults_to_30_without_flag_or_toml(monkeypatch, game):
    assert server_config(monkeypatch, game).timeout == 30.0


def test_timeout_comes_from_toml(monkeypatch, game):
    (game / "godotbridge.toml").write_text("timeout = 20\n")
    assert server_config(monkeypatch, game).timeout == 20


def test_timeout_flag_wins_over_toml(monkeypatch, game):
    (game / "godotbridge.toml").write_text("timeout = 20\n")
    assert server_config(monkeypatch, game, "--timeout", "5").timeout == 5


def test_toml_timeout_is_read_once_when_the_client_is_first_built(game):
    toml = game / "godotbridge.toml"
    toml.write_text("timeout = 20\n")
    lazy = LazyClient(lambda: Config.load(game, default_timeout=30))
    assert lazy.get().config.timeout == 20
    toml.write_text("timeout = 5\n")
    assert lazy.get().config.timeout == 20


def test_toml_timeout_range_is_enforced_when_the_project_loads(monkeypatch, game):
    (game / "godotbridge.toml").write_text("timeout = 601\n")
    with pytest.raises(BridgeError) as error:
        server_config(monkeypatch, game)
    assert error.value.code == "INVALID_ARGUMENT"


def test_timeout_flag_range_is_enforced_at_startup(monkeypatch, game):
    with pytest.raises(SystemExit) as error:
        server_config(monkeypatch, game, "--timeout", "601")
    assert error.value.code == 2
