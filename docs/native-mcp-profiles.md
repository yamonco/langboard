# Native MCP profiles

The compatibility transport remains `/mcp/stream` with all 118 existing tool
contracts. Two additional transports reuse the same registered domain wrappers:

- `/mcp/agent/stream`: 30 canonical work, project, card, wiki, people, notification
  and media entry points.
- `/mcp/raw/stream`: `search_raw_tools` and `call_raw_tool` discover and invoke
  the remaining primitive and compatibility actions on demand. FastMCP's
  `RegexSearchTransform` returns at most five full tool schemas per search.

`create_native_domain_provider` adapts the existing registry. Compatibility,
Agent/Core and Raw providers compose that adapter with FastMCP's native
`Visibility` transform. They do not copy domain commands, rename tools, infer
authorization from a profile, or change existing group grants.

Both new transports retain `McpAuthMiddleware`, `ToolGroupMiddleware`, current
board/card role validation, transport host checks, strict arguments and masked
errors. Profile visibility and authorization are independent restrictions.
The underlying Agent/Core and Raw schemas equal the compatibility catalog.
Raw discovery exposes only the two synthetic tools initially. Those tools
require an active validated ToolGroup; search results are filtered by its
current grants. The proxy rechecks the current discoverable catalog and then
invokes the target through normal middleware and domain authorization. Revoked
grants are not cached between search and execution. Core tools and recursive
synthetic calls cannot be invoked through the Raw proxy.

Modern profiles declare standard read-only, destructive, idempotent and
open-world hints. Reviewed query entry points are explicitly listed as reads;
names are not classified by prefixes. Unreviewed commands and the generic Raw
call proxy remain potentially destructive and non-idempotent. Open-world is
kept true because attachments and user-authored content may cross trust
boundaries. Compatibility retains its original annotations. These hints never
replace authorization, approval or mutation outcome receipts.

This delivery separates existing canonical entry points. It does not yet supply
all planned action facades, atomic Work Plan handling,
OAuth profile access, deprecation telemetry or representative installed-client
parity. Do not switch a connector automatically or remove its legacy tools.
Native OAuth remains a separate opt-in delivery.
