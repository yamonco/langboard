# External work import contract

Langboard accepts provider-neutral JSON bundles through `import:work`. Source-specific
adapters remain outside the Langboard domain and translate legacy records into native
columns, cards, labels, checklists, relationships, comments, and attachments.

## Safety properties

- Imports require an administrator, the project owner, or a member with full project access.
- People are resolved only through an explicit SCIM issuer and external identifier, and must
  already be members of the target project. Email matching is never used.
- Every source record has durable lineage. Replaying identical input is a no-op; changing an
  imported source record is a conflict instead of an implicit overwrite.
- Relationship cycles, ambiguous existing column or label names, unsafe attachment paths,
  and attachment hash or size mismatches fail closed.
- Input is capped at 64 MiB and read in bounded chunks before validation.
- Each source record and its lineage commit together. A failed run resumes from the first
  missing record instead of holding one unbounded transaction or duplicating completed work.
- Realtime and activity effects are checkpointed after each record and retried when a run is
  resumed. Delivery is at least once if a process stops between dispatch and checkpoint.
- Attachment I/O stays outside database transactions and uses a deterministic object key.
  A retry therefore overwrites the same staged object instead of leaking another copy, while
  an observed database failure synchronously removes that exact object. If database visibility
  is itself unavailable, the importer conservatively retains that one key so it cannot delete
  an object committed by a concurrent winner; the next retry reuses it.
- Unknown fields are rejected, so source automation state, bot comments, and approval state
  cannot leak into the Langboard domain accidentally.
- Historical imports publish native realtime and activity updates, but deliberately do not
  execute bots, send mention notifications, or recreate approval workflow state.

## Adapter mapping

| External meaning | Bundle record | Native Langboard model |
| --- | --- | --- |
| Workflow stage | `columns` | project column |
| Work item | `cards` | card |
| Independent subtask | `cards` + `relationships` | child card + typed relationship |
| Simple completion item | `checklists` + `checkitems` | native checklist |
| Meaningful tag | `labels` | project label |
| Historical discussion | `comments` | comment with SCIM author and original timestamp |
| Historical file | `attachments` | attachment with SCIM author, original timestamp, filename, hash, and size |

## Invocation

```console
langboard import:work bundle.json \
  --project-uid PROJECT_UID \
  --actor-uid ACTOR_UID \
  --attachments-root ./files \
  --dry-run
```

Run once with `--dry-run`, then without it. Re-run the same command as the idempotency check;
the receipt must report every record as `unchanged` and no record as `created`.
