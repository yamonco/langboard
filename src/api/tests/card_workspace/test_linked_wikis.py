import os
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.card_workspace.infrastructure.linked_wikis import change_link, visible_linked_wikis  # noqa: E402
from langboard.mcp_tools import CardMcp  # noqa: E402
from langboard_shared.core.storage import FileModel  # noqa: E402
from langboard_shared.domain.models import CardAttachment, User  # noqa: E402


def test_linked_wiki_read_filters_foreign_and_private_wikis() -> None:
    project = SimpleNamespace(id=1)
    card = SimpleNamespace()
    wikis = {
        "public": SimpleNamespace(project_id=1, is_public=True, title="Public", get_uid=lambda: "public"),
        "private": SimpleNamespace(project_id=1, is_public=False, title="Private", get_uid=lambda: "private"),
        "foreign": SimpleNamespace(project_id=2, is_public=True, title="Foreign", get_uid=lambda: "foreign"),
    }
    user = User(firstname="A", lastname="B", email="a@example.test", password="unused")
    metadata = SimpleNamespace(
        get_all_as_api=lambda *_args, **_kwargs: {
            "linked_wiki:public": "1",
            "linked_wiki:private": "1",
            "linked_wiki:foreign": "1",
        }
    )
    project_wiki = SimpleNamespace(
        get_by_id_like=lambda uid: wikis.get(uid),
        is_assigned=lambda _user, wiki: wiki.is_public,
    )
    service = SimpleNamespace(metadata=metadata, project_wiki=project_wiki)

    assert visible_linked_wikis(project, card, user, service) == [{"wiki_uid": "public", "title": "Public"}]


def test_link_rejects_foreign_wiki_before_save() -> None:
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(is_linked_resource=False)
    save = Mock()
    wiki = SimpleNamespace(project_id=2)
    service = SimpleNamespace(
        project_wiki=SimpleNamespace(get_by_id_like=lambda _uid: wiki),
        metadata=SimpleNamespace(save=save),
    )

    with pytest.raises(ValueError, match="not found in project"):
        change_link(project, card, "foreign", "link", object(), service)
    save.assert_not_called()


def test_create_wiki_from_card_keeps_attachment_as_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    project = SimpleNamespace(id=1)
    card = SimpleNamespace(title="Topic", description=SimpleNamespace(content="Body"), is_linked_resource=False)
    wiki = SimpleNamespace(get_uid=lambda: "wiki", title="Topic")
    create = Mock(return_value=(wiki, {}))
    archive = Mock()
    attachment = CardAttachment(
        id=3,
        user_id=1,
        card_id=2,
        filename="report.pdf",
        file=FileModel(
            storage_type="local",
            storage_name="card_attachments",
            original_filename="report.pdf",
            filename="stored-report.pdf",
            path="/file/stored-report.pdf",
        ),
    )
    monkeypatch.setattr(CardMcp, "_require_task_card", lambda *_args: (project, card))
    monkeypatch.setattr(CardMcp, "change_link", lambda *_args: [{"wiki_uid": "wiki", "title": "Topic"}])
    service = SimpleNamespace(
        project=SimpleNamespace(get_user_role_actions_by_project=lambda *_args: ["*"]),
        checklist=SimpleNamespace(get_api_list_by_card=lambda _card: []),
        card_attachment=SimpleNamespace(get_api_list_by_card=lambda _card: [attachment.api_response()]),
        project_wiki=SimpleNamespace(create=create),
        card=SimpleNamespace(archive=archive),
    )

    result = CardMcp.create_wiki_from_card("project", "card", object(), service)
    content = create.call_args.args[3].content
    assert "Body" in content and f"report.pdf (attachment_uid: {attachment.get_uid()})" in content
    assert "/file/stored-report.pdf" not in content
    assert result["linked"] is True and result["card_archived"] is False
    archive.assert_not_called()
