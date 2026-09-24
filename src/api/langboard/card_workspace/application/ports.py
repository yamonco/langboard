from dataclasses import dataclass
from typing import Any, Protocol
from ..domain import (
    CardDescriptionPatch,
    ChecklistProjectionItem,
)


@dataclass(frozen=True)
class CardBundleSource:
    """Native card facts consumed by the bounded application projection."""

    details: dict[str, Any]
    checklists: list[dict[str, Any]]
    attachments: list[dict[str, Any]]
    metadata: dict[str, str]
    bot_scopes: list[dict[str, Any]]
    bot_schedules: list[dict[str, Any]]


@dataclass(frozen=True)
class CommentPageSource:
    """Native comment page without provider-specific types."""

    items: list[dict[str, Any]]
    total_count: int
    next_cursor_fields: tuple[str, str] | None


@dataclass(frozen=True)
class ProjectCardPageSource:
    """Native project card page without provider-specific types."""

    items: list[dict[str, Any]]
    total_count: int
    next_cursor_fields: tuple[str, str] | None


class CardWorkspaceQueryPort(Protocol):
    """Read capabilities required by card workspace queries."""

    def get_card_bundle_source(
        self,
        project_uid: str,
        card_uid: str,
        requested_sections: frozenset[str],
    ) -> CardBundleSource | None:
        """Load bounded native facts, fetching optional sections only when requested."""

    def get_comment_page(
        self,
        card_uid: str,
        limit: int,
        before_created_at: str | None,
        before_comment_uid: str | None,
    ) -> CommentPageSource:
        """Load one newest-first comment page."""

    def get_project_identity(self, project_uid: str) -> dict[str, Any] | None:
        """Load the minimal identity of one accessible project."""

    def get_project_card_page(
        self,
        project_uid: str,
        limit: int,
        before_updated_at: str | None,
        before_card_uid: str | None,
    ) -> ProjectCardPageSource:
        """Load one bounded project-card keyset page."""

    def get_card_content_blocks(self, project_uid: str, card_uid: str) -> list[dict[str, Any]] | None:
        """Return the ordered public content blocks of a card."""

        ...

    def get_public_card_metadata(self, project_uid: str, card_uid: str) -> dict[str, str] | None:
        """Load raw card metadata after ancestry validation."""


class CardWorkspaceCommandPort(Protocol):
    """Write capabilities required by card workspace commands."""

    def provision_project(
        self,
        title: str,
        description: str | None,
        template_name: str | None,
        infer_template_prefix: bool,
    ) -> dict[str, Any]:
        """Create a project and its standard workflow."""

    def create_card_in_leftmost_column(
        self,
        project_uid: str,
        title: str,
        description: str | None,
        assign_user_uids: list[str] | None,
    ) -> dict[str, Any]:
        """Create a card in the server-selected leftmost active column."""

    def patch_card_description(
        self,
        project_uid: str,
        card_uid: str,
        patch: CardDescriptionPatch,
    ) -> str:
        """Atomically apply one revision-bound description patch."""

    def replace_card_description(
        self,
        project_uid: str,
        card_uid: str,
        description: str,
        expected_revision: str,
    ) -> str:
        """Atomically replace one revision-bound description, including an empty body."""

    def cardify_card_checkitem(
        self,
        project_uid: str,
        card_uid: str,
        checkitem_uid: str,
        project_column_uid: str,
    ) -> dict[str, Any]:
        """Create a card from one existing checkitem."""

    def replace_card_people_and_labels(
        self,
        project_uid: str,
        card_uid: str,
        assign_user_uids: list[str] | None,
        label_uids: list[str] | None,
    ) -> dict[str, Any]:
        """Validate complete replacement sets before mutating."""

    def replace_card_relationships(
        self,
        project_uid: str,
        card_uid: str,
        is_parent: bool,
        relationships: list[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        """Validate all relationship edges before replacing them."""

    def reconcile_card_checklist_projection(
        self,
        project_uid: str,
        card_uid: str,
        projection_key: str,
        title: str,
        items: list[ChecklistProjectionItem],
        expected_receipt: str | None,
    ) -> dict[str, Any]:
        """Converge one caller-owned checklist and persist its receipt last."""
