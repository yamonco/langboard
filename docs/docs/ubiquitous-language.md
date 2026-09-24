# Ubiquitous language

This glossary is the single source of truth for Langboard's public vocabulary.
API routes, MCP tool names, Python identifiers, and documentation must use
these terms consistently. When a name in code disagrees with this page, the
code is wrong.

## Canonical vocabulary

- **Project**: The aggregate root that owns permissions, settings, columns,
  cards, and wikis. Its identifier is always `project_uid`. Every card, wiki,
  member, and execution artifact belongs to exactly one project.
- **Board**: The Kanban UI projection of a project. Existing `/board/*` REST
  routes are compatibility transport aliases for project endpoints; `board` is
  never a domain identifier. Do not introduce `board_uid`, `board_id`, or
  board-named DTO fields for project identity.
- **Card**: A work item inside a project. Identified by `card_uid`.
- **Card Bundle**: The bounded read projection of one card returned by
  `get_card_bundle`.
- **Execution Binding**: The optional project-to-external-executor binding
  stored in `project_execution_binding`.
- **Execution Generation**: The per-card counter of execution transitions,
  stored in `card_execution_generation` and used as the delivery fence.
- **Execution Receipt**: The idempotent record of an external execution
  outcome, stored in `execution_receipt`.
- **Workspace**: A genuinely separate working surface, not a synonym for
  project or board. Use the `Workspace` suffix in new module and class names
  only when the concept is a real workspace (for example, the `card_workspace`
  application slice). It must not appear as an MCP module suffix for ordinary
  project, card, wiki, or user tools.

## Naming rules

1. One identifier name per concept: a project is referenced as `project_uid`
   in REST payloads, MCP tool arguments, DTO schemas, and internal variables.
   The same ID is never exposed under two names.
2. MCP tools are named after the domain concept they act on:
   `create_project`, `get_card_bundle`, `list_project_cards`. The former
   `create_project_board` tool is now `provision_project`, because it
   provisions a project with its standard workflow columns.
3. REST `/board/*` routes stay for compatibility, but their Python handlers,
   variables, and DTO schemas speak in project terms.
4. Renames do not keep permanent compatibility wrappers. When a name changes,
   callers move to the new name in the same change.
