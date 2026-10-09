# External service app SDK

Langboard owns registration, current permissions, board settings and native
business commands. An app runs as a separate service. Its definition never
uploads executable server code, supplies a principal or overrides a repository.
This document distinguishes implemented contracts from remaining acceptance.

## Entry points

- [Python install and API guide](../src/sdk/py/GUIDE.md): caller-owned authenticated
  REST/MCP transports, registry, workflow mapping, card presentation and resources.
- [Panel SDK guide](../src/sdk/js/README.md): isolated browser lifecycle, bounded
  session drafts and executable browser example.
- [Native command composition](native-extension-contract.md): trusted host tool
  selection, separate from external service registration.
- [Execution binding](execution-binding-cutover.md): existing work.ready delivery
  and generation fences; not an arbitrary app outbox.

## Authority and update flow

1. An instance administrator approves a versioned app definition. Built-in keys
   cannot be overwritten. Updates require an exact revision and newer version.
2. A board administrator reviews the requested capabilities and grants specific
   supported operations. Declaration and actual grant are different values.
3. A panel-only app can receive `panels.render` without workflow transitions,
   card mutation or automation permission.
4. Every panel mount reads current board access and consent. An enabled catalog
   entry or cached draft is insufficient authority.
5. App updates or disablement clear existing board grants and transitions in one
   transaction. The committed change emits a payload-free invalidation event.
6. Apps use stable built-in workflow keys. A board explicitly chooses an existing
   column for each key; app-owned workflow types are not created.

## Current support and acceptance

| Capability | Implemented evidence | Remaining boundary |
| --- | --- | --- |
| App registry | Native admin-authenticated HTTP, persistent definition, revision conflicts, update/disable revocation | Real independent service and deployed acceptance |
| Panel consent | Native board Read/Update checks, explicit UI confirmation, exact revisions | Canary product UI acceptance |
| Panel lifecycle | One selected visible iframe, abort/teardown, scoped session snapshots, SDK example | App-specific business execution is separate |
| Card presentation | Shared card.presentation.v1 validation and native storage | Display traits cannot change access policy |
| Card creation | Native permission-checked commands and stable work-plan receipts | App automation principal and external event dedup acceptance |
| Resource selection | Common 1:N declarations and provider-specific native connections | Generic external service onboarding is not implied |
| Shared design | Existing Button/Textarea/Badge wrappers, semantic theme channel and hashed resource manifest | Compiled resource and canary browser acceptance |
| Signed event verification | Portable exact-byte v1 HMAC verifier | Consumer durable duplicate detection and app outbox delivery |
| App outbox | Existing webhook signing, URL policy and execution lease contracts inspected | Board/app scoped enqueue, attachment access, delivery history and retry UI not implemented |

## Panel state and design resources

Panel state is disposable UI draft data, never credentials, an execution queue or
business receipts. Snapshots are limited to 16 KiB each; a session cache permits
32 entries and 256 KiB total. Keys include user, board, app and version. Account
change and observed revocation clear drafts. Rapid writes coalesce every 150 ms;
closing before transmission may discard the pending latest value. There is no
last-minute hide flush guarantee or persistence across browser restart.

Use existing Langboard design resources and widgets through the SDK. Automatic
host theme synchronization and shared widget packaging are implemented in source;
the compiled widget browser fixture verifies theme changes without remounting,
input preservation and close/reopen draft restoration. Deployed acceptance is
still a separate gate. Do not add another theme picker, duplicate
component CSS or copy the application bundle into each plugin. Shared public
assets must be cacheable and work in an opaque sandbox, with no authenticated API
CORS widening. A theme/design channel carries presentation only, not authority.

## Webhook authentication

Use `verify_webhook` on the exact raw body **before** JSON parsing or side effects.
Headers are case-insensitive; duplicate authentication headers are rejected.
The verifier requires version 1, HMAC-SHA256, a nonempty signing secret, a delivery
age of at most five minutes and at most 30 seconds of future skew. Keep clocks
synchronized. Requests are limited to 1 MiB. Errors do not echo body or secret.

```python
import json
from langboard_sdk import verify_webhook

verify_webhook(raw_body, request_headers, configured_signing_secret)
event = json.loads(raw_body)
# Persist event_id atomically with the consumer's business effect. On a repeated
# event, return the saved receipt. Do not re-execute an action solely on a retry.
```

This verifies authenticity, not board authority or event freshness for execution.
A valid signature does not grant card access. Read authoritative content with
current credentials; for work.ready, also validate the current execution
readiness and generation. Existing generic webhooks allow unsigned configuration;
SDK verification deliberately rejects unsigned input. Approved app delivery must
require a signing secret before it can become an accepted app outbox.

## Outbox implementation boundary

The existing execution outbox is keyed by card execution generation and frozen
execution binding. Reusing its table for arbitrary card/attachment app sends
would conflate readiness with user-directed transfer. Reuse its proven signing,
URL checks, bounded timeout and lease/retry principles at the delivery boundary.
A new app send must retain the exact approved destination and grant revisions,
recheck board/card/attachment access before enqueue and delivery, use a stable
send/event identity, and expose saved pending/delivered/failed/revoked receipts.
Retries must not silently change the destination or widen content scope.

## Verification and deployment

Portable SDK tests do not require Langboard or a database. Native HTTP tests
exercise authentication and real persistence in an isolated fixture. The browser
example exercises the actual sandboxed MessageChannel and draft restoration,
not deployed product authority. Build, migration, runtime health, authenticated
browser acceptance and business acceptance are separate gates. Draft PR submission
or a local union cherry-pick does not prove canary deployment.
