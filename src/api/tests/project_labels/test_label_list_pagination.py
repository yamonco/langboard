from types import SimpleNamespace
from unittest.mock import Mock, patch
from langboard_shared.domain.services.factory.ProjectLabelService import ProjectLabelService


def test_project_label_projection_applies_the_requested_limit() -> None:
    """Project label pagination reaches the repository query."""

    project = SimpleNamespace()
    label = SimpleNamespace(api_response=lambda: {"name": "label"})
    repository = SimpleNamespace(
        project_label=SimpleNamespace(
            get_all_by_project=Mock(return_value=[label]),
        )
    )
    service = ProjectLabelService(lambda _: None, lambda _: None, repository)

    with patch(
        "langboard_shared.domain.services.factory.ProjectLabelService.InfraHelper.get_by_id_like",
        return_value=project,
    ):
        assert service.get_api_list_by_project(project, limit=5) == [{"name": "label"}]

    repository.project_label.get_all_by_project.assert_called_once_with(project, where_in=None, limit=5)
