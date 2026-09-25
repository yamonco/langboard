"""Project navigator search: fast fuzzy title matching with scoring."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    """A single project search result with relevance score."""

    project_uid: str
    title: str
    score: float
    matched_field: str  # "title" | "type" | "label"


def normalize_query(query: str) -> str:
    """Normalize a search query for case-insensitive, whitespace-tolerant matching."""
    return query.strip().lower()


def score_title_match(query: str, title: str) -> float:
    """Score a title against a query.

    Exact match: 1.0
    Starts-with: 0.8
    Contains: 0.6
    Word-start match: 0.4
    Fuzzy (all chars present in order): 0.2
    No match: 0.0
    """
    q = normalize_query(query)
    t = title.lower()

    if not q:
        return 0.0

    if t == q:
        return 1.0
    if t.startswith(q):
        return 0.8
    if q in t:
        return 0.6

    # Word-start match: any word in the title starts with the query
    for word in t.split():
        if word.startswith(q):
            return 0.4

    # Fuzzy: all query chars appear in order in the title
    idx = 0
    for ch in q:
        idx = t.find(ch, idx)
        if idx == -1:
            return 0.0
        idx += 1
    return 0.2


def search_projects(
    query: str,
    projects: list[dict[str, Any]],
    limit: int = 20,
    min_score: float = 0.2,
) -> list[SearchHit]:
    """Search projects by title with fuzzy scoring.

    Returns hits sorted by score (descending), limited to `limit`.
    """
    if not query.strip():
        return []

    hits: list[SearchHit] = []
    for project in projects:
        uid = project.get("uid", "")
        title = project.get("title", "")
        score = score_title_match(query, title)

        if score >= min_score:
            hits.append(SearchHit(
                project_uid=uid,
                title=title,
                score=score,
                matched_field="title",
            ))

    hits.sort(key=lambda h: (-h.score, h.title))
    return hits[:limit]


def search_with_recents(
    query: str,
    projects: list[dict[str, Any]],
    recent_uids: list[str],
    limit: int = 20,
) -> list[SearchHit]:
    """Search projects, boosting recently-accessed ones.

    If query is empty, returns recents in their original order.
    Otherwise, applies search scoring with a recency boost (+0.1).
    """
    if not query.strip():
        # Return recents first, then others alphabetically
        recent_set = set(recent_uids)
        recents = [
            SearchHit(project_uid=uid, title=p.get("title", ""), score=1.0, matched_field="title")
            for uid in recent_uids
            for p in projects
            if p.get("uid") == uid
        ]
        non_recents = [
            SearchHit(project_uid=p.get("uid", ""), title=p.get("title", ""), score=0.5, matched_field="title")
            for p in projects
            if p.get("uid") not in recent_set
        ]
        non_recents.sort(key=lambda h: h.title)
        return (recents + non_recents)[:limit]

    recent_set = set(recent_uids)
    hits = []
    for project in projects:
        uid = project.get("uid", "")
        title = project.get("title", "")
        base_score = score_title_match(query, title)
        if base_score < 0.2:
            continue
        boost = 0.1 if uid in recent_set else 0.0
        hits.append(SearchHit(
            project_uid=uid,
            title=title,
            score=min(base_score + boost, 1.0),
            matched_field="title",
        ))

    hits.sort(key=lambda h: (-h.score, h.title))
    return hits[:limit]
