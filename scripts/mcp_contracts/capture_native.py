"""Capture non-secret native MCP contracts from the deployed Python environment.

Run inside the API container. No business tools, tokens, or OAuth state are read.
ToolGroup rows are queried through the existing readonly repository boundary.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import version


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


async def capture(*, include_groups=True):
    from langboard.Loader import ModuleLoader
    from langboard.mcp_integration import McpServer, McpTool
    from langboard_shared.core.db import DbSession, SqlBuilder
    from langboard_shared.domain.models import McpToolGroup

    ModuleLoader.load("mcp_tools", "Mcp", log=False)
    _, server = McpServer.get_http_app()
    tools = []
    for tool in await server.list_tools(run_middleware=False):
        annotations = tool.annotations
        tools.append(
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
                "output_schema": tool.output_schema,
                "annotations": annotations.model_dump(mode="json") if annotations else None,
            }
        )
    tools.sort(key=lambda tool: tool["name"])
    registered = McpTool.get_tools()
    groups = []
    if include_groups:
        with DbSession.use(readonly=True) as db:
            for group in db.exec(SqlBuilder.select.table(McpToolGroup)).all():
                groups.append(
                    {
                        "key": hashlib.sha256(str(group.id).encode()).hexdigest(),
                        "owner": hashlib.sha256(str(group.user_id).encode()).hexdigest()
                        if group.user_id is not None
                        else None,
                        "scope": "global" if group.user_id is None else "user",
                        "active": group.activated_at is not None,
                        "tools": sorted(set(group.tools)),
                    }
                )
    groups.sort(key=canonical_bytes)
    contract = {
        "tools": tools,
        "tool_groups": groups,
        "registered_runtime_mismatches": sorted(set(registered) ^ {tool["name"] for tool in tools}),
    }
    return {
        "format_version": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "fastmcp_version": version("fastmcp"),
        "contract_sha256": hashlib.sha256(canonical_bytes(contract)).hexdigest(),
        "scope": "Deployed source registration and readonly ToolGroup rows; not authenticated discovery or tool invocation.",
        "contract": contract,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-only", action="store_true", help="Skip deployed ToolGroup DB read for isolated CI.")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(capture(include_groups=not args.catalog_only)), ensure_ascii=False, sort_keys=True, indent=2
        )
    )
