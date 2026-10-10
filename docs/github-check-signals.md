# GitHub check Signal ingestion

## Current delivery scope

The resource-scoped receiver accepts signed `check_run` / `completed` deliveries at
`POST /apps/github/boards/{board_uid}/connections/{connection_uid}/resources/{resource_uid}/events`.
It persists minimal append-only App Signal evidence. The existing
`POST /apps/github/events` now routes `check_run` completion deliveries to the durable
shared dispatcher, alongside its existing installation lifecycle consumer. The routing
candidate comes from `X-GitHub-Hook-Installation-Target-ID`; exactly one connected native
App Connection must match, and its HMAC authorizes the original bytes. No credential scan,
provider sender trust, or check-producing App identity is used for routing. Signed created,
rerequested and requested-action events are acknowledged without storing completion evidence.

The registration manifest remains unchanged with an inactive hook and no subscriptions.
This is not live provider acceptance or a completed Work State/Inbox implementation.

The adapter follows GitHub's official webhook contract:
- [check_run webhook](https://docs.github.com/en/webhooks/webhook-events-and-payloads#check_run)
- [Octokit webhook schema](https://github.com/octokit/webhooks/blob/main/payload-types/schema.d.ts)

`installation` is an InstallationLite containing an installation ID, not the full
installation lifecycle object. `check_run.app.id` identifies the check producer and
must not be compared to the receiving Langboard App ID. Sender identity is never used
as host authorization.

## Authority and data boundary

Original bytes are authenticated with the native Connection's SecretRef webhook secret
using HMAC SHA256 before JSON decoding. The shared HTTP body guard rejects duplicate
security headers, compressed bodies, non-JSON media types and bodies over 1 MiB.
The receiver requires all of:

- An active stored Connection owner with current board Update permission.
- A connected GitHub Connection.
- An enabled or needs-attention board App binding with an explicit `signals.read` grant.
- A selected repository resource with current granted access and exact matching
  repository ID, installation ID and repository owner/account ID.

Commit rechecks current authority, Connection identity revision, resource access revision
and path, and locks the current SecretRef to fence rotation or revocation. Neither resource
selection nor this receiver implicitly enables an App or grants a capability. Incomplete
workflow mapping does not suppress authorized evidence ingestion.

Stored evidence contains provider, event/delivery ID, event type, UTC occurrence timestamp,
external check ID, raw conclusion enum, commit SHA and original payload digest. Provider
output text, arbitrary URLs, sender details and credentials are not stored. `success` is
preserved as provider evidence only; it does not mean reviewer approval. Neutral/skipped
results remain distinct from success.

The unique resource/event key and current Connection lock serialize duplicate submissions.
Matching redelivery returns the existing UID; a changed signed payload with the same
delivery ID returns 409. All events remain append-only. Exact card-bound check scopes use the ordered projection
described below. The full multi-provider Signal card remains incomplete.

## Read surface and remaining work

The shared board Signal Inbox scopes discovery to the requesting user's personal
connections and organization connections belonging to the current board's organization.
Board ownership or instance administration does not expose another user's unshared
personal Signal rows. The same SQL scope applies before pagination and cursor validation,
so hidden personal rows do not produce discoverable cursors. Explicit card-bound evidence
remains a separate projection with its own card visibility rules.

`GET /board/{board_uid}/settings/apps/github/connections/{connection_uid}/resources/{resource_uid}/signals`
requires browser authentication and current board Read permission in addition to the live
consumer authority above. It returns 25 events per page with a scoped opaque cursor,
without payload digests, secrets or provider output. Disconnect/unlink/revocation blocks
new ingestion and this read surface; persisted audit evidence is retained.

Remaining: PR/deployment/GlitchTip/Dokploy adapters,
Inbox, provider presets, optional explicit workflow transitions, and user Automation.
No card, checklist, column, workflow stage or reviewer verification record is changed here.

Migration `f985238a4bc4` follows `e87412793ab3`. A populated downgrade is refused to preserve
provider evidence. No production migration or live provider acceptance is implied by tests.


## Durable shared dispatch

Migration `0a96349b5cd5` persists a verified minimal delivery and its dispatch cursor in
one transaction. No raw body, signature, arbitrary output or credential is retained.
The unique Connection/event key serializes duplicate receipts; changed content conflicts.
The delivery snapshots the highest matching resource ID, preventing newly created bindings
from receiving old events. Existing bindings are evaluated using their current state at
processing time; historical backfill is not performed.

Each native broker task claims a 300-second lease and processes at most one matching
resource. Processing locks current host authority, Connection, resource, SecretRef and
lease token before atomically storing evidence and advancing the cursor. Replays reuse
existing resource/event evidence. An unavailable board or revoked resource is skipped,
retaining a blocked terminal result, while other authorized boards proceed. Connection
revision or SecretRef rotation/revocation also prevents consumption of the old receipt.
Transient processing failure retries with 30-second exponential backoff, capped at four
attempts. Lease expiry permits crash recovery; stale lease holders cannot commit evidence.

After-commit queue dispatch is best effort. The existing GitHub recovery cron now dispatches
at most 100 due Signal deliveries in addition to at most 100 due health jobs. It reads the
indexed due-job set, not every repository or file. The API broker command registers both
health and Signal tasks from its API module. No shared package imports API policy.
Raw global delivery diagnostics and explicit terminal-job retry UI are not implemented.
Populated delivery downgrades are refused. No production migration has been applied.

## Explicit card evidence scopes

`POST /board/{project_uid}/card/{card_uid}/signals` selects an existing signed
check signal using `connection_uid`, `resource_uid`, `signal_uid`, and the current
`source_change_seq`. The caller needs current card visibility and `card_update`.
A new scope omits `expected_revision`; updating or re-enabling an existing scope
requires its exact revision. Each card permits at most 25 enabled scopes.

`GET` on the same path exposes current evidence. The scope matches the exact
repository resource, check ID and commit, ordered by provider occurrence time.
Older deliveries cannot replace newer outcomes. Equal-time contradictory outcomes
are `conflict`. A card edit makes the scope `stale` until explicitly rebound.
Current connection owner, membership, board grants, repository selection and
personal/project/workspace SecretRef authority are checked on primary storage.
Secret values and provider output are never returned.

`POST /board/{project_uid}/card/{card_uid}/signals/{binding_uid}/unlink` requires
`expected_revision` and current card modification authority. It preserves the
binding history and remains available after provider access is withdrawn.

Authorized Work State reads expose `external_signal_evidence`. Failed or
conflicting current checks project execution `failed`, blocker `blocked` and
exclude active execution; `human_execution_state` retains the timer diagnostic.
Successful checks provide evidence, never reviewer approval, completion or an
automatic workflow transition. Actorless socket projections omit this evidence;
clients obtain it through authorized reads. GlitchTip/Dokploy signals, deployment
proof and presets remain separate work.

### Card detail evidence controls

The card detail evidence section loads on explicit expansion, with no initial
provider request or timer polling. It supports current evidence refresh, explicit
repository/check selection, and revision-fenced unlink. Error paths clear stale
cached evidence; card navigation aborts pending requests and resets selection.
English, Korean, Japanese and Chinese labels are provided.

The authorized snapshot includes `bindings` containing only IDs and revisions,
including scopes whose provider access is revoked, so card editors can unlink
without retaining hidden provider evidence. `source_change_seq` fences attachment
against a card edit since the last refresh.

`GET /board/{project_uid}/card/{card_uid}/signals/resources` discovers currently
consumable selected repositories in explicit 25-row pages. It requires card read
visibility, rather than board settings Update authority. Connection owners still
need current board Update permission; SecretRef authorization shares the evidence
projection's batched primary query. Rows excluded by SecretRef authorization may
produce a short/empty page with a continuation cursor. No global background scan
or GitHub API request occurs. Check pages remain explicit and bounded too.

### Event-driven refresh

New signed check evidence, worker evidence insertion, explicit card binding/unlink
repository selection changes, scoped lifecycle invalidation and resource health refresh
register a native socket notice after transaction
commit. Rollbacks and duplicate deliveries emit no notice. The board-scoped notice
contains only `app_signal_changed: true`; it reveals no card ID, repository, commit
or provider result. Open evidence controls coalesce bursts for 150 ms and reread
through the authorized native API. Closed controls perform no refresh requests.
Reconnect, visible-window focus and changes to the card revision also refresh open
controls. Refresh waits for an active mutation to finish; it does not cancel writes.

Socket transport is best-effort, not a durable outbox. A transport failure does not
roll back committed evidence. Lifecycle invalidation queries only affected selected repository boards and emits once
per distinct board; ping and duplicate receipt replay emit nothing. Health refresh emits
once per nonempty committed resource page. SecretRef and ACL mutations do not yet
publish this notice; reconnect, focus or explicit refresh reevaluates authority.
Live provider acceptance and the full mounted card integration on deployed canary,
other provider types and the remaining Signal contract remain unverified.

### Board Signal Inbox foundation

`GET /board/{project_uid}/signals/inbox` requires browser authentication and
current board Read permission and membership. It returns up to 25 currently
consumable GitHub check scopes with an explicit continuation cursor. It groups
by repository/check/commit using provider occurrence time; older redeliveries
cannot replace newer outcomes. Contradictory equal-time results return
`conflict: true` and no selected outcome. The API exposes only normalized
provenance, never provider output, payload digests or raw event bodies.

Enabled links to currently readable cards remove that scope from this reader's
Inbox. Hidden card links do not affect visible results or reveal card existence.
Unlink restores discovery. This visibility rule is not a global duplicate-card
creation policy. Current Connection owner, board grants, selected repository and
SecretRef authorization use the existing primary-storage policy and batched
SecretRef check. Revoked references can produce a short/empty page with a cursor.
A cursor must identify a currently visible candidate; linked/removed candidates
require restarting discovery instead of relying on an outdated continuation.

This foundation performs no card creation, workflow transition or background
scan. Existing explicit card attachment remains the mutation path. Board/personal
Inbox UI, creation deduplication, workflow context after linking, PR/deployment
and other provider adapters remain incomplete. Automatic creation remains absent.
