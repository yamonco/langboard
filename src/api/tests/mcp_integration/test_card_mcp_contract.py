import importlib
import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.card_workspace.application.dtos import CardBundleDto, CardBundleResponse  # noqa: E402
from langboard.mcp_integration import McpRoleFilter, McpTool  # noqa: E402
from langboard.mcp_tools import CardMcp  # noqa: E402, F401
from langboard.routes.mcp.McpApi import serialize_mcp_result  # noqa: E402
from langboard_shared.domain.models.bases import REACTION_TYPES  # noqa: E402
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction  # noqa: E402
from langboard_shared.domain.services.factory.CardService import CardService  # noqa: E402


def test_card_partial_edit_schema_requires_only_card_identity() -> None:
    """Partial detail fields remain optional while an explicit identity is always required."""

    schema = McpTool.get_tool("change_card_details")["input_schema"]

    assert schema["required"] == ["project_uid", "card_uid"]
    assert schema["properties"]["title"]["default"] is None
    assert schema["properties"]["description"]["default"] is None
    assert schema["properties"]["deadline_at"]["default"] is None


def test_description_patch_schema_supports_atomic_multi_hunk_edits() -> None:
    """The agent contract keeps legacy edits while exposing bounded structured patches."""

    schema = McpTool.get_tool("patch_card_description")["input_schema"]

    assert schema["required"] == ["project_uid", "card_uid"]
    assert schema["properties"]["old_text"]["default"] is None
    assert schema["properties"]["edits"]["default"] is None
    assert schema["$defs"]["ExactTextReplacement"]["required"] == ["old_text", "new_text"]


def test_description_replacement_schema_requires_reviewed_revision_and_accepts_empty_content() -> None:
    """The explicit whole-body contract cannot be mistaken for an unguarded partial edit."""

    schema = McpTool.get_tool("replace_card_description")["input_schema"]

    assert schema["required"] == ["project_uid", "card_uid", "description", "expected_revision"]


def test_card_move_schema_makes_column_an_optional_destination() -> None:
    """Reordering in place requires no synthetic nullable column argument."""

    schema = McpTool.get_tool("change_card_order_or_move_column")["input_schema"]

    assert schema["required"] == ["project_uid", "card_uid", "order"]
    assert schema["properties"]["column_uid"]["default"] is None


def test_attachment_upload_requires_card_update_permission() -> None:
    """Attachment bytes cannot be written by a read-only project member."""

    _, actions, _, _ = McpRoleFilter.get_filtered(CardMcp.upload_card_attachment)

    assert actions == [ProjectRoleAction.CardUpdate.value]


def test_comment_tools_use_native_owner_without_workspace_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    comment = SimpleNamespace(api_response=lambda: {"uid": "comment", "content": "hello"})
    native = SimpleNamespace(
        create=lambda actor, project, card, body: (calls.append(("create", body.content)) or comment),
        update=lambda actor, project, card, uid, body: (calls.append(("update", body.content)) or comment),
        delete=lambda actor, project, card, uid: (calls.append(("delete", uid)) or True),
    )
    service = SimpleNamespace(card_comment=native)
    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: pytest.fail("workspace adapter used"))

    assert CardMcp.add_card_comment("project", "card", " hello ", None, service)["comment"]["uid"] == "comment"
    assert (
        CardMcp.update_card_comment("project", "card", "comment", " hello ", None, service)["comment"]["uid"]
        == "comment"
    )
    assert CardMcp.delete_card_comment("project", "card", "comment", None, service) == {"deleted": True}
    assert calls == [("create", "hello"), ("update", "hello"), ("delete", "comment")]

    with pytest.raises(ValueError, match="Comment is required"):
        CardMcp.add_card_comment("project", "card", " ", None, service)

    missing = SimpleNamespace(
        card_comment=SimpleNamespace(create=lambda *args: None, update=lambda *args: None, delete=lambda *args: False)
    )
    with pytest.raises(ValueError, match="Card not found in project"):
        CardMcp.add_card_comment("project", "card", "hello", None, missing)
    with pytest.raises(PermissionError, match="not owned"):
        CardMcp.update_card_comment("project", "card", "comment", "hello", None, missing)
    with pytest.raises(PermissionError, match="not owned"):
        CardMcp.delete_card_comment("project", "card", "comment", None, missing)


def test_public_metadata_mutations_use_native_owner_and_bounded_response(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    card = object()
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *_: (object(), card))
    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: pytest.fail("workspace adapter used"))
    service = SimpleNamespace(
        metadata=SimpleNamespace(
            save=lambda model, target, key, value, old_key: (
                calls.append(("save", (target, key, value, old_key))) or SimpleNamespace(value=value)
            ),
            delete=lambda model, target, keys: (calls.append(("delete", (target, keys))) or True),
        )
    )

    saved = CardMcp.save_public_card_metadata("project", "card", " note ", "x" * 4001, None, service)
    assert saved == {"key": "note", "value": "x" * 4000, "total_chars": 4001, "truncated": True}
    assert CardMcp.delete_public_card_metadata("project", "card", [" note "], None, service) == {"deleted": True}
    assert calls == [
        ("save", (card, "note", "x" * 4001, None)),
        ("delete", (card, ["note"])),
    ]

    for keys in (["api_token"], ["note", " note "]):
        with pytest.raises(ValueError):
            CardMcp.delete_public_card_metadata("project", "card", keys, None, service)
    with pytest.raises(ValueError, match="reserved or secret-like"):
        CardMcp.save_public_card_metadata("project", "card", "api_token", "secret", None, service)
    assert len(calls) == 2


def test_attachment_mutations_use_native_owner_and_bounded_response(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(id=2)
    attachment = SimpleNamespace(card_id=2)
    monkeypatch.setattr(CardMcp, "_get_card_in_project", lambda *_: (project, card))
    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: pytest.fail("workspace adapter used"))
    native = SimpleNamespace(
        get_by_id_like=lambda uid: attachment,
        change_name=lambda actor, p, c, item, name: (calls.append(("name", name)) or True),
        change_order=lambda p, c, item, order: (calls.append(("order", order)) or True),
        delete=lambda actor, p, c, item: (calls.append(("delete", item)) or True),
        get_api_list_by_card=lambda uid, limit: [
            {"uid": str(index), "storage_key": "private/object", "user": {"uid": "u1", "email": "hidden"}}
            for index in range(26)
        ],
    )
    service = SimpleNamespace(card_attachment=native)

    with pytest.raises(ValueError, match="non-negative"):
        CardMcp.update_card_attachment("p", "c", "a", None, service, " renamed ", -1)
    assert calls == []
    response = CardMcp.update_card_attachment("p", "c", "a", None, service, " renamed ", 2)
    assert calls == [("name", "renamed"), ("order", 2)]
    assert response["attachments"].total_count == 26
    assert len(response["attachments"].items) == 25
    assert response["attachments"].items[0]["user"] == {"uid": "u1"}
    assert "storage_key" not in response["attachments"].items[0]

    attachment.card_id = 3
    with pytest.raises(ValueError, match="Attachment not found in card"):
        CardMcp.delete_card_attachment("p", "c", "a", None, service)
    assert len(calls) == 2
    attachment.card_id = 2
    assert CardMcp.delete_card_attachment("p", "c", "a", None, service) == {"deleted": True}
    assert calls[-1] == ("delete", attachment)


def test_checklist_updates_use_native_set_state_without_workspace_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    card = SimpleNamespace(id=10)
    checklist = SimpleNamespace(id=20, card_id=10, title="Old")
    item = SimpleNamespace(checklist_id=20, title="Old item")
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *_: (object(), card))
    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: pytest.fail("workspace adapter used"))
    service = SimpleNamespace(
        checklist=SimpleNamespace(
            get_by_id_like=lambda uid: checklist,
            change_title=lambda *args: (calls.append(("checklist_title", args[-1])) or True),
            toggle_checked=lambda *args, **kwargs: (
                calls.append(("checklist_checked", kwargs["desired_checked"])) or True
            ),
            get_api_list_by_card=lambda *args, **kwargs: [{"uid": "l", "title": "New", "checkitems": []}],
        ),
        checkitem=SimpleNamespace(
            get_by_id_like=lambda uid: item,
            change_title=lambda *args: (calls.append(("checkitem_title", args[-1])) or True),
            change_deadline=lambda *args: (calls.append(("checkitem_deadline", args[-1])) or True),
            toggle_checked=lambda *args, **kwargs: (
                calls.append(("checkitem_checked", kwargs["desired_checked"])) or True
            ),
        ),
    )

    first = CardMcp.update_card_checklist("project", "card", "list", None, service, title=" New ", is_checked=True)
    second = CardMcp.update_card_checkitem(
        "project", "card", "item", None, service, title=" New item ", deadline_at="", is_checked=False
    )
    assert first["checklists"].items[0]["title"] == "New"
    assert second["checklists"].items[0]["uid"] == "l"
    assert calls == [
        ("checklist_title", "New"),
        ("checklist_checked", True),
        ("checkitem_title", "New item"),
        ("checkitem_deadline", None),
        ("checkitem_checked", False),
    ]

    for kwargs in ({}, {"title": " "}, {"is_checked": "yes"}):
        with pytest.raises(ValueError):
            CardMcp.update_card_checklist("project", "card", "list", None, service, **kwargs)
    assert len(calls) == 5


def test_checklist_create_delete_tools_use_native_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    checklist = SimpleNamespace(api_response=lambda: {"uid": "list", "title": "Tasks", "private": "hidden"})
    item = SimpleNamespace(api_response=lambda: {"uid": "item", "title": "Task", "private": "hidden"})
    service = SimpleNamespace(
        checklist=SimpleNamespace(
            create=lambda actor, project, card, title: (calls.append(("create_list", title)) or checklist),
            delete=lambda actor, project, card, uid: (calls.append(("delete_list", uid)) or True),
        ),
        checkitem=SimpleNamespace(
            create=lambda actor, project, card, uid, title: (calls.append(("create_item", title)) or item),
            delete=lambda actor, project, card, uid: (calls.append(("delete_item", uid)) or True),
        ),
    )
    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: pytest.fail("workspace adapter used"))

    created_list = CardMcp.create_card_checklist("project", "card", " Tasks ", None, service)["checklist"]
    created_item = CardMcp.create_card_checkitem("project", "card", "list", " Task ", None, service)["checkitem"]
    assert created_list["uid"] == "list" and "private" not in created_list
    assert created_item["uid"] == "item" and "private" not in created_item
    assert CardMcp.delete_card_checklist("project", "card", "list", None, service) == {"deleted": True}
    assert CardMcp.delete_card_checkitem("project", "card", "item", None, service) == {"deleted": True}
    assert calls == [
        ("create_list", "Tasks"),
        ("create_item", "Task"),
        ("delete_list", "list"),
        ("delete_item", "item"),
    ]

    with pytest.raises(ValueError, match="Checklist title is required"):
        CardMcp.create_card_checklist("project", "card", " ", None, service)
    with pytest.raises(ValueError, match="Checkitem title is required"):
        CardMcp.create_card_checkitem("project", "card", "list", " ", None, service)


@pytest.mark.parametrize("reason", ["stale revision", "missing fragment", "ambiguous fragment"])
def test_description_conflict_is_transport_validation(monkeypatch: pytest.MonkeyPatch, reason: str) -> None:
    """Only a known pre-save conflict becomes a recoverable MCP validation error."""
    from fastmcp.exceptions import ValidationError
    from langboard.card_workspace.domain import DescriptionPatchConflict

    def reject(*args: Any, **kwargs: Any) -> None:
        raise DescriptionPatchConflict(reason)

    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: object())
    monkeypatch.setattr(CardMcp, "replace_description_text", reject)
    with pytest.raises(ValidationError, match="No changes saved"):
        CardMcp.patch_card_description("project", "card", None, None, old_text="old", new_text="new")


def test_description_unexpected_failure_is_not_claimed_unsaved(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure after persistence must not be disguised as a safe conflict."""

    def fail(*args: Any, **kwargs: Any) -> None:
        raise ValueError("downstream effect failed")

    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: object())
    monkeypatch.setattr(CardMcp, "replace_description_text", fail)
    with pytest.raises(ValueError, match="downstream effect failed"):
        CardMcp.patch_card_description("project", "card", None, None, old_text="old", new_text="new")


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["stale revision", "missing fragment", "ambiguous fragment", "effect failure"])
async def test_description_conflict_through_http_route(monkeypatch: pytest.MonkeyPatch, reason: str) -> None:
    """The HTTP dispatcher preserves safe validation errors and unknown outcomes separately."""
    from fastapi import FastAPI, Request
    from fastmcp import FastMCP
    from httpx import ASGITransport, AsyncClient
    from langboard.card_workspace.domain import DescriptionPatchConflict

    route = importlib.import_module("langboard.routes.mcp.McpApi")
    closed: list[bool] = []
    group = SimpleNamespace(activated_at=True, tools=["patch_card_description"], user_id=None)
    service = SimpleNamespace(
        mcp_tool_group=SimpleNamespace(get_by_id_like=lambda _uid: group),
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(route, "DomainService", lambda: service)
    monkeypatch.setattr(route, "User", SimpleNamespace)
    monkeypatch.setattr(CardMcp, "_adapter", lambda *args: object())

    def reject(*args: Any, **kwargs: Any) -> None:
        if reason == "effect failure":
            raise ValueError("effect failure")
        raise DescriptionPatchConflict(reason)

    monkeypatch.setattr(CardMcp, "replace_description_text", reject)
    mcp = FastMCP("description-http-test")

    @mcp.tool(name="patch_card_description")
    def patch() -> Any:
        """Run the real MCP boundary without database or external effects."""
        return CardMcp.patch_card_description("project", "card", None, None, old_text="old", new_text="new")

    monkeypatch.setattr(route.McpServer, "mcp", mcp)
    app = FastAPI()

    @app.post("/mcp/tools/{tool_name}")
    async def dispatch(tool_name: str, request: Request) -> Any:
        """Inject an isolated authenticated actor before the real route dispatcher."""
        request.scope["auth"] = SimpleNamespace(id=1)
        return await route.execute_mcp_tool(tool_name, request)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.post(
            "/mcp/tools/patch_card_description",
            json={},
            headers={route.AuthSecurity.MCP_TOOL_GROUP_UID_HEADER: "test-group"},
        )
    assert response.status_code == (500 if reason == "effect failure" else 400)
    assert closed == [True]
    assert route.mcp_auth_context.get() is None


def test_card_bundle_schema_exposes_opt_in_sections() -> None:
    """Agents can request rich sections without paying for them by default."""

    schema = McpTool.get_tool("get_card_bundle")["input_schema"]

    assert schema["$defs"]["CardBundleInclude"]["enum"] == [
        "description",
        "people",
        "classification",
        "checklists",
        "comments",
        "attachments",
        "metadata",
        "automation",
        "content_blocks",
    ]
    assert schema["properties"]["include"]["default"] is None


def test_comment_reaction_schema_exposes_only_native_reactions() -> None:
    """Agents cannot invent reaction values unsupported by Langboard clients."""

    schema = McpTool.get_tool("toggle_card_comment_reaction")["input_schema"]

    assert schema["properties"]["reaction"]["enum"] == REACTION_TYPES


def test_graph_patch_schema_exposes_typed_request_local_references() -> None:
    """Clients can mix existing UIDs and request-local cards in one explicit patch."""

    schema = McpTool.get_tool("apply_card_graph_patch")["input_schema"]

    assert schema["required"] == [
        "project_uid",
        "anchor_card_uid",
        "new_cards",
        "add_edges",
        "remove_relationship_uids",
    ]
    assert schema["$defs"]["CardGraphNewCard"]["required"] == ["client_ref", "title"]
    assert schema["$defs"]["CardGraphEdge"]["required"] == [
        "parent_ref",
        "child_ref",
        "relationship_type_uid",
    ]


def test_cardify_checkitem_schema_requires_explicit_source_and_destination() -> None:
    """Agents cannot cardify an ambiguous checklist item or choose an implicit column."""

    schema = McpTool.get_tool("cardify_card_checkitem")["input_schema"]

    assert schema["required"] == [
        "project_uid",
        "card_uid",
        "checkitem_uid",
        "project_column_uid",
    ]


def test_mcp_serializer_omits_unrequested_card_sections() -> None:
    """The real MCP response path does not leak optional sections as null placeholders."""

    result = serialize_mcp_result(
        CardBundleResponse(
            card_uid="card-1",
            card=CardBundleDto(core={"uid": "card-1", "title": "Work"}, workflow={}),
        )
    )

    assert result == {
        "card_uid": "card-1",
        "card": {"core": {"uid": "card-1", "title": "Work"}, "workflow": {}},
        "continuation": None,
    }


def test_project_member_projection_omits_email_and_is_bounded() -> None:
    """Room tools receive assignable identities without the private directory."""

    service = SimpleNamespace(
        project=SimpleNamespace(
            get_by_id_like=lambda _uid: object(),
            get_api_assigned_user_list=lambda _project: [
                {
                    "uid": str(index),
                    "username": f"member-{index}",
                    "type": "user",
                    "firstname": "Given",
                    "lastname": "Family",
                    "email": "hidden@example.com",
                }
                for index in range(51)
            ],
        )
    )

    result = CardMcp.list_project_members("project", service)

    assert len(result["items"]) == 50
    assert result["truncated"] is True
    assert "email" not in str(result)
    assert result["items"][0] == {"uid": "0", "username": "member-0", "firstname": "Given", "lastname": "Family"}


def test_project_member_projection_does_not_expose_invitation_email_as_name() -> None:
    """Invitation and unknown identities cannot leak directory fields through names."""

    service = SimpleNamespace(
        project=SimpleNamespace(
            get_by_id_like=lambda _uid: object(),
            get_api_assigned_user_list=lambda _project: [
                {
                    "uid": identity_type,
                    "username": "",
                    "type": identity_type,
                    "firstname": "hidden@example.com",
                    "lastname": "Private",
                    "email": "hidden@example.com",
                }
                for identity_type in ("group_email", "unknown")
            ],
        )
    )

    result = CardMcp.list_project_members("project", service)

    assert result["items"] == [{"uid": "group_email", "username": ""}, {"uid": "unknown", "username": ""}]
    assert "hidden@example.com" not in str(result)


def test_empty_partial_edit_and_invalid_order_stop_before_service() -> None:
    """No-op and malformed multi-field writes never reach the native service."""

    calls: list[tuple[Any, ...]] = []
    service = SimpleNamespace(
        card=SimpleNamespace(
            update=lambda *args: calls.append(args),
            change_order=lambda *args: calls.append(args),
        )
    )

    with pytest.raises(ValueError, match="At least one"):
        CardMcp.change_card_details("p", "c", object(), service)
    with pytest.raises(ValueError, match="non-negative"):
        CardMcp.change_card_order_or_move_column("p", "c", -1, object(), service)

    assert calls == []


def test_native_archive_rejects_card_outside_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Native archive validates the project-card ancestry before any write."""

    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    monkeypatch.setattr(
        module.InfraHelper,
        "get_records_with_foreign_by_params",
        lambda *args: None,
    )

    assert CardService.archive(object(), object(), "project-a", "card-from-b") is None


def test_card_delete_preserves_known_authors_and_allows_role_gated_legacy_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Known authors stay protected while creator-less legacy cards rely on the outer role gate."""

    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")

    class FakeUser:
        def __init__(self, actor_id: int, *, is_admin: bool = False):
            self.id = actor_id
            self.is_admin = is_admin

    class FakeBot:
        def __init__(self, actor_id: int):
            self.id = actor_id

    monkeypatch.setattr(module, "User", FakeUser)
    monkeypatch.setattr(module, "Bot", FakeBot)
    user_card = SimpleNamespace(created_by_user_id=7, created_by_bot_id=None)
    bot_card = SimpleNamespace(created_by_user_id=None, created_by_bot_id=9)
    unknown_card = SimpleNamespace(created_by_user_id=None, created_by_bot_id=None)

    assert CardService.can_delete(FakeUser(7), user_card) is True
    assert CardService.can_delete(FakeUser(8), user_card) is False
    assert CardService.can_delete(FakeBot(9), bot_card) is True
    assert CardService.can_delete(FakeBot(10), bot_card) is False
    assert CardService.can_delete(FakeUser(7), unknown_card) is True
    assert CardService.can_delete(FakeUser(8, is_admin=True), user_card) is True
    assert CardService.can_delete(FakeUser(8, is_admin=True), unknown_card) is True


def test_card_delete_rejects_non_author_before_any_destructive_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ownership mismatch fails closed before checkitems, relationships, schedules, or the card row change."""

    from langboard_shared.core.exceptions.CardDeleteForbidden import CardDeleteForbidden

    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")

    class FakeUser:
        id = 8
        is_admin = False

    project = SimpleNamespace(id=1)
    card = SimpleNamespace(created_by_user_id=7, created_by_bot_id=None, archived_at=object())
    repository = SimpleNamespace(
        checkitem=SimpleNamespace(get_all_started_checkitem_by_card=lambda _card: pytest.fail())
    )
    service = CardService(lambda _service: pytest.fail(), lambda _name: pytest.fail(), repository)
    monkeypatch.setattr(module, "User", FakeUser)
    monkeypatch.setattr(module.InfraHelper, "get_records_with_foreign_by_params", lambda *_args: (project, card))

    with pytest.raises(CardDeleteForbidden, match="original card author or an administrator"):
        service.delete(FakeUser(), project, card)


def test_card_delete_mcp_returns_actionable_author_or_admin_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agents receive a stable cause instead of retrying or suggesting a missing project role."""

    from fastmcp.exceptions import ValidationError
    from langboard_shared.core.exceptions.CardDeleteForbidden import CardDeleteForbidden

    def reject(*_args: Any) -> None:
        raise CardDeleteForbidden("Only the original card author or an administrator can delete this card")

    service = SimpleNamespace(card=SimpleNamespace(delete=reject))
    with pytest.raises(ValidationError, match="CARD_DELETE_AUTHOR_OR_ADMIN_REQUIRED"):
        CardMcp.delete_card("project", "card", object(), service)


def test_native_move_rejects_column_from_another_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native move validates destination column ancestry before touching row order."""

    module = importlib.import_module("langboard_shared.domain.services.factory.CardService")
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(project_id=1, project_column_id=10)
    old_column = SimpleNamespace(id=10, project_id=1)
    foreign_column = SimpleNamespace(id=20, project_id=2)
    monkeypatch.setattr(
        module.InfraHelper,
        "get_records_with_foreign_by_params",
        lambda *args: (project, card),
    )
    monkeypatch.setattr(
        module.InfraHelper,
        "get_by_id_like",
        lambda model, value: old_column if value == 10 else foreign_column,
    )

    assert CardService.change_order(SimpleNamespace(), object(), project, card, 0, foreign_column) is None
