# External service app SDK

Langboard owns registration, current permissions, board settings and native
business commands. An app runs as a separate service. Its definition never
uploads executable server code, supplies a principal or overrides a repository.
This document distinguishes implemented contracts from remaining acceptance.

## Entry points

- [Python install and API guide](https://github.com/yamonco/langboard-sdk/blob/main/packages/python/GUIDE.md): caller-owned authenticated
  REST/MCP transports, registry, workflow mapping, card presentation and resources.
- [Panel SDK guide](https://github.com/yamonco/langboard-sdk/blob/main/packages/app-panel/README.md): isolated browser lifecycle, bounded
  session drafts and executable browser example.
- [Native command composition](native-extension-contract.md): trusted host tool
  selection, separate from external service registration.

## Authority and update flow

1. An instance administrator approves a versioned app definition. Built-in keys
   cannot be overwritten. Updates require an exact revision and newer version.
2. A board administrator reviews the requested capabilities and grants specific
   supported operations. Declaration and actual grant are different values.
3. A panel-only app can receive `panels.render` without workflow transitions,
   card mutation or automation permission.
4. Every panel mount reads current board access and consent. An enabled catalog
   entry or cached draft is insufficient authority.
5. Same-trust updates retain the intersection of previously approved capabilities.
   Added capabilities require new consent. Changes to publisher, authentication,
   MCP or data destinations, MCP identity, or the panel URL clear affected grants
   and revoke affected connections; disablement clears board grants. Updates
   require administrator review and emit a payload-free invalidation event.
6. Apps use stable built-in workflow keys. A board explicitly chooses an existing
   column for each key; app-owned workflow types are not created.

## Current support and acceptance

| Capability | Implemented evidence | Remaining boundary |
| --- | --- | --- |
| App registry | Native admin-authenticated HTTP, persistent definition, revision conflicts, update/disable revocation | Real independent service and deployed acceptance |
| Panel consent | Native board Read/Update checks, explicit UI confirmation, exact revisions | Deployed authenticated browser acceptance |
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
current credentials and validate the declared event identity. Existing generic
webhooks allow unsigned configuration;
SDK verification deliberately rejects unsigned input. Approved app delivery must
require a signing secret before it can become an accepted app outbox.

## Outbox implementation boundary

Delivery uses signing, URL validation, bounded timeouts and leased retries.
An app send must retain the exact approved destination and grant revisions,
recheck board/card/attachment access before enqueue and delivery, use a stable
send/event identity, and expose saved pending/delivered/failed/revoked receipts.
Retries must not silently change the destination or widen content scope.

## Verification and deployment

Portable SDK tests do not require Langboard or a database. Native HTTP tests
exercise authentication and real persistence in an isolated fixture. The browser
example exercises the actual sandboxed MessageChannel and draft restoration,
not deployed product authority. Build, migration, runtime health, authenticated
browser acceptance and business acceptance are separate gates. Draft PR submission
or local integration does not prove deployment.

## Policy and account ownership

Global policy sets the instance ceiling (`disabled`, `approved_only`, or
`personal_allowed`). Organization policy can only restrict it further. Personal
app distribution is separate from account ownership: an approved organization
app may use a user-owned account for that user's requested work. Unattended work on organization boards or boards with another assigned member
requires an organization-owned connection. A board without an organization ID
is still shared when it has collaborators. Personal unattended work is allowed
only on the account owner's private board. Deleted boards cannot authorize apps. Personal
account credentials and private data are not administrator-readable by virtue
of app approval.

Board catalog resource counts and health summaries include personal connections
only for their owner, including when the viewer is an instance administrator.
Organization connections are aggregated only for the board's own organization.
GitHub repository settings apply the same boundary to resource paths and IDs,
including retained selections after revocation. Client revisions cover only the
visible resources, so another user's private selections do not leak through a
revision or prevent the owner's independent selection updates.

The native policy API, connection ownership model and standalone SDK helpers
implement these boundaries. Personal app registration, connection scope consent,
optional MCP execution and all existing automation paths still require complete
runtime integration; declaration validation alone does not enable them.

Board administrators can disable an existing binding even after instance policy
or app registration has disabled its use. This removal still requires current
board Update authority and the exact binding revision. It does not restore app
discovery, execution, capabilities, or access to another person's connection.
Existing panel consent can also be withdrawn after policy or registration
disablement, using current board Update authority and exact app/binding
revisions. Withdrawal does not require the removed panel capability to remain
in the declaration; enabling a panel still requires current approval and policy.
The board catalog remains readable with current board Read authority under
disabled policy. Disabled app definitions appear only when the board already
has a retained binding; they expose current removal revisions with no declared
capabilities. This catalog is configuration metadata, not execution approval.
Normal approved-manifest resolution continues to exclude disabled definitions.
Catalog `is_available` reflects current policy and registration status. An
unavailable entry has no declared capabilities; the settings UI marks it
disabled and prevents new workflow configuration while retaining cleanup.
GlitchTip and Dokploy account owners can also remove selected resources or
disconnect their own connection after policy revocation, including connections
whose trust change has revoked credentials. These operations do not resolve
secrets or call the provider; retained cards, history, and shared secrets remain.
Their native connection lists and retained selection endpoints also remain
available to the account owner with current board Update authority after policy
revocation. Pending, revoked and disconnected metadata is returned without
credentials so clients can obtain current removal revisions. Provider discovery
and activation continue to require active policy and a connected account.
The shared settings panel has a separate saved-selection query and explicit
selection removal controls. This path does not depend on provider discovery.
Dokploy notification-health failures clear cached resource and notification
results while retaining the selected account metadata for removal. This retained
UI state grants no authority; every saved-selection query and removal still
requires current server authorization and revisions.
GitHub repository deselection uses the same revocation-only gate: revoked or
disconnected connections can remove existing selections with current board
Update authority, connection ownership and the exact resource revision. Adding
repositories still requires active policy and verified installation authority.


The standalone source repositories are `langboard-sdk`, `langboard-app-github`,
`langboard-app-glitchtip`, and `langboard-app-dokploy`. The host consumes reviewed
package artifacts, and the three panels use host design resources and the same
SDK read bridge. No provider credentials are passed into an iframe.
The `signals.list` bridge accepts a bounded adapter key rather than duplicating
the built-in provider list in the browser and request schema. The native read
still rejects adapters that are not installed in the host and rechecks current
board, connection and capability authority. Registering an external panel does
not install a signal adapter or grant access to another connection.

### Native signal revocation

Built-in adapters retain their host declarations when no registry override exists.
An explicit registry override can disable an adapter or reduce its capabilities;
it cannot add an unsupported built-in capability. Discovery excludes disabled
adapters. GitHub signal reads and leased signal delivery tasks, GlitchTip issue
refreshes, Dokploy deployment refreshes and Dokploy notification receivers check
current registry state again before committing new evidence. Card evidence,
board signal inboxes and linked-resource discovery also apply the current app
capability ceiling inside their existing SQL queries. Revoked evidence is hidden
without deleting it, and cursors into revoked resources become invalid. A revoked queued
GitHub delivery retains its normalized evidence and blocked delivery history.

Connection ownership is also checked in the shared SQL scope: a personal account
has no organization, and an organization account must match the board's active,
unsuspended organization. This check applies to card evidence and paged signal
and linked-resource discovery; a valid credential alone cannot substitute for
the current organization boundary.
The GitHub queued signal worker rechecks `unattended` connection authority for
each leased resource before writing evidence. Personal connections are blocked
on organization or shared boards; an owner-only personal board may retain its
explicit personal automation. Organization connections require a current matching
active organization. Existing evidence and failed delivery history are retained.
Direct GitHub signal reads also validate the requesting user's connection access,
not only the stored connection owner's authority. Board ownership and instance
administration do not make another user's personal account readable, including
when the requester supplies a previously known signal cursor.
The resource-specific GitHub webhook endpoint applies the same unattended gate
before signature resolution and again inside the evidence transaction. Changing
the connection to personal ownership or disabling its organization while a
signature is checked prevents the subsequent write.
Dokploy automatic notification authentication and receipt insertion use the same
unattended gate. Changes to ownership, board organization or organization state
between header authentication and streamed-body receipt insertion are rechecked.
Interactive configuration and health reads validate ordinary connection access.
When policy, app registration, connection state or a referenced secret is revoked,
notification health may retain removal revisions and prior receipt timestamps,
with no resource discovery or credentials. Disabling an existing receiver still
requires current board Update access, its connection owner and exact revisions;
it does not require the removed signal grant or an active secret. Reconfiguration
continues to require current app policy and active connection credentials.
Notification health includes a current `can_configure` hint. The UI keeps revoked
receiver metadata available for explicit disablement while blocking credential
input and configuration actions when that hint is false. The hint does not grant
authority: every mutation rechecks its current server permissions and revisions.
GlitchTip and Dokploy interactive metadata discovery and signal refresh validate
current connection ownership and matching active organization before provider IO
and again before returning results or persisting evidence. Owner-authorized
personal-account reads remain interactive operations; they do not acquire
organization automation permission from a board mapping.
This does not retroactively undo external changes or prove that every automation
route is integrated with connection ownership and governance policy.

The global governance editor serializes submissions immediately, including
multiple submit events before React renders its pending state. Failed saves
retain the selected mode and pinned revision; the guard releases for an explicit
retry. The saved revision receipt wraps on mobile rather than widening the page.
The browser regression exercises the actual page and query hook at 1280px and
390px using intercepted HTTP responses. It does not establish live administrator
authorization, organization policy UI or deployed policy enforcement.
