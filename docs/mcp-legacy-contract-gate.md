# MCP legacy contract gate

This is the first delivery of the MCP vNext compatibility card. It preserves the
observed legacy surface before the FastMCP GA and native OAuth migrations.
It does not implement dual-run, authenticate a client, or prove output parity.

## Evidence and boundaries

The immutable fixtures in `src/api/tests/mcp_integration/fixtures` describe source
revision `c0d86f7aab29bc190c7d2f381d340d38cb418408`. The manifest pins artifact
checksums and the native and plugin image digests.

- Native: 118 tools reconstructed in a separate process inside the deployed API
  Python environment; five ToolGroup rows read through `DbSession.use(readonly=True)`.
- Group and owner identifiers are hashed. No access tokens, OAuth state, client
  secrets, personal identifiers, or business tool results are captured.
- Plugin: the previously captured 25-tool deployed catalog uses synthetic settings
  with OAuth disabled. Discovery metadata came from the plugin pod loopback.
- Neither catalog proves authenticated discovery from the running server process.
  Plugin schemas and OAuth metadata are evidence artifacts, not yet compatibility
  comparisons against a future plugin deployment.

## Candidate checks

Run the pure standard-library tests from the repository root:

```sh
python scripts/mcp_contracts/test_legacy.py
```

In the candidate API environment, capture the registered native tool surface:

```sh
python scripts/mcp_contracts/capture_native.py --catalog-only > candidate.json
python scripts/mcp_contracts/check_legacy.py --catalog-only \
  src/api/tests/mcp_integration/fixtures/legacy-canary-20261004.json candidate.json
```

CI performs these commands against the candidate source and frozen dependencies.
It rejects missing tools, input/output schema changes, annotation changes,
registry/runtime mismatches, duplicate identities, and invalid contract digests.
New tool names are allowed. Description changes are allowed. Exact schema
comparison is deliberately conservative; an alias must retain the old contract
when a canonical implementation evolves.

For a deployed transition, omit `--catalog-only` on both commands. The capture
also reads current ToolGroup ownership, activation and grants, and the check
requires every captured group to remain identical. New groups are allowed.
Do not replace the baseline merely to silence a regression. Intentional group
configuration changes require a reviewed new capture with provenance; old evidence
remains available for rollback review.

## Remaining delivery gates

Authenticated old-client and new-client discovery, business output parity,
compatibility aliases, simultaneous E2E, deprecation telemetry and tested rollback
remain open. Native OAuth must also survive restart and refresh rotation while
enforcing current OIDC/SCIM user status, ToolGroup ownership and board permissions.
The associated OAuth design is tracked at
https://langboard.yamon.io/board/2RRwwB5JNm0/gCD2eKGGSAP.
