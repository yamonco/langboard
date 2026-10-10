# Governed wiki and self-assignment MCP operations

These operations are generic Langboard capabilities, not a company identity provider or a ChatGPT-specific approval system. Names follow the [ubiquitous language](docs/ubiquitous-language.md) glossary.
The authenticated MCP user and current project permissions determine access.

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

## Editing and pagination

Read the current document revision before appending content. A stale revision is
rejected so another person's edit is preserved. Appending a wiki does not archive
or delete the source card. Card archiving remains a separate action.

If a write returns an uncertain outcome, read the document before retrying to
avoid adding the same contribution twice. Wiki history may appear after a delay,
and some history entries contain metadata without a saved body snapshot.

Continuation cursors belong to a specific document revision. If the document
changes during pagination, restart the read rather than combining versions.
Self-assignment adds the current user without removing any existing assignees.
