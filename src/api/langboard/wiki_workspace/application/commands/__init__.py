"""Revision-guarded wiki append commands."""

from ...domain import WikiRepository, WikiSnapshot, append_content


def append_wiki(
    repository: WikiRepository, project_uid: str, wiki_uid: str, expected_revision: str, text: str
) -> dict[str, str]:
    """Append only after concurrency validation, then return the saved-content revision."""
    before = repository.snapshot(project_uid, wiki_uid)
    after = append_content(before, expected_revision, text)
    repository.append(project_uid, wiki_uid, before.content, after)
    return {"wiki_uid": wiki_uid, "revision": WikiSnapshot(wiki_uid, before.title, after).revision}
