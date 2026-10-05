# Native capability diagnostics

`diagnose_connection` supports native OAuth without a legacy ToolGroup. It evaluates registered user-compatible tools against the current domain roles. Bot-only tools are excluded. Legacy API-key sessions still require an active ToolGroup and are limited to its grants.

For scoped tools, missing project/card identifiers produce `unknown_project_scope` or `unknown_card_scope`; a missing scope never implies permission. The caller should supply both identifiers for concrete card decisions.

Native OAuth results classify `update_card` and `change_card_checklist` as `action_dependent` and provide an `actions` map evaluated from each canonical command's role metadata. For example, the card envelope's Read permission does not imply Delete permission. An unavailable command is reported as `unavailable`.

This is a read-only permission snapshot, not a reservation or mutation authorization. Call-time ACL, current identity, card ancestry, revisions, destination validity and lifecycle preconditions remain enforced by commands. `schema_runtime.source=registered_metadata` identifies the inspected source; it does not prove an external connector's catalog or deployed parity. The existing legacy input/output contract is preserved.
