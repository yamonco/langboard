# Common card work state, phase one

`CardService.get_work_states` is the shared read projection for board cards,
card details, dashboard/My Work, assigned-work pages and MCP bundles/list pages.
The existing authorized card query supplies IDs; projection queries do not
discover additional cards or reveal related-card data. A batch uses one column
query, one grouped checkitem query and one latest-verification query, including
archived cards for diagnostics.

This is a partial contract. Clients must preserve nullable axes and must never
turn `active_queue_eligible: null` into `true`. It deliberately does not replace
existing queues or their selection policy yet.

| Field | Current evidence | Meaning |
| --- | --- | --- |
| workflow_stage | ProjectColumn.workflow_stage | Explicit mapping only; unconfigured is null regardless of display name |
| verification_state | User checkitem progress plus append-only reviewer record | all checked alone is never verified; explicit current evidence may yield verified; linked Wiki is not_required |
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

- Independent required-acceptance and release-gate policy. The new record's
  card change cursor invalidates ordinary edits; external source and permission
  revocation still need their own invalidation contract. Legacy orchestration
  `passed` metadata has no evidence revision and cannot promote verification.
- Authoritative agent execution lifecycle, failure and freshness.
- Dependency/approval/input gate evaluation with permission-safe reasons.
- Explicit meeting/material classification and unmapped-column administration.
- UI consumers and live socket invalidation; typed storage alone is not full
  live UI adoption. Preserve server projection rather than recalculating from
  column labels or checkbox counts.
- Actionable queues and atomic actions after those contracts are complete.

No database migration or task mutation was introduced in phase one.

## Reviewer evidence (second phase)

Verification now has a separate append-only `card_verification_record` table.
Generic card metadata, including old orchestration `passed`, cannot become a
trusted record. The authenticated native `verification-evidence` write requires
`CardUpdate`, the card's current `last_change_seq`, the expected previous
record UID, an explicit reviewer decision, and at least one reference with
source revision and environment. `verified` requires a card-level reference
and one for each explicitly declared required checkitem; those items must be
currently checked and belong to the card. The server locks the card and appends
the reviewer identity itself. It does not move the card or approve a release.

A later card change makes that record `stale`. This cursor intentionally also
invalidates on comments; false-positive re-review is safer than treating old
evidence as current. `verified` describes the reviewer's declared evidence
scope, not acceptance-policy completeness across every card or release-gate
approval. Those policies and agent/dependency gates still need authoritative
native contracts before `active_queue_eligible` can become `true`. The
read projection does not grant access to linked resources or other cards.
