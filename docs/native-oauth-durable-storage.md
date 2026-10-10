# Native OAuth durable storage verification

The standard provider factory delegates storage to FastMCP's default encrypted
file store. Stable signing material derives the storage encryption key and its
isolated directory. No plugin storage engine or second OAuth protocol is added.

The subprocess regression exercises the real factory without `client_storage`
overrides. Only OIDC discovery and the upstream JWT verifier use isolated fixture
configuration; file storage, encryption, client registration, token mappings and
native access-token validation are real.

Five processes write/read/reopen the same temporary FastMCP home:
- client registration, upstream token and refresh metadata survive process exit;
- stored fixture access/refresh tokens and subject are absent in plaintext;
- a different signing key cannot retrieve or validate the original credentials;
- reopening with the original key still works;
- removing JTI mapping rejects access without losing client/upstream metadata.

This proves local durable storage restoration, not live IdP login, consent,
refresh exchange, shared-backend replica safety or recovery from storage faults.
The deployment must retain its stable key and persistent FastMCP home. Production
multi-server deployments require a shared encrypted storage backend and separate
concurrency verification per FastMCP's documented deployment guidance.

Official reference: https://gofastmcp.com/servers/auth/oauth-proxy
