# Native employee identity proof

Tool: `get_employee_identity_proof(request_nonce: string)`. The request nonce is the canonical UUID `jti` from the independently signed Teams actor proof. It binds two assertions to one request and never grants identity or permissions by itself.

The tool is user-only and must be enabled in the authenticated user's allowed MCP tool group. Its result is `{attestation, issuer, audience, expires_at, request_nonce}`. JWT issuer is `urn:yam:langboard`; audience is `urn:yam:erp-employee-proof`; `sub` is the native Langboard user ID; `oidc_iss`, `oidc_sub`, and `oidc_aud` identify the verified bearer credential; `request_nonce` binds the actor request; `iat`, `nbf`, `exp`, and UUID `jti` bound the proof to at most 60 seconds and never beyond the source access token expiry.

Configure the existing OIDC provider with `AUTH_PROVIDER=oidc` or `hybrid`, exact `OIDC_ISSUER`, `OIDC_CLIENT_ID`, native discovery/JWKS configuration, and `OIDC_API_AUDIENCE=langboard-api`. Access tokens must use RS256, `typ=Bearer`, configured issuer/audience, and unexpired required time claims. Native signed session tokens, API keys, bot credentials, and caller-provided identity claims cannot produce this proof. Bearer authentication is enabled only at MCP authentication entrypoints.

Mount a dedicated Ed25519 PEM private key read-only and configure `EMPLOYEE_IDENTITY_SIGNING_KEY_PATH` to its absolute path. Existing dedicated identity signing material may be reused through deployment configuration; do not copy credentials into source or logs. Public JWKS route is `/auth/employee-identity/jwks` on the Langboard API origin. The route publishes only the public Ed25519 coordinate and key ID; missing/unreadable signer returns 503.

The credential's verified issuer/subject must match the existing UserIdentityLink, and the linked account must be active and undeleted. No email-based link is created by bearer authentication. Existing native OIDC login/provisioning remains responsible for account links.

ERP receives the proof through `X-Langboard-Identity-Proof` together with `X-Yam-Actor-Proof`. It validates signature, issuer, audience, freshness and request nonce, then independently resolves the current Entra and Keycloak projections to one current employee or representative. Deployment must configure the ERP native JWKS URL and CA contract; no ContextForge custom endpoint or modified image is needed.
