# Native MCP profiles

The compatibility transport remains `/mcp/stream` with all 118 existing tool
contracts. Two additional transports reuse the same registered domain wrappers:

- `/mcp/agent/stream`: 30 canonical work, project, card, wiki, people, notification
  and media entry points.
- `/mcp/raw/stream`: `search_raw_tools` and `call_raw_tool` discover and invoke
  the remaining primitive and compatibility actions on demand. FastMCP's
  `RegexSearchTransform` returns at most five full tool schemas per search.

`create_native_domain_provider` adapts the existing registry. Compatibility,
Agent/Core and Raw providers compose that adapter with FastMCP's native
`Visibility` transform. They do not copy domain commands, rename tools, infer
authorization from a profile, or change existing group grants.

Both new transports retain `McpAuthMiddleware`, `ToolGroupMiddleware`, current
board/card role validation, transport host checks, strict arguments and masked
errors. Profile visibility and authorization are independent restrictions.
The underlying Agent/Core and Raw schemas equal the compatibility catalog.
Raw discovery exposes only the two synthetic tools initially. Those tools
require an active validated ToolGroup; search results are filtered by its
current grants. The proxy rechecks the current discoverable catalog and then
invokes the target through normal middleware and domain authorization. Revoked
grants are not cached between search and execution. Core tools and recursive
synthetic calls cannot be invoked through the Raw proxy.

Modern profiles declare standard read-only, destructive, idempotent and
open-world hints. Reviewed query entry points are explicitly listed as reads;
names are not classified by prefixes. Unreviewed commands and the generic Raw
call proxy remain potentially destructive and non-idempotent. Open-world is
kept true because attachments and user-authored content may cross trust
boundaries. Compatibility retains its original annotations. These hints never
replace authorization, approval or mutation outcome receipts.

Modern command results include `_meta.mutation_receipt`, a typed envelope with
`request_id`, `tool`, `outcome`, `revision_conflict`, `retryable` and `next_action`.
Domain payload fields remain unchanged. Normal command completion is
`applied`; this acknowledges the command and is not workflow approval or proof
of checklist completion. Known pre-save card/wiki revision conflicts return
`not_applied` with `read_and_review`. Other failures, including a failure after
a side effect, return `unknown` with `read_resource`. No automatic retry is
authorized. Existing authorization errors remain errors. Raw invocation keeps
the target receipt and does not overwrite it with a proxy receipt.

Transport loss/cancellation can prevent any receipt from reaching a client.
Such absence is not evidence that a write failed. Durable receipt lookup,
idempotency keys and full typed command payloads remain separate work.

Modern profiles use strict Pydantic output models for 31 reviewed commands:
description patch/replace, self-assignment, notification read, project creation,
wiki creation/revision/deletion, column naming, comment reactions, content-block
movement, fixed deletion acknowledgements and message acknowledgements.
FastMCP derives their output
schemas from native return annotations; Raw search includes the same schemas.
Compatibility retains its original return annotations and schema. Validation
runs after the domain command, so a validation failure returns an unknown
mutation receipt rather than claiming a rollback. No defaults or coercion hide
missing or malformed domain fields. Remaining outputs are not yet typed.
Boolean fields reject integers and strings explicitly, including `Literal[True]`
fields that Pydantic otherwise accepts as `1` in strict mode.

Eight additional work commands declare typed nested outputs for comment
creation/editing, checklist and checkitem creation/update, work timer transitions,
and public metadata writes. Nested projections preserve omitted fields separately
from explicit nulls, bounded titles, cardified references and continuation cursors.
Native datetime objects retain their existing JSON serialization. Domain DTOs
are validated without replacing their pagination semantics. Malformed nested
output after execution still produces an unknown receipt. The 39 reviewed
command contracts do not establish coverage of all domain/query responses.

Label catalog reads and local creation, global-label reuse, and card attach/detach
also declare typed outputs. Local-first ordering, offset pagination, truncation
metadata and optional emoji/global source fields retain their domain meaning.
An existing local name match can satisfy global-label reuse without receiving
global identity or emoji fields. Output contracts never authorize creation;
the explicit local-creation instruction guard and global-creation prohibition
remain in force. Coverage is now 42 reviewed commands and one additional query.

This delivery separates existing canonical entry points. It does not yet supply
all planned action facades, atomic Work Plan handling,
OAuth profile access, deprecation telemetry or representative installed-client
parity. Do not switch a connector automatically or remove its legacy tools.
Native OAuth remains a separate opt-in delivery.
