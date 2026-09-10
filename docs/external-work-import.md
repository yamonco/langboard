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
- Database records commit as one unit. Uploaded files are removed if that transaction fails.
- Unknown fields are rejected, so source automation state, bot comments, and approval state
  cannot leak into the Langboard domain accidentally.

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
