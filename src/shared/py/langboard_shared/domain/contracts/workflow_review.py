"""Automated code review contracts for the AI workflow.

Assembles review prompts from a pull request plus board context,
validates structured findings, and triages the outcome into approval
or human review. The LLM call itself stays outside these contracts.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class ReviewSeverity(str, Enum):
    """Finding severity ladder."""

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def blocks_approval(self) -> bool:
        """Whether this severity forces human review."""

        return self in (ReviewSeverity.HIGH, ReviewSeverity.CRITICAL)


@dataclass(frozen=True)
class ReviewRequest:
    """The pull request under review."""

    pr_uid: str
    repository: str
    branch: str
    author: str
    title: str = ""
    changed_files: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.pr_uid or not self.repository or not self.branch or not self.author:
            raise ValueError("pr_uid, repository, branch and author are required")


@dataclass(frozen=True)
class ReviewFinding:
    """One structured issue reported by the reviewer."""

    path: str
    severity: ReviewSeverity
    message: str
    line: int | None = None

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("finding path is required")
        if not self.message.strip():
            raise ValueError("finding message is required")
        if self.line is not None and self.line < 1:
            raise ValueError("line must be positive when present")


@dataclass(frozen=True)
class ReviewReport:
    """Aggregated review outcome for triage."""

    pr_uid: str
    findings: tuple[ReviewFinding, ...]
    summary: str = ""

    def __post_init__(self) -> None:
        covered = {finding.path for finding in self.findings}
        unknown = [path for path in covered if self._is_suspicious_path(path)]
        if unknown:
            raise ValueError(f"suspicious finding paths rejected: {unknown}")

    @staticmethod
    def _is_suspicious_path(path: str) -> bool:
        return ".." in path or path.startswith("/")

    def findings_for(self, path: str) -> tuple[ReviewFinding, ...]:
        """Return findings of one file in report order."""

        return tuple(finding for finding in self.findings if finding.path == path)

    def blocking(self) -> tuple[ReviewFinding, ...]:
        """Return findings that force human review."""

        return tuple(finding for finding in self.findings if finding.severity.blocks_approval)


@dataclass(frozen=True)
class ReviewDecision:
    """Triage verdict with the reason kept auditable."""

    auto_approve: bool
    reason: str
    requires_human: bool


AUTO_APPROVE_MAX_FILES = 20
AUTO_APPROVE_MAX_FINDINGS = 10


def build_review_prompt(request: ReviewRequest, board_context: str = "") -> str:
    """Assemble the deterministic prompt skeleton for the reviewer LLM."""

    files = "\n".join(f"- {path}" for path in request.changed_files) or "- (no files listed)"
    context_block = f"\nBoard context:\n{board_context.strip()}\n" if board_context.strip() else ""
    return (
        f"Review pull request {request.pr_uid} in {request.repository} (branch {request.branch}) by {request.author}.\n"
        f"Title: {request.title or '(untitled)'}\n"
        f"Changed files:\n{files}\n"
        f"{context_block}\n"
        "Report findings as structured items with path, line (when known), severity "
        "(info|warning|high|critical) and a one-paragraph message. Do not invent paths."
    )


def triage_review(report: ReviewReport, changed_files: Sequence[str] = ()) -> ReviewDecision:
    """Decide auto-approval from blocking findings and review size."""

    blocking = report.blocking()
    if blocking:
        top = blocking[0]
        return ReviewDecision(
            auto_approve=False,
            reason=f"{len(blocking)} blocking finding(s), first: {top.severity.value} in {top.path}",
            requires_human=True,
        )
    files = len(changed_files) if changed_files else len({finding.path for finding in report.findings})
    if files > AUTO_APPROVE_MAX_FILES:
        return ReviewDecision(
            auto_approve=False,
            reason=f"{files} files under review exceeds the auto-approve limit of {AUTO_APPROVE_MAX_FILES}",
            requires_human=True,
        )
    if len(report.findings) > AUTO_APPROVE_MAX_FINDINGS:
        return ReviewDecision(
            auto_approve=False,
            reason=f"{len(report.findings)} findings exceeds the auto-approve limit of {AUTO_APPROVE_MAX_FINDINGS}",
            requires_human=True,
        )
    return ReviewDecision(
        auto_approve=True,
        reason=f"no blocking findings across {files} file(s)",
        requires_human=False,
    )
