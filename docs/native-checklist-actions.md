# Native checklist actions

Langboard exposes `change_card_checklist(project_uid, card_uid, change)` in Agent/Core and native OAuth. It absorbs the plugin's eight action shapes without replacing the existing `update_card_checklist` primitive, whose legacy title/checked-state schema remains unchanged.

| Action | Required fields | Optional fields |
| --- | --- | --- |
| create_list | title | none |
| add_item | checklist_uid, title | none |
| update_list | checklist_uid | title, is_checked; at least one |
| delete_list | checklist_uid | none |
| set_completed | checkitem_uid, is_checked | none |
| update_item | checkitem_uid | title, deadline_at, is_checked; at least one |
| delete_item | checkitem_uid | none |
| promote | checkitem_uid, project_column_uid | none |

Each change is a discriminated union. Unexpected fields, blank identifiers/titles, non-boolean completion and empty updates fail before dispatch. An empty deadline explicitly clears it. False completion values are preserved.

Canonical commands retain board/card ancestry checks, active-column validation, action permissions and actor/service injection. Promotion retains the existing canonical CardUpdate permission. After an ambiguous promotion, read the checkitem's `cardified_card` before retrying. Completion does not approve a card or automatically change its workflow.

Legacy API-key clients still need an explicit grant for the new tool. Native OAuth does not use a manually composed ToolGroup. Existing plugin routing remains until native authenticated parity is verified; there is no destructive cutover in this change.
