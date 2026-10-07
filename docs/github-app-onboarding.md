# Native GitHub App onboarding

The native host starts registration with authenticated
`POST /board/{uid}/settings/apps/github/manifest`. It returns the official GitHub
registration form target and Manifest JSON. Optional organization targets are
strictly bounded GitHub slugs. Current board update authority is required.

The host stores a random nonce bound to actor, board and an independent random
HttpOnly, SameSite=Lax, production Secure cookie for ten minutes. Cache keys store
a digest of the nonce. Callback completion requires the same authenticated actor,
board and cookie and claims state atomically before exchanging a one-time code.
Wrong session/board, missing/expired state, current permission revocation and
replay fail before GitHub exchange. Ambiguous exchange failure is never retried
automatically.

The Board Apps onboarding panel POSTs `{state, code}` to the authenticated completion endpoint after
GitHub returns to the board URL. The host exchanges the code only at the fixed
GitHub API endpoint, with redirects disabled and a finite timeout. Credential
response fields are validated then stored as one personal Secret Reference;
AppConnection retains only its canonical URI. Returned data contains the pending
connection and installation URL, never credential values. Registration is distinct
from installation: `pending` and `installation_verified: false` are intentional.

The Manifest requests read permissions only. Webhook delivery is disabled until
an authenticated signature-verifying signal receiver exists. No manual PAT,
private key or webhook URL is required by this registration path.

## Remaining acceptance

Live installation acceptance, reusable Connection selection in fresh browser tabs,
installation lifecycle callback state, reinstall/uninstall lifecycle and webhook
processing remain
pending. Store onboarding availability must remain false until these paths work.
Current tests use actual native authentication, SQLite/PostgreSQL storage and
mock GitHub transport, not live GitHub installation acceptance. No production
migration, deployment or external App creation was performed.

Official protocol: https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest

## Installation and repository inspection

Native authenticated `GET /board/{uid}/settings/apps/github/installations/{id}/repositories`
requires `connection_uid`, expected `account_id` and a bounded page. Host checks
current board update authority and Connection owner/state, resolves its secret
only in runtime, and signs an RS256 App JWT with the existing PyJWT dependency.
The fixed GitHub API re-reads the installation and validates App ID, installation
ID, expected account identity/type and suspension state.

A metadata-only ephemeral installation token lists up to 100 repository identities
per page. Each repository owner must match the verified account. Token is never
persisted or returned and is revoked after inspection; revocation failure prevents
a successful result. Current board authority and Connection state/reference are
rechecked after external IO. Responses contain repository IDs/names and pagination,
not tokens or arbitrary external URLs. Inspection does not create a Binding or
mark the Connection connected.

Tests sign and verify actual RSA JWTs with mock GitHub transport. Live GitHub
acceptance, installation callback state and UI account/repository selection
remain pending. API verification supplements the earlier Manifest flow;
it does not claim the remaining acceptance list is complete.

## Incremental repository resources

Authenticated GET and PUT `/board/{uid}/settings/apps/github/resources` share
current board update authority. GET returns repository resource metadata and a
snapshot revision. PUT accepts one current-owner Connection, installation/account
identity, up to 25 positive IDs to add and 25 to remove, and `expected_revision`.
Empty, overlapping or duplicate deltas are rejected. Additions mint a metadata-only
token restricted to the requested IDs and require an exact returned ID set and
count; the token is revoked before persistence. Missing, substituted or duplicate
external repositories fail without changing selection.

The transaction locks the board, Connection and Binding and rejects stale resource
snapshots or changed Connection identity. Removal only deselects the targeted
board/Connection repository; re-addition reuses its existing row. Other repositories
and other boards remain intact. New Binding stays disabled; resource access does
not grant workflow capabilities, enable webhook processing or connect the App.
No schema migration is added by this delta. SQLite/PostgreSQL regression covers
preservation, re-selection and stale-edit rejection with mock GitHub transport.

## User authorization and installation discovery

The Manifest now registers the board URL as an OAuth callback. Native authenticated
POST `/board/{uid}/settings/apps/github/authorization` takes a current-owner
`connection_uid`; POST `/authorization/complete` takes `{state, code}` and the
HttpOnly path-scoped session cookie. State is bound to actor, board, Connection
revision and a PKCE S256 verifier for ten minutes, with atomic one-time claiming.
The fixed GitHub token endpoint exchanges the code, then `/user` and
`/user/installations` identify the GitHub user and visible installations for this
App. Discovery is bounded to 100 installations with `has_more` explicitly returned.
The user access token is neither stored nor returned; its revoke must succeed.
Current host authority and Connection identity are checked again after external IO.

Completion issues an opaque five-minute installation proof only after token
revocation and current host checks. Its server-side cache record binds actor,
board, Connection revision and each non-suspended installation/account pair.
Repository additions require this proof before GitHub IO and check it again with
the locked current Connection before persistence. Missing, expired, mismatched or
suspended proof rejects without changes. Removal alone does not require a proof,
so a board owner can deselect resources after external access disappears.

The proof is a bounded snapshot of GitHub user visibility, not a continuous user
revocation feed or permission to activate a Binding. GitHub App repository access
is independently revalidated for every addition. User access revocation after
proof issuance may remain unobserved for up to five minutes. UI integration,
continuation for more than 100 installations, lifecycle handling and live GitHub
authorization remain acceptance work. Older registered Apps require their callback URL updated.

Official user flow:
https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app

## Board Apps onboarding UI

The existing settings App Store mounts the GitHub panel. Manifest registration
uses the official external POST form; return and OAuth callbacks target the board
settings route. The panel removes one-time code/state from the URL before exchange
and never retries an ambiguous exchange automatically. Current-tab onboarding
metadata is scoped to host user and board in sessionStorage; secrets and proofs
are not persisted there. OAuth results show account installation choices, bounded
repository paging and revision-checked selection deltas. Unloaded repositories
remain selected. Read-only users cannot start or exchange callbacks. Four locales
share the same onboarding controls.

Browser fixture acceptance covers 1440px/390px, callback cleanup, official form
submission, repository deltas and read-only denial with mocked native API. It is
not live OAuth acceptance. Fresh-tab Connection discovery/re-selection, automatic
installation-return processing and global Store setup availability remain pending.
