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
