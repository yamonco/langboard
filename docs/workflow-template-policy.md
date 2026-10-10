# Workflow references in board templates

Board templates store column names, descriptions, translations, and the immutable
`workflow_stage` key. They do not snapshot completion, active queue, overdue, or
entry-effect policies. `ProjectTemplateService.save_columns` persists this
allowlist; copying a board uses the same structural fields.

New boards bind each column to the current registry entry. Changing a registry
policy therefore changes the interpretation of existing bindings and later
template-created boards. Column guidance remains separate and is combined with
the current stage description for API/MCP readers. Renaming a column does not
change the key. Legacy string columns retain a null stage without name inference.

The structural integration regression exercises database save/readback, a
registry edit, native column creation, guidance resolution, board-to-template
copy, and another registry edit. It also supplies policy fields at the service
boundary and checks they are not persisted. Project creation, notification
effects, and unrelated automation providers are replaced in this test; it is
not evidence of a deployed browser or live PostgreSQL roundtrip.

## Compact MCP workflow context

Modern card lists and search results reference `project_column_uid` and stage keys.
Column guidance and registry policies are supplied once in the response's
`columns` and `workflow_stages` dictionaries. Card state retains completion,
verification, execution, and inconsistency codes independently. Null completion
is preserved for unmapped columns. Legacy list transport restores column names
and emits a JSON object conforming to `ProjectCardListResponse`.

The regression gate covers native adapter/query projection, list transport,
search, query-stage filtering before limits, and the native 1,000-item transition
test. That transition requires one summary event and at most three timer reads;
the fixture substitutes publishers and exercises SQLite by default. Authenticated
live list/search readback confirms the compact contract for returned cards; it
does not establish all board ACL combinations or live mass-event delivery.
