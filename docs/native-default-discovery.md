# Default native MCP discovery

Native OAuth now exposes Agent/Core tools plus `search_raw_tools` and
`call_raw_tool` on its default connection. No per-user tool-group assembly is
needed. Other native commands remain available through bounded search or direct
calls; discovery reduction does not grant or remove domain permissions.

The provider uses FastMCP's native RegexSearchTransform with core tools pinned.
Search returns at most five command definitions and excludes pinned duplicates.
The proxy uses the normal command pipeline, preserving input validation, native
identity, ownership and project/card ACL checks. Tool annotations describe search
as a query and the generic proxy conservatively as a mutation.

Legacy transport and the existing explicit agent/raw transports are unchanged.
Resources and workflow prompts remain available. This is a catalog byte reduction,
not proof of a task token/call reduction or the eight-facade roadmap completion.
External OAuth login, consent, refresh and persistent storage remain separate gates.

Official implementation reference:
https://gofastmcp.com/servers/transforms/tool-search
