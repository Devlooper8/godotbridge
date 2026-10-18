import asyncio
import sys

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

pytestmark = pytest.mark.engine


def test_mcp_stdio_round_trip(editor, request):
    async def exercise():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "godotbridge.mcp_server", "--project", str(editor.config.project)],
        )
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert "godot_scene_tree" in tools
            assert tools["godot_node_create"].input_schema["required"] == ["name"]
            assert tools["godot_scene_tree"].annotations.read_only_hint
            assert not tools["godot_node_create"].annotations.read_only_hint
            scene = await session.call_tool("godot_scene_create", {"path": "res://scenes/mcp.tscn"})
            assert not scene.is_error, scene
            created = await session.call_tool("godot_node_create", {"name": "ViaMCP"})
            assert created.structured_content["result"]["node_path"] == "ViaMCP"
            tree = await session.call_tool("godot_scene_tree", {})
            assert len(tree.structured_content["result"]["nodes"]) == 2
            invalid = await session.call_tool(
                "godot_node_create", {"name": "Invalid", "type": "OS"}
            )
            assert invalid.is_error
            assert invalid.structured_content["error"]["code"] == "INVALID_ARGUMENT"
            missing = await session.call_tool("godot_node_inspect", {"path": "Missing"})
            assert missing.is_error
            assert missing.structured_content["error"]["code"] == "NODE_NOT_FOUND"
            if request.config.getoption("--graphical"):
                result = await session.call_tool(
                    "godot_viewport_capture", {"output": "mcp.png", "width": 128, "height": 128}
                )
                assert not result.is_error, result
                assert any(
                    item.type == "image" and item.mime_type == "image/png"
                    for item in result.content
                )

    asyncio.run(exercise())
