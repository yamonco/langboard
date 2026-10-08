# GitHub check Signal ingestion

## Current delivery scope

The resource-scoped receiver accepts signed `check_run` / `completed` deliveries at
`POST /apps/github/boards/{board_uid}/connections/{connection_uid}/resources/{resource_uid}/events`.
It persists minimal append-only App Signal evidence. This is a backend receiver, not
an enabled GitHub App subscription or a completed multi-repository dispatch implementation.
The existing `/apps/github/events` receiver still handles installation lifecycle events only.
GitHub Apps have one configured webhook URL; routing that shared URL to multiple board
resource bindings remains required before enabling check subscriptions. The registration
manifest remains unchanged and check webhook consumption is not advertised as available.

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
delivery ID returns 409. All events remain append-only. No latest Work State projection
exists yet, so this unit does not claim ordered projection or completion of the Signal card.

## Read surface and remaining work

`GET /board/{board_uid}/settings/apps/github/connections/{connection_uid}/resources/{resource_uid}/signals`
requires browser authentication and current board Read permission in addition to the live
consumer authority above. It returns 25 events per page with a scoped opaque cursor,
without payload digests, secrets or provider output. Disconnect/unlink/revocation blocks
new ingestion and this read surface; persisted audit evidence is retained.

Remaining: shared App webhook dispatch and recovery, PR/deployment/GlitchTip/Dokploy adapters,
explicit card/resource evidence association, out-of-order-safe Work State projection,
Inbox, provider presets, optional explicit workflow transitions, and user Automation.
No card, checklist, column, workflow stage or reviewer verification record is changed here.

Migration `f985238a4bc4` follows `e87412793ab3`. A populated downgrade is refused to preserve
provider evidence. No production migration or live provider acceptance is implied by tests.
