"""Side-effect-free, revision-bound wiki reading."""

from typing import Any
from ...domain import WikiRepository, content_page


def read_wiki(
    repository: WikiRepository, project_uid: str, wiki_uid: str, cursor: str | None, limit: int
) -> dict[str, Any]:
    """Recheck access for every page and bind continuation to one exact revision."""
    return content_page(repository.snapshot(project_uid, wiki_uid), f"{project_uid}/{wiki_uid}", cursor, limit)
