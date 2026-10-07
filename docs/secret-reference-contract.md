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

Audit source linkage, provider migration/rotation tooling, richer dangling status,
model-facing API/MCP/CLI/wiki metadata integration and GitHub onboarding consumers
remain pending. The earlier remaining-contract section describes those end-state
requirements; scope/URI/rename/move primitives are now implemented as above.
