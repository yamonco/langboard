# MCP tool group default for OIDC users

`MCP_OIDC_DEFAULT_TOOL_GROUP_UID` optionally selects an existing Langboard MCP tool group when a verified OIDC user omits `X-MCP-Tool-Group-UID`. Its default is empty, which preserves the requirement to supply the header. This setting applies to the native MCP transport and `/mcp/tools/{tool_name}` REST execution route.

Configure the value on the Langboard API server. Official ContextForge can then forward the employee's OIDC access token through its native OAuth flow without injecting a company tool-group field or header. OIDC authentication still requires the configured issuer and API audience and an existing exact account link.

An explicit header, including an empty header, always takes precedence. The selected group must exist and be active; personal groups must belong to the authenticated employee. Existing role checks and each group's allowed-tool list remain authoritative for discovery and execution. A default group does not grant additional permissions.

API keys, bots, native sessions, and unauthenticated requests do not inherit this OIDC default. Configure a group appropriate for the intended employee population. A default pointing to another employee's personal group fails the owner check.
