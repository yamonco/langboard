# Optional OIDC identity proofs

The optional `get_employee_identity_proof` MCP command preserves its legacy name
for existing clients. It proves the currently linked OIDC account identity; it
does not assert employment, grant SCIM directory access, or approve an action.
Use native SCIM employee policy commands for membership classification.

The host must explicitly configure `IDENTITY_PROOF_ISSUER`,
`IDENTITY_PROOF_AUDIENCE`, and `IDENTITY_PROOF_SIGNING_KEY_PATH`. All three default
to empty; there is no built-in organization, relying party, or signing key. The
key must be an Ed25519 PEM private key. The host supplies the key through its
secret store and grants read access to the runtime user. Public verification
keys are available at `/auth/employee-identity/jwks`; missing configuration
returns 503 without exposing key details.

The request nonce must be a canonical UUID. Proofs bind the current active user,
current OIDC identity link, source issuer and resource audience. Their lifetime
is at most 60 seconds and never exceeds the verified bearer token expiry. A
native session, bot, API key, ID token, stale identity link, or expired credential
cannot produce a proof. The relying party owns nonce matching, replay defense,
and its own authorization decision. An identity proof is not permission.

Legacy MCP HTTP/SSE transports may set `MCP_OIDC_DEFAULT_TOOL_GROUP_UID` for a
verified resource-scoped OIDC bearer. An explicit header, including an empty
header, remains authoritative. Personal group ownership, active group state,
allowed-tool selection, and current role checks still apply. Other credentials
do not inherit this optional default. Modern native OAuth continues using its
existing permission-scoped catalog and does not require legacy tool groups.

Keep organization-specific issuer/audience values and credential locations in
private deployment configuration. Existing deployments must explicitly bind the
three generic settings when replacing earlier organization-specific proof code.
