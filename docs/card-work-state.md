# Card work state

Authorized card reads expose a `work_state` projection so clients can distinguish
workflow, progress, review, execution and archive state. Reading this projection
does not modify the card or grant access to another card or linked resource.

Some axes remain unknown. Preserve `null`; in particular,
`active_queue_eligible: null` does not mean the card is ready for execution.

| Field | Meaning |
| --- | --- |
| `version` | Projection format version, currently `1` |
| `workflow_stage` | Explicit column mapping with an available workflow definition; otherwise `null` |
| `completed` | Whether that workflow definition counts the card as completed; otherwise `null` |
| `active_queue_policy` | Active-queue policy of the mapped workflow definition; otherwise `null` |
| `overdue_policy` | Deadline policy of the mapped workflow definition; otherwise `null` |
| `overdue_suppressed` | Whether deadline alerts are suppressed; archived and linked-resource cards are suppressed; missing policy can leave this `null` |
| `verification_state` | `unverified`, `partial`, `verified`, `stale` or `not_required`; checked items alone do not prove review or approval |
| `verification_source_change_seq` | Card change cursor used to evaluate whether reviewer evidence is current |
| `verification` | Current reviewer evidence record, when available |
| `execution_state` | `human_active` or `paused` for checklist timers, `idle` for linked resources, otherwise `null` when no authoritative execution state is available |
| `blocker_state` | `blocked` when a known prerequisite prevents execution; otherwise `null`, which does not prove all gates are clear |
| `dependency_state` | Direct prerequisite status and permission-filtered blockers; `clear` covers dependencies only, not input or approval gates |
| `material_kind` | `work`, `reference` or `wiki-like` |
| `lifecycle` | `active` or `archived`, independent of workflow |
| `active_queue_eligible` | `false` for a known exclusion or prerequisite blocker; otherwise `null` until all required gates can be established |
| `checklist_progress` | Ordinary checkitem `total` and `completed` counts, separate from required acceptance criteria |

`reasons` and `state_inconsistency` provide `code`, `message` and `source_ref`.
They explain missing information or inconsistent states without changing data.
Inaccessible prerequisites expose no private title or card identifier. A card in
a completed workflow with unchecked items, or an archived card with a running
timer, can still be reported as inconsistent. These diagnostics do not change
assignees, timer ownership or checklist completion.

## Reviewer evidence

The authenticated `verification-evidence` API requires permission to update the
card, its current `last_change_seq`, the expected previous evidence record UID,
an explicit reviewer decision and references that identify source revision and
environment. A `verified` decision requires a card-level reference and a
reference for every explicitly declared required checkitem. Those items must
belong to the card and currently be checked. The server records reviewer identity.

A later card change, including a comment, makes prior evidence `stale`.
`verified` describes the reviewer's declared scope; it does not approve a release,
move the card, establish every acceptance policy or clear separate execution gates.
Generic card metadata cannot substitute for reviewer evidence.
