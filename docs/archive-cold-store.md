# Archive cold-store boundary

Archived cards remain authoritative Langboard records. The board read path returns active cards and only the recent
archive window configured by `archive_visible_days`; older archive records are available through the bounded
`GET /board/{project_uid}/cards/archive` endpoint. This prevents an old archive from increasing the initial board
payload, related-record queries, or per-card socket subscriptions without weakening project authorization.

The archive endpoint is read-only, project-role protected, newest-archive-first, cursor paginated, and optionally
searches card titles. Restoring, editing, and deleting cards continue to use the existing card commands, so there is
one lifecycle and one source of truth.

## Optional memory index

An external memory engine may be added later as an opt-in derived index. It must not become the card store or an
authorization authority. A safe adapter has these properties:

- disabled by default, with no client initialization or health dependency while disabled;
- one isolated memory bank per project and authorization in Langboard before every recall;
- stable card UID as the external document ID, so retries replace rather than duplicate derived memory;
- asynchronous archive, archived-card-update, relationship-change, restore, and delete events through an outbox;
- relationship pointers only for active related cards, never copied active-card content;
- live re-read of the Langboard card and current relationships before returning an answer;
- restore invalidates or removes the derived document, and card deletion removes it;
- endpoint and credentials remain server-side, with bounded retries and observable degraded state.

Hindsight's document upsert/delete and isolated memory-bank APIs satisfy the mechanical indexing requirements, but
its extracted facts are probabilistic. It is therefore suitable only for optional discovery and must never replace
the cold archive endpoint, exact card reads, or Langboard permission checks.
