"""Revision-guarded wiki append commands."""

from ...domain import WikiRepository, WikiSnapshot, append_content, replace_all_content, replace_content


def append_wiki(
    repository: WikiRepository, project_uid: str, wiki_uid: str, expected_revision: str, text: str
) -> dict[str, str]:
    """Append only after concurrency validation, then return the saved-content revision."""
    before = repository.snapshot(project_uid, wiki_uid)
    after = append_content(before, expected_revision, text)
    repository.append(project_uid, wiki_uid, before.content, after)
    return {"wiki_uid": wiki_uid, "revision": WikiSnapshot(wiki_uid, before.title, after).revision}


def patch_wiki(
    repository: WikiRepository,
    project_uid: str,
    wiki_uid: str,
    expected_revision: str,
    edits: list[tuple[str, str]],
) -> dict[str, str]:
    """Persist one reviewed multi-hunk edit as a single application command."""

    before = repository.snapshot(project_uid, wiki_uid)
    after = replace_content(before, expected_revision, edits)
    repository.replace(project_uid, wiki_uid, before.content, after)
    return {"wiki_uid": wiki_uid, "revision": WikiSnapshot(wiki_uid, before.title, after).revision}


def replace_wiki(
    repository: WikiRepository,
    project_uid: str,
    wiki_uid: str,
    expected_revision: str,
    content: str,
) -> dict[str, str]:
    """Persist one reviewed whole-document replacement as a single command."""

    before = repository.snapshot(project_uid, wiki_uid)
    after = replace_all_content(before, expected_revision, content)
    repository.replace(project_uid, wiki_uid, before.content, after)
    return {"wiki_uid": wiki_uid, "revision": WikiSnapshot(wiki_uid, before.title, after).revision}


def delete_wiki(
    repository: WikiRepository, project_uid: str, wiki_uid: str, expected_revision: str
) -> dict[str, bool]:
    """Delete one exact reviewed wiki without title-based guessing."""

    before = repository.snapshot(project_uid, wiki_uid)
    if before.revision != expected_revision:
        raise ValueError("Wiki changed after review; read it again before deleting")
    repository.delete(project_uid, wiki_uid, before.content)
    return {"deleted": True}
