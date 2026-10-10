# MCP legacy contract gate

This is the first delivery of the MCP vNext compatibility card. It preserves the
observed legacy surface before the FastMCP GA and native OAuth migrations.
It does not implement dual-run, authenticate a client, or prove output parity.

## Evidence and boundaries

The portable fixture contains 118 legacy native tool contracts. It includes no
organization identities, deployment endpoints, image references, group ownership
or grants. The manifest pins its checksum. Deployment-specific captures belong
in operator-managed evidence storage outside the source repository.

Source registration does not prove authenticated discovery from a running server
process, tool output parity or successful OAuth authentication.

## Candidate checks

Run the pure standard-library tests from the repository root:

```sh
python scripts/mcp_contracts/test_legacy.py
```

In the candidate API environment, capture the registered native tool surface:

```sh
python scripts/mcp_contracts/capture_native.py --catalog-only > candidate.json
python scripts/mcp_contracts/check_legacy.py --catalog-only \
  src/api/tests/mcp_integration/fixtures/legacy-native-v1.json candidate.json
```

CI performs these commands against the candidate source and frozen dependencies.
It rejects missing tools, input/output schema changes, annotation changes,
registry/runtime mismatches, duplicate identities, and invalid contract digests.
New tool names are allowed. Description changes are allowed. Exact schema
comparison is deliberately conservative; an alias must retain the old contract
when a canonical implementation evolves.

For a deployed transition, an operator may explicitly capture ToolGroups with
`capture_native.py --include-tool-groups`. Compare two external deployment captures
with `check_legacy.py` without `--catalog-only`; this preserves ownership,
activation and grants. The portable repository fixture intentionally has no
ToolGroups, so it cannot prove deployment grant preservation. New groups are
allowed. Keep these deployment captures and rollback provenance outside Git.

Do not replace a schema baseline merely to silence a regression. Intentional
changes require review and an explicit compatibility decision.

## Remaining delivery gates

Authenticated old-client and new-client discovery, business output parity,
compatibility aliases, simultaneous E2E, deprecation telemetry and tested rollback
remain open. Native OAuth must also survive restart and refresh rotation while
enforcing current OIDC/SCIM user status, ToolGroup ownership and board permissions.

## Portable OAuth and identity boundaries

FastMCP provides OAuthProxy/OIDCProxy and the `client_storage` interface. Use its
native storage support: encrypted persistent disk for a single instance, or an
operator-selected shared AsyncKeyValue backend for multiple instances. Stable
signing/encryption keys, durable storage and refresh concurrency are deployment
responsibilities; memory storage must not become a production default.

OIDC discovery URL, issuer, audience, credentials, provider authorization
parameters and SCIM provisioning policy are configuration. The core must not
hardcode a company's domains, identity provider, directory groups or employee
rules. Account selection is an optional provider configuration. Login identity,
organization membership and application authorization remain distinct. SCIM
provisioning alone does not imply employment; any employee classification requires
an explicit operator policy. Existing local users and external collaborators must
remain supported without SCIM.
