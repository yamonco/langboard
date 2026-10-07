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
