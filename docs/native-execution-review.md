# Native execution review

`submit_card_execution_review` is a native MCP entry point backed by the same
transaction as `PUT /projects/{project_uid}/cards/{card_uid}/executions/{generation}/receipt`.
It requires the current stored `card_update` project role and an existing positive
execution generation. It does not claim work or mint an execution generation.

The report requires `changed`, `verified`, `remaining`, and nonempty `evidence_refs`.
Reported verification is review evidence, not an acceptance decision. The command
never changes human-authored description, checkitem completion, or verification
records. Optional machine checklist evidence retains the receipt's existing rules.

Use `langboard:{project_uid}:{card_uid}:{generation}:receipt` as the idempotency key.
Retries with identical semantic content retain the first timestamp and receipt.
Changed content or a stale generation is rejected. The receipt, machine projection,
and configured review move share one database transaction; notifications run after
commit. `moved_to_review` describes a move by this call, not the current column.

Review movement currently follows the existing explicit execution binding. Missing,
disabled, ambiguous, or inapplicable mappings save the report without moving the card.
The returned `moved_to_review=false` makes that limit visible. Native workflow-registry
movement, independent claim/start generation management, input blockers, acceptance
checks, and completion remain separate outstanding Work Actions requirements.

`get_card_execution_receipts` reads the native report history under the current stored
`read` role. Both tools are available through native MCP without the GPT plugin.
