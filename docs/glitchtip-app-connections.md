# Native GlitchTip connections

The native authenticated board API supports GlitchTip SaaS and self-hosted
HTTPS instances. Operators explicitly approve exact base URLs in
`APP_CONNECTION_ALLOWED_BASE_URLS` (comma separated). There are no company
endpoint defaults. This is a trusted outbound-network permission: approve only
instances the host is allowed to contact. Redirects and environment proxies are
disabled. Each request has a 15-second timeout and a 256 KiB decoded response
limit. It does not implement DNS pinning for operator-approved hosts.

## Credential and resource ownership

First create a personal or appropriately scoped native Secret Reference through
the authenticated browser secret-input flow. Store a GlitchTip **API token**,
not a project's ingest DSN. Tokens are resolved only inside the host and audited;
the connection stores only the canonical `secret://ref/{uid}` reference. Request
schemas never accept raw tokens or DSNs. A URL-shaped DSN is rejected before
external I/O. API scopes should be restricted to the required metadata reads.

Authenticated routes under
`/board/{board_uid}/settings/apps/glitchtip/connections`:

- `POST`: `{instance_url, credential_reference}` verifies organization metadata
  read access and persists an owner-scoped connection.
- `GET`: lists the current user's connected instances, 25 per page with `after`.
- `GET /{connection_uid}/resources`: lists organizations; `organization` selects
  that organization's projects. `cursor` retrieves the next page, maximum 25.
  Only resource ID, slug and name are returned.
- `POST /{connection_uid}/projects`: `{organization, project_slug,
  expected_revision}` re-reads the selected project from GlitchTip and binds it
  to the current board. A listing is not authorization evidence for a write.
- `POST /{connection_uid}/disconnect`: `{expected_revision}` disconnects the
  reusable connection and invalidates external access for its bindings. Existing
  selections, cards and board workflow configuration remain intact. The shared
  Secret Reference is not revoked implicitly.

Every operation uses current primary board Update authority. Connections are
owner scoped. External response handling rechecks board authority, connection
revision (including instance URL) and current secret revision/state. Persistence
locks current authority, credential reference and connection rows. First board
binding creation uses the existing board row lock. Bindings stay disabled;
resource selection does not grant signal capabilities or enable transitions.
Provider pagination links supply only a validated cursor; their URLs are never
followed. Redirects, denied/deleted resources and in-flight revocation cannot
produce a new binding.

## Official diagnostic surface and remaining work

GlitchTip's official Streamable HTTP MCP endpoint is `{instance_url}/mcp`,
supporting OAuth dynamic client registration or API tokens. The host returns
this endpoint as metadata; it does not claim MCP is enabled or authenticated.
Raw errors, stack traces, events, performance and logs stay with that official
MCP. This implementation introduces no diagnostic MCP wrapper or raw-event
replica.

Board Apps UI onboarding, selection removal with its own revision contract,
scheduled access health, common signal ingestion, Inbox projection and optional
resolution-proof workflow transitions remain unfinished. Provider OAuth client
onboarding and live SaaS/self-hosted acceptance also remain unverified. Tests
exercise native authentication, SQLite/PostgreSQL storage and host Vault with
mock official API transport; they are not live deployment evidence.

Official contracts:

- [GlitchTip OpenAPI](https://app.glitchtip.com/api/openapi.json)
- [Integration tokens](https://glitchtip.com/documentation/integrations/)
- [Official GlitchTip MCP](https://glitchtip.com/documentation/mcp/)
