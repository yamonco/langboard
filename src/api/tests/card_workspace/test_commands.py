from typing import Any
import pytest
from langboard.card_workspace.application.commands import (
    create_card_in_leftmost_column,
    create_project_board,
    delete_public_card_metadata,
    set_card_people_and_labels,
    update_card_attachment,
)


class FakeCommandPort:
    """Small recording port used to prove application validation order."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def create_project_board(self, title: str, description: str | None) -> dict[str, Any]:
        self.calls.append(("create_project_board", (title, description)))
        return {"project": {"uid": "p1", "title": title}, "columns": []}

    def create_card_in_leftmost_column(
        self,
        project_uid: str,
        title: str,
        description: str | None,
        assign_user_uids: list[str] | None,
    ) -> dict[str, Any]:
        self.calls.append(("create_card_in_leftmost_column", (project_uid, title, description, assign_user_uids)))
        return {"card": {"uid": "c1", "title": title}, "column": {"uid": "left"}}

    def replace_card_people_and_labels(
        self,
        project_uid: str,
        card_uid: str,
        assign_user_uids: list[str] | None,
        label_uids: list[str] | None,
    ) -> dict[str, Any]:
        self.calls.append(("replace_card_people_and_labels", (project_uid, card_uid, assign_user_uids, label_uids)))
        return {"member_uids": assign_user_uids or [], "labels": []}

    def update_card_attachment(
        self,
        project_uid: str,
        card_uid: str,
        attachment_uid: str,
        name: str | None,
        order: int | None,
    ) -> list[dict[str, Any]]:
        self.calls.append(("update_card_attachment", (project_uid, card_uid, attachment_uid, name, order)))
        return [
            {
                "uid": attachment_uid,
                "name": name or "file.pdf",
                "order": order or 0,
                "storage_key": "private/object",
                "user": {"uid": "u1", "username": "safe", "email": "hidden@example.com"},
            }
        ]

    def delete_public_card_metadata(self, project_uid: str, card_uid: str, keys: list[str]) -> None:
        self.calls.append(("delete_public_card_metadata", (project_uid, card_uid, keys)))


def test_create_commands_normalize_before_calling_port() -> None:
    """The application owns input normalization while the adapter owns native mechanics."""

    port = FakeCommandPort()

    create_project_board(port, " Delivery ")
    create_card_in_leftmost_column(port, "p1", " Task ", assign_user_uids=["u1"])

    assert port.calls == [
        ("create_project_board", ("Delivery", None)),
        ("create_card_in_leftmost_column", ("p1", "Task", None, ["u1"])),
    ]


@pytest.mark.parametrize(
    ("invoke", "message"),
    [
        (lambda port: update_card_attachment(port, "p", "c", "a", " renamed ", -1), "non-negative"),
        (
            lambda port: set_card_people_and_labels(port, "p", "c", ["u1", "u1"], None),
            "duplicates",
        ),
        (
            lambda port: delete_public_card_metadata(port, "p", "c", ["api_token"]),
            "reserved or secret-like",
        ),
    ],
)
def test_invalid_multi_field_mutations_never_reach_port(invoke: Any, message: str) -> None:
    """Every supplied field is validated before any infrastructure mutation can occur."""

    port = FakeCommandPort()

    with pytest.raises(ValueError, match=message):
        invoke(port)

    assert port.calls == []


def test_attachment_mutation_response_is_bounded_and_strips_private_fields() -> None:
    """Attachment mutations never echo storage internals or user email."""

    port = FakeCommandPort()

    response = update_card_attachment(port, "p", "c", "a", "report.pdf", 2)
    item = response["attachments"].items[0]

    assert item["user"] == {"uid": "u1", "username": "safe"}
    assert "storage_key" not in item
    assert response["attachments"].limit == 25
