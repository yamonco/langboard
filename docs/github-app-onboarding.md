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

The UI must POST `{state, code}` to the authenticated completion endpoint after
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

Board Apps UI form submission and return handling, authenticated installation
account/organization/each-repository API verification, multi-repository selection,
resource binding, reinstall/uninstall lifecycle and webhook processing remain
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
acceptance, installation callback state, UI account selection and selected-repository
Binding remain pending. API verification supplements the earlier Manifest flow;
it does not claim the remaining acceptance list is complete.
