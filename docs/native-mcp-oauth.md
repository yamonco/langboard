# Native MCP OAuth

The native OAuth transport is optional and separate from the legacy API-key
transport. It uses FastMCP OIDCProxy, native encrypted persistent storage and
AuthMiddleware/require_scopes. No ToolGroup UID is required for OAuth clients.

The operator configures an OIDC discovery URL, dedicated client credentials,
public mount URL, stable signing key and supported scopes. The provider must
allow the application's `mcp:access` scope; the scope string is an application
contract, not a standardized MCP permission name. `openid`/`profile` describe
identity claims, not permission to write a board.

Only a verified issuer/subject with an explicit existing identity link resolves
to a Langboard user. Inactive and deleted users are denied on each request.
OAuth scopes control access to the MCP surface. Existing domain role checks
continue to control board/card operations. SCIM may provision identity and
authorization according to operator policy; it is not required for local users
or external collaborators, and does not inherently classify a person as an
employee.

ToolGroups remain a legacy compatibility policy. FastMCP does not automatically
convert database ToolGroups into OAuth roles or scopes. Their migration requires
an explicit, reviewed mapping and authorization parity evidence. FastAPI's
SecurityScopes can enforce the same scope contract for REST endpoints; it does
not replace resource authorization or create organizational policy.

FastMCP's default OAuthProxy storage uses encrypted persistent files under
FASTMCP_HOME. Operators must preserve the volume and stable signing key.
Multi-instance deployments may inject an AsyncKeyValue backend through
`create_oauth_provider(client_storage=...)`; no company-specific backend is
required. Shared storage and refresh concurrency still need validation.

Implementation acceptance is not yet proven by unit tests. Mounted metadata and
callbacks, real browser consent, restart/refresh persistence and independent
authenticated client read/write must be verified before enabling this transport
in a deployment.

## Employee classification

Set `MCP_EMPLOYEE_GROUP_IDS` to comma-separated SCIM **external group IDs** and
set `SCIM_ISSUER` to the provisioning authority. There are no built-in company,
email-domain or group-name assumptions. An empty policy returns `unknown`.
SCIM provisioning and OAuth authentication alone do not prove employment.

`get_employee_status` classifies only the current linked user from current
primary-database identity and group membership. Inactive/deleted accounts,
foreign issuers and removed memberships do not qualify. Classification grants
no permissions. `list_employees` currently requires a Langboard administrator;
regular authenticated employees cannot enumerate the directory. The query
filters issuer, configured groups and active users before pagination (1–50
records per page), deduplicates overlapping memberships, and exposes public
UID/name fields only. Non-admin directory access needs an explicit future
permission policy; it is not inferred from organization membership.
