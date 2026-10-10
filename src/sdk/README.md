# Independently versioned SDK consumption

SDK source and package tests live in [langboard-sdk](https://github.com/yamonco/langboard-sdk).
This host consumes the same reviewed npm tarball and Python wheel as external apps.
`vendor/provenance.json` records package versions and SHA256 digests. The UI lockfile
pins the npm artifact; both Python lockfiles pin the wheel hash. This snapshot is
not a public npm/PyPI registry publication.

Update the SDK in its repository, run its standalone checks, build artifacts, then
update this directory and the host lockfiles in a reviewed change. Never edit the
package bytes here or restore parallel SDK source implementations. Native host
integration tests remain in this repository because current authentication,
permissions, consent and resource projections are owned by the host.

Panel protocol v1 and package semver are distinct. Existing lifecycle-only panels
remain supported. `signals.list` additionally needs the native panel read bridge,
explicit `signals.read` board consent and current provider resource authority.
An older host without the bridge returns an unavailable error; no permission or
provider operation is inferred from SDK installation.

Python SDK 0.2.1 adds `GlitchTipManager.disable_read` and
`DokployManager.disable_read`. The host and shared Python manifests/lockfiles pin
the same wheel SHA256 recorded in provenance. Integration tests import that wheel
directly and exercise authenticated native read, revocation, denied refresh and
explicit re-consent with persistent observations. No SDK source-directory import
or editable installation is used. The panel package remains 0.2.0/protocol v1.
This local package update is not a registry publication or deployed host claim.

Python SDK 0.2.2 adds `ConnectionCredentials` for explicit owner-managed inbound
credential issue/revoke and `AppIdentity` for the server-derived connection
identity. Use separate owner and app HTTP sessions. The host imports the reviewed
wheel for an authenticated issue → identity → denied user impersonation → revoke
→ 401 roundtrip. No editable SDK installation or host-private SDK import is used.
Identity grants no execution or card mutation capability. The local package and
lockfiles are pinned by digest; deployed compatibility remains pending.

Python SDK 0.2.6 makes `expected_authority_version` mandatory for execution
requests. Pass the version from the preceding authority lookup; the host compares
the current snapshot before persisting either request or outbox event. A stale
version returns 409. The receipt returns its fixed `authority` snapshot; the GET
response additionally has `state: eligible` and `started: false`, so compare the
snapshot fields rather than GET-only status fields. SDK 0.2.5 generation-only
requests fail input validation. This package update is not a deployment or an
execution start; callers need an explicit upgrade.

Python SDK 0.2.7 adds app-authenticated request readback and reception
acknowledgment. `read_request` returns the fixed accepted authority snapshot;
`acknowledge` records `received/started:false` with the matching event UID and
runtime reference. These operations do not start execution or approve work.
The independently built wheel and both lockfiles remain digest pinned.

Python SDK 0.2.8 adds an explicit runtime permit boundary. `authorize_runtime`
requires the accepted request and its `acknowledgment_uid`, plus a random
32-byte lowercase-hex runtime token. It returns a 120-second
`permit_execution: true` authorization with `started: false`; acquiring it
does not start a process. `check_runtime` renews only while current authority
still matches. A revoked connection, stage/resource drift, or expiry changes
the permit to `stop_requested`; the receiver may then submit `stopped: true`.
The opaque token is scoped to that lease and remains valid for stop-only
recovery after app credentials are revoked. Stopped or expired permits never
resume; a new accepted request and generation are required. The host preserves
the stop history, and scheduling, external process start, and HITL resume are
separate integrations.

Python SDK 0.2.9 adds `RuntimePermit` identity types and `recover_runtime`.
Recovery uses the accepted request UID and the privately persisted token to
find an existing permit; it applies the same primary-database authority and
expiry checks as heartbeat. It cannot create, rotate, or resurrect a permit.
An unknown recovery outcome is not permission to execute and is never retried
implicitly by the SDK.

Python SDK 0.2.10 adds `report_start` and `ExecutionStartReport`. The native
app-authenticated endpoint records a receiver-reported execution reference
only under a current live permit. `start_reported/app_attestation` describes
the evidence source explicitly; it is not host process observation, dispatch,
workflow transition, or completion. Duplicate reports are idempotent only for
the same execution reference. Permit receipts still return `started:false`.

Python SDK 0.2.11 adds `runtime_report` and `RuntimeReport`. The read revalidates
current authority without extending the permit. It retains historical start
attestation separately from `active_report`; stopped, expired or revoked
permits cannot appear active. This is an app-attestation projection, not
independent process health. Use explicit heartbeat calls for renewal.

Python SDK 0.2.12 adds `CardResources.read/select` for human administrator
configuration through the native card-resource GET/PUT routes. Use a user
transport separately from app-scoped `AppResources`. Read current revision
before replacement; an empty selection unlinks resources. No automatic retry,
execution grant or workflow transition is performed. The reviewed wheel is
pinned with its digest in `vendor/provenance.json`.
