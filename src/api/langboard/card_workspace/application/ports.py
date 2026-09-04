from dataclasses import dataclass
from typing import Any, Protocol
from ..domain import ChecklistProjectionItem


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

    def get_public_card_metadata(self, project_uid: str, card_uid: str) -> dict[str, str] | None:
        """Load raw card metadata after ancestry validation."""


class CardWorkspaceCommandPort(Protocol):
    """Write capabilities required by card workspace commands."""

    def create_project_board(
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

    def add_card_comment(self, project_uid: str, card_uid: str, content: str) -> dict[str, Any]:
        """Create a comment."""

    def update_card_comment(self, project_uid: str, card_uid: str, comment_uid: str, content: str) -> dict[str, Any]:
        """Update an owned comment."""

    def delete_card_comment(self, project_uid: str, card_uid: str, comment_uid: str) -> None:
        """Delete an owned comment."""

    def create_card_checklist(self, project_uid: str, card_uid: str, title: str) -> dict[str, Any]:
        """Create a checklist."""

    def update_card_checklist(
        self,
        project_uid: str,
        card_uid: str,
        checklist_uid: str,
        title: str | None,
        is_checked: bool | None,
    ) -> list[dict[str, Any]]:
        """Validate and update checklist fields."""

    def delete_card_checklist(self, project_uid: str, card_uid: str, checklist_uid: str) -> None:
        """Delete a checklist."""

    def create_card_checkitem(self, project_uid: str, card_uid: str, checklist_uid: str, title: str) -> dict[str, Any]:
        """Create a checkitem."""

    def cardify_card_checkitem(
        self,
        project_uid: str,
        card_uid: str,
        checkitem_uid: str,
        project_column_uid: str,
    ) -> dict[str, Any]:
        """Create a card from one existing checkitem."""

    def update_card_checkitem(
        self,
        project_uid: str,
        card_uid: str,
        checkitem_uid: str,
        title: str | None,
        deadline_at: str | None,
        is_checked: bool | None,
    ) -> list[dict[str, Any]]:
        """Validate and update checkitem fields."""

    def delete_card_checkitem(self, project_uid: str, card_uid: str, checkitem_uid: str) -> None:
        """Delete a checkitem."""

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

    def update_card_attachment(
        self,
        project_uid: str,
        card_uid: str,
        attachment_uid: str,
        name: str | None,
        order: int | None,
    ) -> list[dict[str, Any]]:
        """Validate and update attachment metadata."""

    def delete_card_attachment(self, project_uid: str, card_uid: str, attachment_uid: str) -> None:
        """Delete a card attachment."""

    def save_public_card_metadata(
        self,
        project_uid: str,
        card_uid: str,
        key: str,
        value: str,
        old_key: str | None,
    ) -> dict[str, str]:
        """Save one public metadata entry."""

    def delete_public_card_metadata(self, project_uid: str, card_uid: str, keys: list[str]) -> None:
        """Delete public metadata entries."""

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
