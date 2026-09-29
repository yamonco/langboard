# Common card work state, phase one

`CardService.get_work_states` is the shared read projection for board cards,
card details, dashboard/My Work, assigned-work pages and MCP bundles/list pages.
The existing authorized card query supplies IDs; projection queries do not
discover additional cards or reveal related-card data. A batch uses one column
query and one grouped checkitem query, including archived cards for diagnostics.

This is a partial contract. Clients must preserve nullable axes and must never
turn `active_queue_eligible: null` into `true`. It deliberately does not replace
existing queues or their selection policy yet.

| Field | Current evidence | Meaning |
| --- | --- | --- |
| workflow_stage | ProjectColumn.workflow_stage | Explicit mapping only; unconfigured is null regardless of display name |
| verification_state | User checkitem progress | unverified/partial only; all checked is not verified; linked Wiki is not_required |
| execution_state | User checkitem started/paused status | human_active/paused; absent human timers leaves agent state unknown (null) |
| blocker_state | Not integrated | null; dependency/input/approval gates cannot be assumed clear |
| material_kind | Linked Wiki or explicit reference column | wiki-like/reference/work; meeting classification remains pending |
| lifecycle | Card.archived_at | active/archived, independent of workflow |
| active_queue_eligible | Known exclusion facts | false for archive, closed/reference or linked Wiki; otherwise null until gates exist |

`reasons` and `state_inconsistency` contain code/message/source_ref. Sources
reference only the authorized card. Closed cards with open checkitems, active
cards with all checkitems checked, and archived cards with running timers are
diagnosed without changing data. These counts do not declare checkitems to be
required acceptance criteria. No assignee or timer owner data is exposed here.

## Remaining acceptance work

- Required-acceptance policy, current verification evidence/revision and stale
  invalidation. Legacy orchestration `passed` metadata has no evidence revision
  and must not promote verification to verified.
- Authoritative agent execution lifecycle, failure and freshness.
- Dependency/approval/input gate evaluation with permission-safe reasons.
- Explicit meeting/material classification and unmapped-column administration.
- UI consumers and live socket invalidation; typed storage alone is not full
  live UI adoption. Preserve server projection rather than recalculating from
  column labels or checkbox counts.
- Actionable queues and atomic actions after those contracts are complete.

No database migration or task mutation is introduced in this phase.
