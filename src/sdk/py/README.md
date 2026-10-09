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

## MCP errors and uncertain writes

`McpTransport` accepts an already connected FastMCP-style client whose
`call_tool(..., raise_on_error=False)` returns `is_error`, `structured_content`,
and content blocks. It does not open or close the client or manage credentials.
A server error raises `NativeCommandError`; its `command` and original `result`
retain structured details and content for the caller. The exception message does
not automatically print the returned payload. An error response is not proof
that a mutation had no effects: inspect current state before replaying it.

A client/protocol exception or missing structured receipt for a mutation raises
`MutationOutcomeUnknown`, preserving the original exception as its cause.
Read failures propagate unchanged. Neither path retries the command. Cancellation
and other Python `BaseException` signals remain under caller control.


## Card display types and app origins

After authorized native card creation, call `set_card_presentation(project_uid,
card_uid, presentation)` to attach optional display metadata. The existing native
`save_public_card_metadata` command owns permissions, storage and socket updates.
This call is separate from creation: on failure the card still exists. Read its
metadata before retrying an unknown outcome. No automatic write replay.

```python
await board.set_card_presentation(project_uid, card_uid, {
    "version": 1,
    "key": "app.github.issue",
    "axis": "origin",  # "type" is also supported; no policy axes
    "name": "GitHub issue",  # English fallback, plain text
    "description": "App-reported origin. Workflow and reviewer approval remain separate.",
    "icon": "🔗",  # optional plain text, never remote HTML or SVG
    "translations": {
        "ko-KR": {"name": "깃허브 이슈", "description": "앱에서 제공한 출처입니다. 완료·승인 상태와 별개입니다."},
    },
})
```

The common UI renderer uses exact locale, language, then English fallback.
The server limits keys to `app.<app-key>.<kind-key>`, allows only `type`/`origin`,
and rejects authorization/status fields. App-reported origins are self-declared,
not verified provider identity. Native visibility always renders independently.
`source_type`/`source_uid` remain linked-resource references; do not overwrite them
for work cards originating from apps. Lifecycle, workflow, material kind, access
and reviewer evidence retain their existing authoritative models.

Contract limits: version 1; name 80 characters; description 1000; icon 32;
at most 16 BCP-47-style locale entries; encoded payload 8192 characters.
Unknown/malformed metadata is hidden in the UI and cannot affect policy.


### Atomic app card creation

To create a card and its display trait together, include `presentation` in a
`new_cards` entry of the existing native work plan. The reviewed revision binds
the presentation too. The server stores it in the same transaction as the card,
relationships, checklists, and durable receipt; a failed metadata write rolls
back the plan. Public metadata events are emitted only after commit. Replaying
the identical request returns the receipt without duplicating cards or events.

```python
plan = {
    "project_uid": project_uid,
    "anchor_card_uid": anchor_card_uid,
    "new_cards": [{
        "client_ref": "new:external-issue",
        "title": "Investigate external issue",
        "presentation": {
            "version": 1,
            "key": "app.glitchtip.issue",
            "axis": "origin",
            "name": "GlitchTip issue",
            "description": "App-reported origin. Resolution is separate from approval.",
            "icon": "🔗",
        },
    }],
}
preview = await board.preview_work_plan(plan)
# Use the reviewed plan, returned revision, and stable request ID together.
result = await board.apply_work_plan(plan, preview["revision"], stable_request_id)
```

This uses the selected anchor's board/column and native creation permissions.
It does not connect to a provider, verify its identity, or enable automatic card
creation. Existing cards can continue to use `set_card_presentation` separately.
When `presentation` is absent, old work-plan serialized payloads stay unchanged.

## Authorized resource context

`await board.get_connection_context(project_uid, card_uid=None, cursor=None)`
reads one bounded native resource page. One board App binding can select several
resources from several connections; one external resource can be selected by
several boards through separate board-owned bindings. Keep both connection and
resource identities, plus each returned revision. Follow `resources.next_cursor`
explicitly when needed. The SDK never retrieves credentials, grants access,
registers provider code, or automatically executes a workflow transition.

Workflow mapping uses stable stage keys and current authorized column identities,
not translated names. Several columns may share a stage: the user must choose an
explicit destination. Missing, inactive or ambiguous stages disable transitions;
metadata reads remain independent. New adapters select built-in workflow types in their
host-installed manifest; app-specific stage definitions are not supported. The current SDK exposes resource discovery, not a full
provider onboarding/registration API.


## Built-in workflow types

Apps use `WorkflowStage` and `WorkflowRequirements` from `langboard_sdk`:

```python
from langboard_sdk import WorkflowRequirements, WorkflowStage

requirements = WorkflowRequirements(
    (WorkflowStage.ACTIVE, WorkflowStage.REVIEW, WorkflowStage.CLOSED),
    (WorkflowStage.READY,),
)
descriptor = requirements.to_dict()
```

These are Langboard's built-in global types, not app-owned stages. The wizard
maps these types to the board's existing columns; it never inserts app-specific
workflow definitions. SDK validation rejects unknown and duplicate types. The
host checks the current built-in registry, activation and column access before
accepting a mapping. Display names and translations remain host-owned.
