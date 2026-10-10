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

## Board Apps declarations

Board Settings Apps discovery uses the immutable host-owned `APP_MANIFESTS`
registry in `langboard_shared.domain.services.AppManifest`. GitHub, GlitchTip
and Dokploy declare resource types, supported capability names, native read and
configuration permission actions, workflow requirements and the v1 signal
provenance fields. The compact signal declaration describes required envelope
fields; it is not a payload validator or an installed event consumer.

Declarations are catalog metadata. They do not register Python handlers, grant
capabilities, enable transitions, create connections or resolve credentials.
The catalog combines these declarations with current board-owned bindings after
its existing primary database authority check. Declared capabilities and saved
`granted_capabilities` remain separate. Unknown App keys cannot mutate bindings.
Returned lists are copies; clients cannot edit the registry through responses.

Connection onboarding remains unavailable until each provider's authenticated
installation and resource access verification are implemented. Dokploy currently
declares read capabilities only; deployment/redeployment writes require a later
explicit host permission contract. SDK transport and native command composition
remain the existing extension boundary.
