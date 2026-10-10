import os


os.environ.setdefault("PROJECT_NAME", "langboard")

import pytest  # noqa: E402
from langboard_shared.domain.contracts.workflow_review import (  # noqa: E402
    ReviewFinding,
    ReviewReport,
    ReviewRequest,
    ReviewSeverity,
    build_review_prompt,
    triage_review,
)


def request(**overrides) -> ReviewRequest:
    defaults = dict(
        pr_uid="pr-1",
        repository="yamonco/langboard",
        branch="feature/x",
        author="dev-1",
        title="Add pipeline",
        changed_files=("src/a.py", "src/b.py"),
    )
    defaults.update(overrides)
    return ReviewRequest(**defaults)


def finding(path: str = "src/a.py", severity: ReviewSeverity = ReviewSeverity.INFO, **overrides) -> ReviewFinding:
    defaults = dict(path=path, severity=severity, message="looks odd", line=10)
    defaults.update(overrides)
    return ReviewFinding(**defaults)


class TestReviewRequest:
    def test_requires_core_fields(self):
        with pytest.raises(ValueError):
            request(repository="")


class TestReviewFinding:
    def test_rejects_blank_path_or_message(self):
        with pytest.raises(ValueError):
            finding(path="  ")
        with pytest.raises(ValueError):
            finding(message="")

    def test_rejects_nonpositive_line(self):
        with pytest.raises(ValueError):
            finding(line=0)


class TestReviewReport:
    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            ReviewReport(pr_uid="pr-1", findings=(finding(path="../evil.py"),))

    def test_findings_for_and_blocking(self):
        report = ReviewReport(
            pr_uid="pr-1",
            findings=(
                finding(path="src/a.py", severity=ReviewSeverity.INFO),
                finding(path="src/a.py", severity=ReviewSeverity.HIGH),
                finding(path="src/b.py", severity=ReviewSeverity.WARNING),
            ),
        )
        assert len(report.findings_for("src/a.py")) == 2
        assert [f.severity for f in report.blocking()] == [ReviewSeverity.HIGH]


class TestBuildReviewPrompt:
    def test_contains_request_and_files(self):
        prompt = build_review_prompt(request(), board_context="card: fix login")
        assert "pr-1" in prompt and "yamonco/langboard" in prompt
        assert "- src/a.py" in prompt
        assert "card: fix login" in prompt

    def test_omits_empty_context(self):
        prompt = build_review_prompt(request(), board_context="   ")
        assert "Board context" not in prompt


class TestTriageReview:
    def test_blocking_findings_require_human(self):
        report = ReviewReport(pr_uid="pr-1", findings=(finding(severity=ReviewSeverity.CRITICAL),))
        decision = triage_review(report)
        assert not decision.auto_approve and decision.requires_human

    def test_small_clean_report_auto_approves(self):
        report = ReviewReport(pr_uid="pr-1", findings=(finding(),))
        decision = triage_review(report)
        assert decision.auto_approve and not decision.requires_human

    def test_large_diff_requires_human(self):
        report = ReviewReport(pr_uid="pr-1", findings=())
        decision = triage_review(report, changed_files=tuple(f"src/f{i}.py" for i in range(25)))
        assert not decision.auto_approve

    def test_finding_flood_requires_human(self):
        report = ReviewReport(pr_uid="pr-1", findings=tuple(finding(line=i) for i in range(1, 13)))
        decision = triage_review(report)
        assert not decision.auto_approve
