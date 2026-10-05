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

## Docker deployment

The standard environment generator forwards `MCP_OAUTH_*` and
`MCP_EMPLOYEE_GROUP_IDS` from the operator's `.env` into the API environment.
OAuth stays disabled by default. Configure a dedicated IdP client with the
callback `<MCP_OAUTH_BASE_URL>/auth/callback`; do not silently reuse a web-login
client whose redirect URIs or scopes may differ. No issuer, tenant, company,
client credentials or employee groups are built into the distribution.

```dotenv
MCP_OAUTH_ENABLED=true
MCP_OAUTH_BASE_URL=https://board.example/api/mcp/oauth
MCP_OAUTH_DISCOVERY_URL=https://id.example/.well-known/openid-configuration
MCP_OAUTH_CLIENT_ID=langboard-mcp
MCP_OAUTH_CLIENT_SECRET=<dedicated-client-secret>
MCP_OAUTH_SIGNING_KEY=<stable-random-key-at-least-32-characters>
MCP_OAUTH_SCOPES="openid profile mcp:access"
MCP_OAUTH_PROMPT=select_account
```

API containers use `FASTMCP_HOME=/app/.fastmcp` on the `mcp-oauth-state` named
volume. FastMCP owns encrypted storage inside that directory. Preserve both
the volume and signing key across recreate/upgrade/rollback; changing the key
changes the encrypted storage namespace. Never use `docker compose down -v`
when preserving registrations. Existing installations must migrate any prior
FastMCP storage before adopting the volume; this change does not copy or reset
existing credential files. Multiple API workers share the directory, but
cross-host replicas need an explicitly shared backend and concurrency checks.

Run the existing environment generator, then recreate only the affected API
service with the deployment's normal Compose files. A restart does not refresh
container environment or volume mounts. Verify discovery, browser consent,
authenticated reads/writes and restart/refresh afterward. Do not infer those
gates from container health.

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
