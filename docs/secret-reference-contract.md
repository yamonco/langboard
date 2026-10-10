# Secret references and trusted storage

## Supplied credential storage

The existing host `KeyVault.store_secret(opaque_id, value)` accepts nonempty
credential text. It returns an **internal locator**, never a public Secret URI.
Only trusted host code may store and resolve material; no MCP tool exposes these
operations. `get_key(locator)` uses the existing provider boundary.

- OpenBao and HashiCorp Vault use the existing KV payload and mount. Imported
  credentials are not copied to development files by the OpenBao adapter.
- Local development writes files with mode 0600 and atomic replacement. IDs are
  bounded opaque filenames; traversal is rejected. This remains a development
  provider, not a production fallback.
- AWS KMS and Azure wrap a short random key. The existing authenticated Encryptor
  encrypts credential text, avoiding direct RSA/KMS plaintext length limits for
  private keys. A versioned envelope is the internal locator. Legacy API-key
  ciphertext locators remain readable; their creation semantics are unchanged.
- Provider failures propagate. Unknown optional provider SDKs do not silently
  fall back in production. KMS deletion is still a no-op: future reference
  revocation must deny access in host storage and must not claim cryptographic
  erasure of copied ciphertext.

Internal locators must be persisted only in host storage excluded from API,
model, wiki and MCP projections. Storage primitives alone do not authorize a
caller or create a logical reference. Existing API-key creation return values
are preserved for compatibility.

## Remaining logical reference contract

Public references such as `secret://me/github/token` and
`secret://project/<board>/openai` must identify a host-owned stable record rather
than reveal a vault path or encrypted locator. Personal, project and workspace
scope authority must be re-evaluated from current host state on every trusted
resolution. Model-facing reads return URI and metadata only.

Stable IDs/aliases, rename and scope moves, dangling-reference status, audit
source linkage, provider selection/migration and host authorization remain to be
implemented before GitHub installation stores or consumes these references.
No connection onboarding route should accept a client-supplied internal locator.

## Persisted logical references

`SecretReferenceService` is available through the existing `DomainService` factory
for trusted host callers. `create` returns metadata only; a `SecretStr` is required
for credential input. Provider locators are excluded from model dumps and repr.
Records retain a canonical `secret://ref/<uid>` URI through rename and scope move.
Named lookup forms are `secret://me/<name>`, `secret://project/<board-uid>/<name>`
and `secret://workspace/<organization-uid>/<name>`. Display names are never used
to infer an identity; named aliases reflect the current name/scope and may become
dangling after changes. Consumers should retain the canonical URI.

Every metadata or runtime read rechecks the current active user in the primary
database. Personal references belong only to their user; project credentials
require existing project update authority, including current membership and role;
workspace credentials use the existing active Organization owner boundary.
Project scope checks lock current board authority and are independent of app-use
policy. Disabling apps cannot prevent native Secret maintenance or revocation;
app consumers must still apply their own policy before using a reference.
Workspace member/delegation policy is not introduced by this unit. Moves require
both source and destination authority. Rename, move and revoke use locked rows
and an expected integer revision. Runtime resolution returns `SecretStr` only to
the trusted caller, with no HTTP/MCP value endpoint.

Revoked, missing, unauthorized, dangling-storage and mismatched-provider references
cannot resolve. Changing the selected provider fails closed rather than treating
an old locator as a path in the new provider. Duplicate-record failure rolls back
the database transaction and removes the newly written KV/local value. KMS may
retain ciphertext semantics as documented above. The migration refuses populated
downgrade. No production migration has been applied.

Dedicated wiki secretization and copy UX, richer dangling status,
model-facing API/MCP/CLI/wiki metadata integration and GitHub onboarding consumers
remain pending. The earlier remaining-contract section describes those end-state
requirements; scope/URI/rename/move primitives are now implemented as above.

## Successful operation audit

The host service writes `SecretReferenceAudit` in the same database transaction
as successful create, trusted resolution, rename, move and revoke operations.
Each fact records the actor, stable reference ID, action, current scope/revision
and optional host source kind/identifier. There is no free-form payload, credential,
locator or provider column. Source kinds are bounded and identifiers reject URLs
and arbitrary text. Host adapters construct `SecretAuditSource`; client-provided
source text must not be trusted as identity or provenance.

Audit insert failure prevents a successful operation. Failed credential creation
rolls back its reference and removes the new KV/local storage value. Successful
resolution does not return material before its audit insert succeeds. These are
transactional host facts, not an independent tamper-proof ledger: a surrounding
transaction rollback also rolls back its audit. Denied/failed request auditing,
retention/export, admin audit UI and external runtime consumer source binding
remain pending. No public audit or secret-value endpoint is added.

## Native metadata transports

Authenticated metadata and history responses use `Cache-Control: no-store` so
clients and intermediaries do not retain a projection after authority changes.

Authenticated native clients can read one canonical reference with
`GET /secret-references/<uid>`. The endpoint returns `{reference: metadata}` and
rechecks current host scope authority. Missing and unauthorized references are
reported uniformly as not found. It never calls the vault backend.

The native MCP command `get_secret_reference_metadata(uri)` accepts canonical or
named logical URIs. Its schema contains only the bounded URI; authenticated
actor and host service are injected by the existing MCP wrapper. It is annotated
read-only and returns the same metadata projection. No create, rotate, resolve or
credential-value command is registered. Standalone SDK and CLI clients can use
the existing authenticated HTTP/MCP transports without a plugin dependency.

Wiki documents may retain canonical URI text as a non-secret reference. Dedicated
wiki reference rendering, CLI convenience UX, and real GitHub provider consumers
remain pending; storing URI text does not imply that those integrations execute.

## Credential rotation

Trusted `rotate(actor, uri, SecretStr, expected_revision)` preserves the stable
reference URI and name/scope. It locks the reference, rechecks current authority,
rejects revoked references and mismatched providers, writes fresh opaque storage,
updates the locator/revision and records a `rotated` audit fact atomically.
Stale revision or audit failure preserves the old reference/material. The old
locator is retired only after the database commit. Cleanup failure preserves a
valid new reference but leaves an old-material cleanup obligation; KMS deletion
retains the previously documented limitations.

Create and rotate must own their database transaction. They reject calls within
an outer host atomic transaction before any vault effect, so a later outer rollback
cannot orphan an untracked successful storage write. Rotation scheduling, cleanup
retry jobs and an HTTP/MCP credential write interface remain outside this contract.
Provider installation adapters must call these trusted units with the returned
reference URI rather than embedding values in a board.

## Trusted provider migration

`migrate_provider(actor, uri, expected_revision, source_provider)` is a host-only
operation. The operator supplies an already authenticated old `VaultProvider`
instance; the destination is the configured `KeyVault.provider`. It does not take
provider addresses, credentials, arbitrary locators or plaintext from clients and
is not registered as an HTTP/MCP command.

The service owns its transaction, locks the reference, rechecks current scope
permission and rejects revoked, stale or mismatched source-provider references
before reading storage. It writes a new opaque locator and verifies destination
readback before changing the private provider/locator. The reference URI,
name and scope remain stable; the revision advances once and a `migrated` event
records the actor, request ID, before/after revision and `provider_migrated` reason.
History contains no value, locator or provider configuration.

Write/readback/audit failure rolls back the reference and removes the new
uncommitted destination. Old material is retired only after database commit.
Retirement failure leaves a valid destination and an explicit old-storage cleanup
obligation; KMS cannot promise physical deletion of historical ciphertext.
The caller must arrange cleanup retry; no background migration or automatic
provider change is introduced. New audit facts prevent a destructive schema
downgrade. Actual production provider migration has not been performed.
