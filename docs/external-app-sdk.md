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

## External execution authority boundaries

The existing execution webhook is a board-owned readiness notification, not an
app-scoped automation grant. Its current fence checks the mapped ready column,
prerequisites, execution generation, signed destination and binding revision.
An external app must not treat `execution.is_ready` alone as proof of current app
consent, organization connection authority, selected external resources or human
approval. Those checks are not yet composed into one external-app execution fence.

General external-resource bindings, app-scoped delivery and native human questions,
instructions and approvals remain required integration work. Their host contracts
must use app/connection/resource identities and stable workflow stages; vendor
project or repository semantics belong to the external service. Registration must
not implicitly grant unattended execution. Permission checks are required again
when queuing, claiming work and accepting a result. Revocation must preserve
delivery and result history without representing an external change as undone.

The native generation-based execution receipt endpoint and webhook delivery lease
are existing building blocks. They do not prove that an arbitrary registered app
can complete this lifecycle or safely stop and resume an external worker.

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

Organization policy discovery uses `GET /settings/apps/governance/organizations`
with an optional `cursor` and `limit` (default 25, maximum 50). The current primary
user determines visibility: administrators see active, unsuspended organizations;
other activated users see only those they own. Each item contains only `uid` and
`name`. `next_cursor` identifies the last returned organization when another page
exists; invalid cursors are rejected rather than silently restarting pagination.
Enumeration does not grant policy authority. The per-organization GET/PUT APIs
still recheck the current actor, organization state and policy revision. This API
does not expose personal connections, tokens, employee membership or credentials.

The Apps settings page is available to organization owners as well as instance
administrators. Its scope selector consumes the paginated authorized organization
API. Only administrators see the instance-policy option; organization owners do
not request global policy data. The same editor uses separately keyed queries and
mutations for each selected organization, supports `mode: null` inheritance, and
displays the server's effective policy under the instance ceiling. Scope and page
changes are disabled while a draft is dirty or a request is active. Save or
explicit Cancel releases that guard; switching scopes mounts a separate editor
so its baseline revision cannot migrate to another organization. Four supported
languages include scope, inheritance and ceiling explanations. The Chrome HTTP
fixture covers desktop/mobile global saves and an owner-only organization flow
with cancellation, conflict preservation and a null inheritance write. A separate
pagination regression switches between two organizations with distinct revisions,
asserts the exact organization-specific write, and verifies that returning to the
first scope restores inheritance without another scope's draft or save receipt.
Dirty drafts block pagination until Cancel; visiting first, next and first pages
makes exactly three discovery requests without background polling. Real
organization consent, administrator sessions and deployed acceptance remain
separate checks.

GlitchTip and Dokploy explicit read consent adds only its required read
capabilities to the existing board grant set. It preserves independently approved
panel and workflow permissions and the existing transition toggle; it does not
grant a new workflow permission or enable transitions. Repeated read consent is
idempotent. Registry trust changes, policy restrictions and explicit revocation
remain separate authorization boundaries. Native SQLite regressions cover both
providers and Dokploy application/compose resources; PostgreSQL acceptance still
requires a disposable configured database.

Board connection settings expose **Revoke board read access** for GlitchTip and
Dokploy. The authenticated `POST .../connections/{connection_uid}/disable-read`
requires the current connection and board-binding revisions. It removes only
that provider's board-wide read grants; connections, selected resources, existing
observations and independently approved panel/workflow grants remain intact.
Current board update authority and connection ownership are rechecked. Revocation
does not require an active credential or an external provider request, so a broken
provider cannot prevent it. Subsequent native reads and unattended webhook reads
use the existing current-grant gates. This does not claim cancellation of work
already accepted by an external service or complete personal MCP consent support.

The revoke control remains visible for any remaining provider read grant, even
when the grant set is partial or no selected resource is currently eligible.
Use **Load saved selections** to obtain the binding without provider discovery.
Re-consent still requires an eligible selected resource. Native SQLite regression
also proves revocation under a disabled global policy, disabled app definition
and revoked credential, with no provider I/O and no change to another board's
binding or the connected account. These are local authority proofs, not deployed
PostgreSQL or external-operation cancellation evidence.

Read-grant revocation publishes the existing content-free `apps:changed` event
only after a committed binding revision change. Repeated revocation and rolled
back transactions emit nothing. The existing board socket receiver disposes
active panel sessions, clears the selected app and invalidates the catalog when
that event arrives. SQLite tests prove commit/rollback notification behavior;
actual deployed socket delivery and multi-browser acceptance remain required.

GlitchTip and Dokploy connection disconnection uses the same post-commit panel
invalidation event. An already-disconnected connection returns its current receipt
without incrementing resource revisions or sending another event. A stale revision
or transaction rollback emits nothing. Selected resources, observations, board
workflow configuration and shared secret references remain preserved; disconnected
resource access stays revoked. Local SQLite tests exercise those transaction and
idempotency boundaries; deployed event delivery is still an acceptance gate.

Individual GlitchTip project and Dokploy resource deselection also emits the
existing payload-free app invalidation event after commit. An exact-revision
repeat returns the retained deselected resource without incrementing its access
revision or emitting another event. Stale revisions and rolled-back transactions
do not notify; sibling selections remain intact. Native SQLite tests exercise
these boundaries. This reuses the existing live panel disposal handler, while
deployed multi-client event delivery remains an acceptance requirement.

GitHub lifecycle health workers use the same unattended connection ownership
policy as check-event delivery. Before external installation inspection and
again before publishing refreshed resource access, they require a connected
account authorized for the current board. A personal account cannot service a
shared board automatically; the owner's private board remains eligible. Adding
a collaborator during the external query prevents the health result from
restoring resource access. Synchronous user-requested health refresh keeps its
existing path. Local lifecycle tests cover the private-board success, shared-board
rejection, mid-query sharing race, resource paging and authenticated diagnostics.
Deployed organization connection onboarding and worker acceptance remain required.

### Inbound connection identity (local implementation)

An authenticated connection owner can issue a dedicated inbound credential with
`POST /settings/apps/connections/{connection_uid}/credentials`. The JSON body
accepts `expires_in_seconds` (integer, 60–86400; default 3600). The response
contains `credential_uid`, `connection_uid`, `token` and `expires_at`. The token
is returned once; the database retains only its SHA-256 hash. Responses use
`Cache-Control: no-store`. Personal credentials can be managed only by their
owner; organization credentials require the existing organization management
authorization.

An external app sends `Authorization: Bearer <token>` to
`GET /apps/v1/identity`. The response contains `schema_version: 1`, `app_key`,
`connection_uid`, `credential_uid` and optional `organization_uid`. App identity
comes from persisted connection state, never a caller-supplied app key.
Authentication checks current connection, account, app registration, organization
and effective policy. Expiry, revocation, connection revision or trust-target
changes invalidate the credential. Same-trust app version updates preserve it
when the connection itself is unchanged.

Owners can revoke with
`POST /settings/apps/connections/{connection_uid}/credentials/{credential_uid}/revoke`.
Revocation is idempotent and remains available after app or policy disablement;
credential history is retained. These credentials cannot authenticate as users
or bots. Identity alone grants no card mutation or execution capability. The
app-owned card fence, app execution grants, HITL delivery contract and independent
app end-to-end acceptance remain subsequent work. These endpoints have local
implementation evidence; deployment and PostgreSQL acceptance are pending.

Owners can recover an uncertain issuance outcome with
`GET /settings/apps/connections/{connection_uid}/credentials`, using native user
authentication. This bounded history remains available after connection or app
disablement. `limit` defaults to 25 (maximum 50); `after` is a credential UID cursor.
Items contain only `credential_uid`, `created_at`, `expires_at` and `revoked_at`.
No token, token hash, trust hash or provider secret is returned. Inspect this
history and revoke the affected credential before explicitly issuing a replacement;
an unavailable issue response must never trigger automatic repeat issuance.

### Credential-scoped resource reads (local implementation)

`GET /apps/v1/boards/{project_uid}/resources` accepts the inbound connection
credential. `limit` defaults to 25 and is bounded to 1–50; `after` is the returned
resource UID cursor. Invalid credentials return 401; authenticated callers without
current board authority return 403. Validation follows native API conventions
(400). Responses are not cached and include `schema_version: 1`, `connection_uid`,
`binding_revision`, `items` and `next_cursor`.

The existing app declaration and enabled board binding must both permit
`resources.read`. The connection owner must retain current board membership and
read permission. Autonomous shared-board requests require a matching active
organization-owned connection; personal connections can serve only the owner's
unshared personal board. Instance and organization policy remain authoritative.
Results contain only this connection's selected resources with granted access,
within the current declaration's resource types. Items expose `resource_uid`,
`resource_type`, `external_resource_id`, `resource_path`, `access_revision` and
`health`; they never expose provider secrets. Health is an observation, not an
execution grant. Cursor pages recheck current authority independently.

This route reuses `AppResourceBinding` rather than creating provider-specific
resource models. It does not establish card-to-resource execution bindings or
authorize card mutation. PostgreSQL, deployed use and external-app acceptance
remain pending.

SDK 0.2.3 exports `AppResources`, `AppResource` and `AppResourcePage` from
`langboard_sdk.resources`. `AppResources(app_transport).list(board_uid, limit=25,
after_uid=None)` consumes the native resource route through the separate app
Bearer transport. It fetches one page only; callers explicitly pass `next_cursor`
as `after_uid`. The current host rechecks authority on every page. Independent
wheel/native HTTP tests verify paging, native response fields and capability
revocation without retries or automatic crawling. Resource reads confer no card
execution grant; card resource bindings and execution/HITL wires remain pending.

### App-owned card governance storage (internal implementation)

`CardAppOwnership` stores a nullable app key and revision independently of
`Card.visibility`, private owner, creator and presentation metadata.
`set_card_app_ownership` currently exists as an internal service only. It requires
current instance administration, board ownership, or board membership with its
existing management permission. It additionally rejects another user's private
card, mismatched project and deleted card. Assigning an app requires current
approval and project policy; release remains possible after app disablement.

Initial assignment expects no prior revision; transfer and release require the
current integer revision. A repeat of the current decision produces no new audit
entry. Every changed decision retains the actor, previous and new app keys and
revision in `CardAppOwnershipAudit`. Outer transaction failure rolls both back.
Audit card IDs have no cascading card foreign key, so governance evidence is not
silently removed by card deletion. Migration downgrade refuses to discard history.

This is storage and management preparation, not an enforced exclusive mutation
claim. No REST/MCP/UI ownership configuration is exposed yet. The canonical card,
stage, checklist and HITL mutation fence must be implemented before exposing the
configuration surface. PostgreSQL concurrency and native HTTP acceptance for
that complete fence remain pending.

The first native mutation fence now wraps the existing card update/order/archive,
assignment/labels, checklist, checkitem and comment mutation services. User-scoped
calls continue through those operations' existing authorization. Unbound bot
calls lock current project/card state and reject cards with an active app owner;
caller-supplied app metadata cannot replace authenticated connection authority.
Released and unowned cards retain their existing bot behavior. No dedicated app
mutation grant is implemented yet. Receipt writes now recheck ownership in their
execution transaction after the execution lock and current visibility check,
before persistence, checklist reconciliation or a Review move. Unauthorized bot
writes return 403; existing receipt reads retain their visibility checks.
Attachment upload, rename, delete, ordering and explicit processing/embedding
requests also use the native service fence. Ordering and processing methods require
an explicit authenticated actor; REST/MCP callers pass their current user, without
inferring automation authority from the attachment author or card owner.
Card-scoped native graph approval creation also holds the project/card ownership
lock through persistence. A supplied bot or internal bot takes precedence over a
requesting user; none of them carries an owner-app grant. Human-only and released
bot requests retain the existing native scope/origin validation. Other approval
scopes and human approval resolution retain their existing behavior. This does
not implement the generic external-app HITL request/response/delivery contract.
Native orchestration metadata, verification, run, suggestions, bypass decisions
and child creation also use the ownership fence before writing or dispatching.
Metadata/run/suggestion methods require an explicit actor; route callers forward
current authentication. Child creation checks the parent card before creating a
new card or updating parent metadata. This does not authorize an external app to
execute these operations. Native relationship replacement and graph patch/preview
check the anchor, existing/new endpoints and endpoints of removed edges under the
project transaction before readiness watches or persistence. An unowned anchor
cannot be used to add or remove another app's card relationships. These fences
retain human permission paths and do not issue an owning-app execution grant.
Public card metadata writes in REST and both MCP surfaces use authenticated
`MetadataService.save_card/delete_card` boundaries. Their internal-key option
does not bypass app ownership. Generic metadata storage remains available to
internal document/work-plan/projection paths; those paths still require their own
caller and lifecycle audit before claiming complete mutation coverage.
The generic HITL contract and remaining direct repository
writes also require separate fence coverage before
ownership configuration is exposed. Service tests prove the exercised denial
paths; they do not prove deployed REST/MCP or PostgreSQL concurrency acceptance.

The native GitHub health worker now has an organization-owned connection
acceptance regression using actual SQLite lifecycle receipts and leased jobs.
An active matching organization completes the job and restores resource health.
Suspension before the query produces no external inspection; suspension during
the query prevents result publication and leaves the job blocked with retained
unknown access. Three cases pass locally. PostgreSQL schema, real GitHub I/O and
deployed worker execution remain unverified by this regression.

### Explicit card execution resource selection (internal implementation)

`CardAppResourceSelection` stores a revisioned, bounded set of at most 20 generic
resource UIDs for one card/app and one connection. This is separate from the
commit/check-specific `CardAppSignalBinding`. `set_card_app_resources` requires a
current human board administrator, current card visibility, matching app ownership,
current unattended connection authority, declared `resources.read`, board consent
and selected/granted resources belonging to the same board and connection.
Replacing a selection requires its current revision. Resource identifiers confer
no authority; execution must recheck current resources and execution gates.

Empty selections explicitly unlink resources, including after consent revocation.
Every changed selection appends an audit record atomically. Audit rows have no
card/connection foreign keys, and downgrade refuses to discard existing history.
The internal service is not exposed as an execution API or SDK grant. Native
REST/MCP configuration, execution grants, PostgreSQL concurrency, HITL/outbox and
external-app acceptance remain pending.

### Current execution authority inspection

SDK 0.2.4 adds the separate reviewed `execution.run` capability. Adding it to
an app update requires additional explicit consent; existing resource read
consent does not acquire it. The host offers
`GET /apps/v1/boards/{board_uid}/cards/{card_uid}/execution-authority?generation=N`
through dedicated app Bearer authentication, without accepting caller identity.

The current primary checks owning app, current connection/policy and actor role,
card visibility, current resource selection/access/type, current board consent,
explicit built-in ready mapping, unsatisfied blocking prerequisites, pending
native approvals and the requested positive execution generation. Successful
inspection returns `state: eligible` and `started: false`, with ownership,
selection, board and card revisions. It is not a stored grant, lease, execution
start, stop acknowledgment or a mutation authorization token. Every future write
must recheck current authority. Durable execution/HITL receipts, start/resume,
active-stage mutation fences, signed event delivery and PostgreSQL concurrency
acceptance remain pending.

### Durable execution request acceptance

`POST /apps/v1/boards/{board_uid}/cards/{card_uid}/execution-requests` accepts
only `{ "generation": N }` with a strict positive integer and a dedicated app
Bearer credential. It evaluates current authority in the same atomic transaction
as insertion. `AppExecutionRequest` preserves the accepted authority snapshot
without card/connection foreign keys. The unique card/generation record returns
the same request UID for a retry only after current authority is rechecked.
Changing owner, connection, selection, board revision or resource access revision
conflicts with that accepted generation. Revocation denies a retry without
removing evidence. Downgrade refuses to discard existing requests.

The response is `state: requested`, `started: false`. This is request acceptance,
not dispatch, delivery, a running lease or an external runtime acknowledgment.
No automatic start or resume is implemented by this route. Durable signed
outbox delivery, request discovery and start/stop/resume acknowledgment remain
required before an external app can execute through this flow.

### Independent execution client (SDK 0.2.5)

`from langboard_sdk import AppExecution, ExecutionAuthority, ExecutionRequest`.
`AppExecution(app_transport).authority(board_uid, card_uid, generation=N)` calls
current authority inspection; `.request(board_uid, card_uid, generation=N)` calls
request acceptance. Both use the caller-owned app Bearer transport. No automatic
start, stop, retry or token refresh is performed. Native wheel/HTTP tests cover
current authority, duplicate request identity and immediate consent revocation.
The successful responses explicitly retain `started: false`.

The existing board execution outbox has a unique card/generation identity and a
board webhook destination contract. App requests cannot be inserted as another
ready event without colliding with that contract. App-scoped signed delivery is
not implemented by the SDK clients and remains a required host integration.
