"""Official MCP Python SDK 2.x stdio server over the common operation registry."""

import argparse
import asyncio
import base64
import json
import logging
from pathlib import Path

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import __version__
from .client import Client
from .config import Config
from .errors import BridgeError
from .models import OPERATIONS

TOOL_OPERATIONS = {
    op.tool or "godot_" + name.replace(".", "_"): name for name, op in OPERATIONS.items()
}


def create_server(client: Client) -> Server:
    async def list_tools(_context, _params):
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool,
                    description=OPERATIONS[name].description,
                    input_schema=OPERATIONS[name].arguments.model_json_schema(),
                    annotations=types.ToolAnnotations(
                        read_only_hint=not OPERATIONS[name].mutating,
                        destructive_hint=OPERATIONS[name].mutating,
                        open_world_hint=False,
                    ),
                )
                for tool, name in TOOL_OPERATIONS.items()
            ]
        )

    async def call_tool(_context, params):
        try:
            if params.name not in TOOL_OPERATIONS:
                raise BridgeError("UNSUPPORTED_OPERATION", f"Unknown tool: {params.name}")
            operation = TOOL_OPERATIONS[params.name]
            result = await asyncio.to_thread(client.call, operation, **(params.arguments or {}))
            structured = {"ok": True, "result": result}
            content: list = [
                types.TextContent(type="text", text=json.dumps(structured, ensure_ascii=False))
            ]
            image_path = (
                result.get("image_path")
                if operation == "scene.snapshot"
                else result.get("artifact_path")
                if operation in {"viewport.capture", "game.screenshot"}
                else None
            )
            if image_path:
                # These paths have already passed the workspace and PNG checks in artifacts.py.
                content.append(
                    types.ImageContent(
                        type="image",
                        mime_type="image/png",
                        data=base64.b64encode(Path(image_path).read_bytes()).decode("ascii"),
                    )
                )
            return types.CallToolResult(
                content=content, structured_content=structured, is_error=False
            )
        except BridgeError as exc:
            error = {"ok": False, "error": exc.as_dict()}
        except Exception:
            logging.exception("MCP operation failed")
            error = {
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Unexpected server failure; inspect stderr diagnostics.",
                },
            }
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(error))],
            structured_content=error,
            is_error=True,
        )

    return Server(
        "godotbridge",
        version=__version__,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        instructions="Mutations affect the live Godot editor. Inspect state before retrying a timed-out mutation. All artifact paths are project-confined.",
    )


async def serve(config: Config):
    server = create_server(Client(config))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="GodotBridge MCP stdio server (official SDK 2.x)")
    parser.add_argument("--project", default=None)
    parser.add_argument("--godot", default=None)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    try:
        asyncio.run(serve(Config.load(args.project, args.godot, args.timeout)))
    except BridgeError as exc:
        parser.exit(exc.exit_code, f"{exc.code}: {exc.message}\n")


if __name__ == "__main__":
    main()
