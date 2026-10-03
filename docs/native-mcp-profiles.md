# Native MCP profiles

The compatibility transport remains `/mcp/stream` with all 118 existing tool
contracts. Two additional transports reuse the same registered domain wrappers:

- `/mcp/agent/stream`: 30 canonical work, project, card, wiki, people, notification
  and media entry points.
- `/mcp/raw/stream`: the remaining primitive and compatibility actions.

`create_native_domain_provider` adapts the existing registry. Compatibility,
Agent/Core and Raw providers compose that adapter with FastMCP's native
`Visibility` transform. They do not copy domain commands, rename tools, infer
authorization from a profile, or change existing group grants.

Both new transports retain `McpAuthMiddleware`, `ToolGroupMiddleware`, current
board/card role validation, transport host checks, strict arguments and masked
errors. Profile visibility and authorization are independent restrictions.
The combined Agent/Core and Raw schemas equal the compatibility catalog.

This delivery separates existing canonical entry points. It does not yet supply
all planned action facades, atomic Work Plan handling, Raw search/lazy discovery,
OAuth profile access, deprecation telemetry or representative installed-client
parity. Do not switch a connector automatically or remove its legacy tools.
Native OAuth remains a separate opt-in delivery.
