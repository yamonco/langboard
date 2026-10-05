# Native card actions

`update_card` is a built-in Langboard API/MCP command, independent of the
ChatGPT plugin. It is included in the Agent/Core profile and native OAuth
catalog. OAuth clients do not configure a ToolGroup to obtain this surface;
the authenticated user's current project roles still authorize every action.
The legacy API-key transport retains its explicit ToolGroup grants.

Pass exactly one action-specific `change`:

```json
{
  "project_uid": "project-uid",
  "card_uid": "card-uid",
  "change": { "action": "title", "title": "Reviewed title" }
}
```

| Action | Required fields | Canonical command |
| --- | --- | --- |
| `assign` | `assign_user_uids` | `set_card_people_and_labels` |
| `label` | `label_uids` | `set_card_people_and_labels` |
| `title` | `title` | `change_card_details` |
| `deadline` | `deadline_at` (empty string clears) | `change_card_details` |
| `description_replace` | `description`, `expected_revision` | `replace_card_description` |
| `move` | `column_uid`, `order` | `change_card_order_or_move_column` |
| `archive` | none | `archive_card` |
| `delete` | none | `delete_card` |
| `attachment_update` | `attachment_uid`, at least one of `name`/`order` | `update_card_attachment` |
| `attachment_delete` | `attachment_uid` | `delete_card_attachment` |
| `attachment_upload` | `filename`, `file_data_base64` | `upload_card_attachment` |

Unexpected fields are rejected before dispatch. Empty member/label lists
explicitly clear their respective sets; omitting the other set preserves it.
Labels refer to existing project labels and cannot create global or local
labels. Description replacement preserves whitespace and requires a reviewed
revision. Deletion retains the native archive/author/admin requirements.
Attachment commands retain their user-only restriction, ownership checks and
size limits. Order rejects negative numbers and booleans.

The facade calls the same authorized native command wrapper used by direct
MCP calls, including actor/service injection and cleanup. It does not duplicate
domain mutations or grant the facade's read permission to the selected write.
The modern transport retains its mutation receipt middleware. Existing
primitive names and schemas remain available for compatibility.

The REST compatibility endpoint `/mcp/tools/update_card` accepts the same
arguments and retains its existing authentication and ToolGroup policy. A
ChatGPT adapter can forward this contract rather than own action validation
and routing. Switching that deployed adapter requires native rollout and
authenticated parity evidence first.

This slice absorbs card-field/lifecycle/attachment action dispatch. Checklist,
comment, graph-plan, multimodal reading and result-link parity remain separate
native acceptance work. Native OAuth browser login and restart/refresh
verification are also required; in-process catalog tests do not prove them.
