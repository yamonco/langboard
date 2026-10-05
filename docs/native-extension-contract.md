# Native extension composition

Extensions select existing native command names explicitly. They do not register
replacement business handlers, a principal, role policy or repository. An empty,
duplicate or unknown selection is rejected before a provider is populated.

```python
from langboard.mcp_integration.Extensions import create_native_extension_provider
from langboard.mcp_integration.Server import McpServer

provider = create_native_extension_provider(
    ["get_card_bundle", "preview_card_work_plan"], McpServer._wrap_tool
)
```

This is a host composition API, not a client request or auto-loader. Native
modules must be loaded first. The host owns the selected names and wrapper.
Mount the provider on a separate FastMCP catalog with the same authenticated
middleware as its transport. On legacy/API-key transports preserve tool-group
middleware too; selection never grants access to a command. Do not add a second
copy of selected names to a provider/server that already exposes them.

The provider uses the same native tool builder as the core: schema, output
projection, annotations, bounds and application metadata remain identical.
The wrapper reads the authenticated actor, checks current role policy and owns
per-call service/repository cleanup with an ExitStack. It closes resources on
successful results and handler errors. Providers do not receive caller-owned
services or credentials and never close the host's authenticated client session.

Core startup does not discover entry points, import external packages or require
an extension installation. This contract composes trusted native commands only.
It does not execute arbitrary extension Python, claim an in-process sandbox, or
provide a dynamic package installation/uninstallation lifecycle. Custom business
integrations should use the standalone transport SDK against native commands;
untrusted code requires a separate process and deployment boundary.
