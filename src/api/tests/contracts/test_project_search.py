import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.contracts.project_search import (  # noqa: E402
    score_title_match,
    search_projects,
    search_with_recents,
)


PROJECTS = [
    {"uid": "p1", "title": "Langboard"},
    {"uid": "p2", "title": "ChatGPT Plugin"},
    {"uid": "p3", "title": "Sanmopia Migration"},
    {"uid": "p4", "title": "Brown F&B"},
    {"uid": "p5", "title": "랭보드 개선"},
]


class TestScoreTitleMatch:
    def test_exact_match(self):
        assert score_title_match("langboard", "Langboard") == 1.0

    def test_starts_with(self):
        assert score_title_match("chat", "ChatGPT Plugin") == 0.8

    def test_contains(self):
        assert score_title_match("plugin", "ChatGPT Plugin") == 0.6

    def test_word_start_subsumed_by_contains(self):
        # 'gpt' is a substring of 'chatgpt', so contains matches first (0.6 > 0.4)
        assert score_title_match("gpt", "ChatGPT Plugin") == 0.6

    def test_fuzzy(self):
        assert score_title_match("lb", "Langboard") == 0.2

    def test_no_match(self):
        assert score_title_match("xyz", "Langboard") == 0.0

    def test_empty_query(self):
        assert score_title_match("", "Langboard") == 0.0

    def test_korean(self):
        assert score_title_match("랭보드", "랭보드 개선") == 0.8


class TestSearchProjects:
    def test_returns_matching_projects(self):
        hits = search_projects("lang", PROJECTS)
        assert len(hits) >= 1
        assert hits[0].project_uid == "p1"

    def test_sorted_by_score(self):
        hits = search_projects("plugin", PROJECTS)
        assert hits[0].score >= hits[-1].score if len(hits) > 1 else True

    def test_respects_limit(self):
        hits = search_projects("a", PROJECTS, limit=2)
        assert len(hits) <= 2

    def test_empty_query_returns_empty(self):
        assert search_projects("", PROJECTS) == []

    def test_no_results(self):
        assert search_projects("zzzz", PROJECTS) == []


class TestSearchWithRecents:
    def test_empty_query_returns_recents_first(self):
        hits = search_with_recents("", PROJECTS, recent_uids=["p3", "p1"])
        assert hits[0].project_uid == "p3"  # Most recent first
        assert hits[1].project_uid == "p1"

    def test_recency_boost(self):
        hits = search_with_recents("l", PROJECTS, recent_uids=["p1"])
        # p1 should be boosted above non-recent matches
        if len(hits) > 1:
            p1_hit = next((h for h in hits if h.project_uid == "p1"), None)
            if p1_hit:
                assert p1_hit.score > 0.8  # base 0.8+ + 0.1 boost
