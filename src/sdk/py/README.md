# Langboard Python SDK

A standalone package with no runtime dependencies on Langboard server internals,
ChatGPT, a company identity provider, or a database. Native Langboard remains the
owner of validation, current authorization, transactions, and durable receipts.

```python
from fastmcp import Client  # Your chosen MCP implementation; not an SDK dependency.
from langboard_sdk import LangboardClient, McpTransport

async with Client("https://your-board.example/api/mcp/oauth/stream", auth="oauth") as session:
    board = LangboardClient(McpTransport(session))
    preview = await board.preview_work_plan(plan)
    # Display/review the plan and obtain the user's intended authorization.
    result = await board.apply_work_plan(plan, preview["revision"], stable_request_id)
```

Any transport with `async call(name, arguments, *, mutation=False)` can be used.
A host adapter may provide token exchange or confirmation, but cannot supply a
principal override or bypass the server's stored roles. SDK calls never combine
multiple mutation commands, mint a revision, or retry an ambiguous write.

Keep the exact reviewed plan, returned revision, and request ID together. A lost
response requires reading current state; only the same request may be replayed.
A changed plan requires a new preview. Work-plan handling supports the existing
native server contract; this initial package does not claim to cover every API.
Server extension registration and optional integration loading are separate work.

Build independently: `uv build --out-dir dist ./src/sdk/py` from the server repository.

## Verified CI distribution

The `Check Python SDK` workflow preserves the wheel and source archive for 30 days
as `langboard-python-sdk-<workflow source SHA>`. `provenance.json` records that
exact source SHA and each distribution's SHA-256. A separate consumer job downloads
the artifact, checks those hashes, and installs the wheel without a source checkout
or package index. This tests package consumption independently of the server.

Download a successful, reviewed run with GitHub CLI:

```sh
gh run download <run-id> --repo <owner>/<repository> --name langboard-python-sdk-<source-sha> --dir sdk-dist
python -m pip install --no-index --no-deps sdk-dist/langboard_sdk-0.1.0-py3-none-any.whl
```

Check `provenance.json` against the reviewed run SHA before installing. Access to
GitHub artifacts follows repository permissions; no credential is included in the
SDK. Artifacts expire and are a review/distribution path, not a permanent package
index or an automatic production dependency. Production consumers must retain
and pin the reviewed wheel digest in their chosen package repository or build
input. No company registry, identity, or deployment URL is built into this package.
