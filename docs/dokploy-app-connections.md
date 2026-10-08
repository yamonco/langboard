# Dokploy App connections

Dokploy remains the deployment system. Langboard binds selected resources and
consumes deployment evidence through the current authorized connection. Generic
notification receipts describe channel activity; they do not establish a
particular deployment result or approve a card.

## Connection and resource access

Operators explicitly approve HTTPS instance bases with
`APP_CONNECTION_ALLOWED_BASE_URLS`. The configuration has no company defaults.
Store the management API key through the existing secure secret input and pass
only its canonical `secret://ref/...` reference to the board connection API.
Management reads use the official `x-api-key` header. Redirects and environment
proxies are disabled; provider responses are bounded and not returned raw.

Under `/board/{project_uid}/settings/apps/dokploy/connections/{connection_uid}`,
select Project → Environment → Application or Compose resources and explicitly
enable read access. Connection ownership, active membership, board update
permission, selected resource grants and current binding capabilities are checked
when accessing external functionality. Provider writes such as deploy, redeploy,
cancel and notification creation are not part of this read contract.

## Notification receiver

Configure a separate receiver token through secure input. It must not reuse the
management API key. `POST /webhook-config` requires current connection, binding
and local configuration revisions. An optional saved Dokploy notification ID
identifies the provider configuration to inspect.

The local receiver is `POST /apps/dokploy/notifications/{config_uid}`. In Dokploy,
an operator creates a custom notification with the intended public HTTPS endpoint
and `Authorization: Bearer <receiver token>`. Enable both successful deployment
and build-error notifications. Configure the token directly through secure
administration; Langboard does not return it in the browser or API response.

The receiver accepts only bounded supported JSON after authenticating the current
configuration and current authority. It stores a minimal deduplicated receipt
with server UTC reception time. Disabling or revoking access prevents new receipt
acceptance while preserving existing cards and receipts.

## Explicit provider configuration verification

`POST /webhook-verify` accepts `expected_revision`,
`expected_binding_revision`, `expected_config_revision` and the operator's exact
`callback_url`. A saved notification ID and an enabled, current receiver
configuration are required. The HTTPS callback may include an explicitly supplied
reverse-proxy prefix before the receiver path. The callback address is compared
only; it is never fetched and its origin is never inferred from an internal
service address or the browser location.

The server performs one bounded official `GET /api/notification.one` with the
saved notification ID. It compares notification identity, custom channel type,
endpoint, Authorization header and both notification flags. The response contains
only safe boolean checks, a server UTC `checked_at`, current revisions and
`provider_config`: `matched`, `mismatch` or `unavailable`. Provider headers,
credentials, endpoint values, names and error bodies are not exposed. Current
permissions, grants, configuration and both secret revisions are checked again
after provider I/O; a stale or revoked scope invalidates the result.

This verification is an explicit point-in-time observation. The browser clears
it when the input or relevant scope/configuration changes. The ordinary Health
response keeps provider configuration `unknown` until a new explicit observation
is made. Neither a matched configuration nor an authenticated local receipt
proves provider delivery history, deployment success or card approval.

Inspect `last_received_at` separately in `/webhook-health`; it is the actual
server time of the last accepted local receipt, not a timestamp supplied by the
provider. Verify real delivery and deployment polling in the target environment
before declaring the integration accepted.
