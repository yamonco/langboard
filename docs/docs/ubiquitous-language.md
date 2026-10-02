# Langboard vocabulary

These terms describe Langboard's product and public integration identifiers.

- **Project**: Contains permissions, settings, columns, cards and wikis. Public
  API and MCP requests identify a project with `project_uid`.
- **Board**: The Kanban view of a project. Existing `/board/*` REST paths refer
  to projects and use `project_uid` in their request parameters.
- **Column**: A position in a board. A column may have an explicit workflow-stage
  mapping; its displayed name alone does not determine workflow behavior.
- **Card**: A work item inside a project, identified by `card_uid`.
- **Card Bundle**: A bounded card response from `get_card_bundle`, with optional
  sections such as comments, checklists and attachments.
- **Execution Binding**: An optional connection between a project and an
  external executor.
- **Execution Generation**: The card's execution-transition counter. Consumers
  use it to reject events for an outdated executable state.
- **Execution Receipt**: A record of an external execution outcome with
  idempotency information.
- **Workspace**: A distinct working surface, rather than another name for a
  project or its board.
