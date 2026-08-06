import os
from types import SimpleNamespace
from typing import Any


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.domain.models import ProjectTemplate  # noqa: E402
from langboard_shared.domain.services.factory.ProjectTemplateService import (  # noqa: E402
    SI_COLUMNS,
    ProjectTemplateService,
)


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
    assert "Archive" not in template.columns
    assert template.is_default is True
    assert _service(repository).ensure_builtin() is template
    assert len(templates.items) == 1


def test_copy_snapshot_preserves_order_and_bot_settings_but_not_cards_or_schedules() -> None:
    """Copy captures only reusable board structure and automation hooks."""

    templates = TemplateRepository()
    project = SimpleNamespace(id=7)
    columns = [
        SimpleNamespace(id=2, name="Done", order=2, is_archive=False),
        SimpleNamespace(id=9, name="Archive", order=3, is_archive=True),
        SimpleNamespace(id=1, name="Backlog", order=0, is_archive=False),
    ]
    bot_type = SimpleNamespace(value="project_chat")
    internal_bot = SimpleNamespace(bot_type=bot_type)
    setting = SimpleNamespace(prompt="Keep it short", use_default_prompt=False)
    repository = SimpleNamespace(
        project_template=templates,
        project_column=SimpleNamespace(
            get_all_by_project=lambda _project: [(column, 0) for column in columns],
            get_bot_scopes_by_project=lambda _project: [],
        ),
        project_assigned_internal_bot=SimpleNamespace(get_all_by_project=lambda _project: [(internal_bot, setting)]),
        project_bot_scope=SimpleNamespace(get_all_by_project=lambda _project: []),
    )

    template = _service(repository).copy_from_project(project, "Support")

    assert template.columns == ["Backlog", "Done"]
    assert template.internal_bots == [
        {
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
    }
    assert not hasattr(template, "cards")
    assert not hasattr(template, "schedules")


def test_si_constant_is_stable_for_command_and_ui_contracts() -> None:
    """Prevent silent workflow drift in the built-in template."""

    assert SI_COLUMNS == ["Backlog", "Ready", "In Progress", "Review", "Done"]


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
