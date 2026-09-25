# Card MCP tool retirement

The Card MCP surface uses `create_card(column_uid="leftmost")` for first-column creation, `list_project_cards` for bounded project card pages, and `get_card_bundle` for card details and optional sections.

The following legacy tools are retired from `CardMcp` after their replacement became available to the Langboard plugin:

| Retired tool | Replacement |
| --- | --- |
| `create_card_in_leftmost_column` | `create_card` with `column_uid="leftmost"` |
| `get_cards` | `list_project_cards` with cursor continuation |
| `get_card` | `get_card_bundle` |
| `get_card_checklists` | `get_card_bundle` with `include=["checklists"]` |
| `get_card_attachments` | `get_card_bundle` with `include=["attachments"]` |
| `get_card_bot_scopes` | `get_card_bundle` with `include=["automation"]` |

Direct MCP callers must migrate to these bounded tools before deploying this release. REST and UI routes keep their existing contracts.
