# Native comment actions

Agent/Core and native OAuth expose `change_card_comment` with a discriminated
`change.action`: add, edit, delete or react. Each action accepts only its fields.
Text and UIDs reject blanks; reaction names use the existing server enum.

The facade dispatches through the canonical authorized command wrapper, retaining
project/card/comment validation, edit/delete ownership and actor/service injection.
Outputs reuse typed native comment, deletion and reaction contracts. Output
validation happens after execution; malformed output must not imply rollback.

Reactions retain their existing toggle semantics. They do not create a separate
acknowledgement state, approve a workflow, assign work or complete checklists.
After timeout or uncertain mutation failure, read the card before retrying.
Existing primitive names and schemas remain available for compatibility.

This slice absorbs the plugin action contract. It does not switch existing
plugin routing or establish external native OAuth parity.
