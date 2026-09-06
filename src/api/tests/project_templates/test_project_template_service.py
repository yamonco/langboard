import os
from types import SimpleNamespace
from typing import Any
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.models import ProjectTemplate  # noqa: E402
from langboard_shared.domain.models.InternalBot import InternalBotType  # noqa: E402
from langboard_shared.domain.services.factory.ProjectTemplateService import (  # noqa: E402
    SI_COLUMN_DESCRIPTIONS,
    SI_COLUMNS,
    SI_EMAIL_NOTIFICATION_POLICY,
    ProjectTemplateService,
)
from langboard_shared.helpers import InfraHelper  # noqa: E402


class TemplateRepository:
    """Small repository double for template policy tests."""

    def __init__(self) -> None:
        self.items: list[ProjectTemplate] = []

    def get_by_name(self, name: str) -> ProjectTemplate | None:
        return next((item for item in self.items if item.name == name), None)

    def get_default(self) -> ProjectTemplate | None:
        return next((item for item in self.items if item.is_default), None)

    def get_all(self) -> list[ProjectTemplate]:
        return self.items

    def insert(self, template: ProjectTemplate) -> None:
        self.items.append(template)

    def update(self, template: ProjectTemplate) -> None:
        assert template in self.items

    def replace_default(self, template: ProjectTemplate) -> None:
        for item in self.items:
            item.is_default = item is template


def _service(repository: Any, services: dict[str, Any] | None = None) -> ProjectTemplateService:
    return ProjectTemplateService(
        lambda service_type: services[service_type.name()],
        lambda name: (services or {})[name],
        repository,
    )


def test_builtin_si_is_the_initial_default_without_duplicate_archive() -> None:
    """SI owns active workflow columns while native Project owns Archive."""

    templates = TemplateRepository()
    repository = SimpleNamespace(project_template=templates)

    template = _service(repository).ensure_builtin()

    assert template.name == "SI"
    assert template.columns == ["Backlog", "Ready", "In Progress", "Review", "Done"]
    assert template.column_descriptions == SI_COLUMN_DESCRIPTIONS
    assert "Archive" not in template.columns
    assert template.is_default is True
    assert template.email_notification_policy == SI_EMAIL_NOTIFICATION_POLICY
    assert _service(repository).ensure_builtin() is template
    assert len(templates.items) == 1


def test_builtin_si_backfills_only_legacy_empty_guidance() -> None:
    """An older built-in gains guidance without rewriting a deliberate customization."""

    templates = TemplateRepository()
    legacy = ProjectTemplate(
        name="SI",
        columns=SI_COLUMNS,
        column_descriptions=[],
        email_notification_policy=SI_EMAIL_NOTIFICATION_POLICY,
        is_builtin=True,
        is_default=True,
    )
    templates.items.append(legacy)
    repository = SimpleNamespace(project_template=templates)

    assert _service(repository).ensure_builtin().column_descriptions == SI_COLUMN_DESCRIPTIONS
    legacy.column_descriptions = ["Keep custom"]
    assert _service(repository).ensure_builtin().column_descriptions == ["Keep custom"]


def test_builtin_si_name_cannot_be_claimed_by_a_project_copy() -> None:
    """A user template must never be promoted as the built-in SI default."""

    templates = TemplateRepository()
    templates.items.append(ProjectTemplate(name="SI", columns=["Custom"]))
    repository = SimpleNamespace(project_template=templates)

    try:
        _service(repository).ensure_builtin()
    except ValueError as exc:
        assert str(exc) == "SI is reserved for the built-in project template"
    else:
        raise AssertionError("Expected a reserved-name error")


def test_copy_snapshot_preserves_order_and_bot_settings_but_not_cards_or_schedules() -> None:
    """Copy captures only reusable board structure and automation hooks."""

    templates = TemplateRepository()
    project = SimpleNamespace(id=7)
    columns = [
        SimpleNamespace(id=2, name="Done", description="Accepted work", order=2, is_archive=False),
        SimpleNamespace(id=9, name="Archive", description="Archive only", order=3, is_archive=True),
        SimpleNamespace(id=1, name="Backlog", description="Uncommitted work", order=0, is_archive=False),
    ]
    bot_type = SimpleNamespace(value="project_chat")
    internal_bot = SimpleNamespace(bot_type=bot_type, get_uid=lambda: "internal-bot-uid")
    setting = SimpleNamespace(prompt="Keep it short", use_default_prompt=False)
    repository = SimpleNamespace(
        project_template=templates,
        project_column=SimpleNamespace(
            get_all_by_project=lambda _project: [(column, 0) for column in columns],
            get_bot_scopes_by_project=lambda _project: [],
        ),
        project_assigned_internal_bot=SimpleNamespace(get_all_by_project=lambda _project: [(internal_bot, setting)]),
        project_bot_scope=SimpleNamespace(get_all_by_project=lambda _project: []),
        project_email_notification=SimpleNamespace(get_with_recipients=lambda _project: (None, [])),
    )

    template = _service(repository).copy_from_project(project, "Support")

    assert template.columns == ["Backlog", "Done"]
    assert template.column_descriptions == ["Uncommitted work", "Accepted work"]
    assert template.internal_bots == [
        {
            "internal_bot_uid": "internal-bot-uid",
            "bot_type": "project_chat",
            "prompt": "Keep it short",
            "use_default_prompt": False,
        }
    ]
    assert set(template.model_fields) >= {
        "columns",
        "internal_bots",
        "project_bot_scopes",
        "column_bot_scopes",
        "email_notification_policy",
    }
    assert not hasattr(template, "cards")
    assert not hasattr(template, "schedules")


def test_template_policy_excludes_external_email_addresses() -> None:
    """Reusable workflow policy must not leak one customer's recipients into another board."""

    policy = SimpleNamespace(
        is_enabled=True,
        notify_all_members=False,
        categories=[SimpleNamespace(value="cards")],
        card_move_target_columns=["Review"],
        external_recipient_emails=["customer@example.com"],
    )
    repository = SimpleNamespace(
        project_email_notification=SimpleNamespace(get_with_recipients=lambda _project: (policy, []))
    )

    snapshot = _service(repository)._email_notification_policy_snapshot(SimpleNamespace(id=7))

    assert snapshot == {
        "is_enabled": True,
        "notify_all_members": False,
        "categories": ["cards"],
        "card_move_target_columns": ["Review"],
    }
    assert "external_recipient_emails" not in snapshot


def test_template_restores_the_exact_assigned_internal_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    """A copied template must not select an arbitrary bot of the same type."""

    exact_bot = SimpleNamespace(id=17)
    inserted: list[Any] = []
    fallback = SimpleNamespace(
        get_default_by_type=lambda _bot_type: (_ for _ in ()).throw(AssertionError("unexpected fallback"))
    )
    assigned = SimpleNamespace(
        find_with_internal_bot_by_project_and_type=lambda _project, _bot_type: None,
        insert=inserted.append,
    )
    repository = SimpleNamespace(internal_bot=fallback, project_assigned_internal_bot=assigned)
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda _model, uid: exact_bot if uid == "exact-bot" else None)

    _service(repository)._apply_internal_bots(
        SimpleNamespace(id=9),
        [
            {
                "internal_bot_uid": "exact-bot",
                "bot_type": InternalBotType.ProjectChat.value,
                "prompt": "Use this bot",
                "use_default_prompt": False,
            }
        ],
    )

    assert len(inserted) == 1
    assert inserted[0].internal_bot_id == exact_bot.id
    assert inserted[0].prompt == "Use this bot"
    assert inserted[0].use_default_prompt is False


def test_template_replaces_an_existing_bot_without_stale_writeback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bot identity and prompt settings must be persisted in one update."""

    exact_bot = SimpleNamespace(id=17)
    current_bot = SimpleNamespace(id=8)
    setting = SimpleNamespace(internal_bot_id=current_bot.id, prompt="Old", use_default_prompt=True)
    updated: list[Any] = []
    assigned = SimpleNamespace(
        find_with_internal_bot_by_project_and_type=lambda _project, _bot_type: (current_bot, setting),
        update=updated.append,
        replace_by_project=lambda *_args: (_ for _ in ()).throw(AssertionError("redundant replacement")),
    )
    repository = SimpleNamespace(
        internal_bot=SimpleNamespace(get_default_by_type=lambda _bot_type: None),
        project_assigned_internal_bot=assigned,
    )
    monkeypatch.setattr(InfraHelper, "get_by_id_like", lambda _model, _uid: exact_bot)

    _service(repository)._apply_internal_bots(
        SimpleNamespace(id=9),
        [
            {
                "internal_bot_uid": "exact-bot",
                "bot_type": InternalBotType.ProjectChat.value,
                "prompt": "New",
                "use_default_prompt": False,
            }
        ],
    )

    assert updated == [setting]
    assert setting.internal_bot_id == exact_bot.id
    assert setting.prompt == "New"
    assert setting.use_default_prompt is False


def test_si_constant_is_stable_for_command_and_ui_contracts() -> None:
    """Prevent silent workflow drift in the built-in template."""

    assert SI_COLUMNS == ["Backlog", "Ready", "In Progress", "Review", "Done"]
    assert SI_EMAIL_NOTIFICATION_POLICY == {
        "is_enabled": True,
        "notify_all_members": True,
        "categories": ["cards"],
        "card_move_target_columns": ["Review"],
    }


def test_creation_prefix_is_used_only_when_it_is_a_real_template() -> None:
    """Quoted and plain titles work while a valid leading template stays explicit."""

    templates = TemplateRepository()
    templates.items.append(ProjectTemplate(name="SI", columns=SI_COLUMNS))
    service = _service(SimpleNamespace(project_template=templates))

    assert service.resolve_creation_target("SI Customer board", None, True) == (
        "Customer board",
        "SI",
    )
    assert service.resolve_creation_target("Private board", None, True) == (
        "Private board",
        None,
    )
    assert service.resolve_creation_target("SI Customer board", None, False) == (
        "SI Customer board",
        None,
    )
