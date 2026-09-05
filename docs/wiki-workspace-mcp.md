# Governed wiki and self-assignment MCP operations

These operations are generic Langboard capabilities, not a company identity provider or a ChatGPT-specific approval system.
The MCP user identity and existing project roles remain authoritative. No schema migration or search service is required.

## Public operations

| Operation | Effect and limits |
| --- | --- |
| `assign_card_to_me` | Requires CardUpdate and project membership. Adds the authenticated user only; preserves other assignees and returns `changed=false` on replay. |
| `list_project_wikis` | Requires project Read. Filters private and deleted wikis before keyset pagination or literal title/body search. At most 50 results and a 1000-character query. |
| `read_wiki_content` | Rechecks current wiki visibility for every page. Returns exact Markdown, whole-content revision and an opaque continuation cursor; at most 16000 characters per page. |
| `list_wiki_revisions` | Rechecks current visibility, returns at most 50 activity metadata records without full historical bodies. |
| `read_wiki_revision` | Reads a stored before/after body in exact pages under current access rules. Missing snapshots are errors, not reconstructed history. |
| `append_wiki_content` | Requires native wiki edit permission, an exact reviewed revision and 1–32000 nonblank characters. Preserves all prior content. |
| `create_project_wiki` | Uses existing native creation and history; the new wiki is project-visible. Title is 1–300 characters, body at most 32000. |

## Ownership and compatibility

- `wiki_workspace/domain.py` owns exact-content revisions, paging/append invariants and the repository interface. It has no transport or persistence imports.
- `wiki_workspace/application/queries` and `application/commands` separate reads from writes.
- `wiki_workspace/infrastructure.py` implements permission filtering and reads existing native history. Native `ModelColumnType` stores model JSON as a JSON string; the search query decodes that wrapper instead of searching escaped serialization. PostgreSQL and SQLite paths are covered.
- `mcp_tools/WikiWorkspaceMcp.py` exposes bounded inputs and native role checks.
- `ProjectWikiService.update(expected_content=...)` is additive. Only content can be changed in this mode. Existing callers that omit the keyword keep their original behavior.
- `ProjectWikiRepository.update_content_if_current` locks the live row, compares the exact reviewed content and updates only content/timestamp. A stale caller cannot overwrite another committed edit or an unrelated title change. Events/history run only after a successful save.
- `CardAssignedUserRepository.add_member` serializes same-card additive requests and inserts one member without a delete/replace step. `CardService.assign_self` retains native publishers and activity recording. Existing full-set assignment remains a distinct operation.

## Workflow and failure boundaries

For card knowledge capture: read source and destination, review the contribution/audience, append with the current revision,
read back, then separately archive the card. Saving a wiki never implicitly archives or deletes anything. A saved wiki followed
by an archive failure is a partial workflow outcome; do not append the contribution again. Unexpected post-save failures retain
an ambiguous outcome and must be reconciled by reading before retrying.

History uses the existing asynchronous activity recorder. Some events contain no body snapshot and recent history can lag.
Continuation cursors bind document/revision/offset; a changed document requires restarting the read rather than mixing versions.

## Executable proof

- `wiki_workspace/domain_test.py`: exact Unicode/Markdown/CRLF paging, malformed/stale cursors, append preservation and revoked read permission.
- `wiki_workspace/infrastructure_test.py`: real SQL private/deleted filtering, literal `%`/`_` search, page boundaries, native history snapshots, stale save rejection, PostgreSQL concurrent writers and unrelated-field preservation.
- `wiki_workspace/mcp_contract_test.py`: current-identity-only self-assignment, private history denial and pre-save versus post-save error distinction.
- `CardAssignedUserRepository_test.py`: other-assignee preservation, duplicate/no-op behavior, cross-project denial and PostgreSQL concurrent replay.

Run the repository tests with `PROJECT_NAME=langboard_plate_dev uv run pytest -q`.
The repository test outside the API package is also included in the companion development Tilt contract command.
For PostgreSQL proof, use a disposable local database named `langboard_wiki_test` and set
`LANGBOARD_WIKI_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:PORT/langboard_wiki_test`.
The tests create only their isolated fixture rows; never point them at an application database.
The validated PostgreSQL 17.6 image is `postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`.
Colocated test files are excluded from API/shared wheels and Docker build contexts.
