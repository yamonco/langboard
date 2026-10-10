# Archived cards

Archived cards remain authoritative Langboard records. The board read path returns active cards and only the recent
archive window configured by `archive_visible_days`; older archive records are available through the bounded
`GET /board/{project_uid}/cards/archive` endpoint. This prevents an old archive from increasing the initial board
payload, related-record queries, or per-card socket subscriptions without weakening project authorization.

The archive endpoint is read-only, project-role protected, newest-archive-first, cursor paginated, and optionally
searches card titles. Restoring, editing, and deleting cards continue to use the existing card commands, so there is
one lifecycle and one source of truth.
