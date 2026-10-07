"""Settings and standalone counts must carry the server audience, never admin bypass."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.routes.board import BoardApi, BoardSettingApi
from langboard_shared.core.routing import ApiException
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel


@pytest.mark.parametrize("channel", [None, CollaborationChannel.HumanUI, CollaborationChannel.Mcp])
def test_settings_and_column_routes_forward_trusted_scope(channel):
    project, context, actor = object(), object(), object()
    effective = channel or CollaborationChannel.Api
    request = SimpleNamespace(scope={} if channel is None else {"collaboration_channel": channel})
    resolver = Mock(return_value=(project, context))
    inventory = Mock(return_value=[])
    columns = Mock(return_value=[])
    service = SimpleNamespace(
        card=SimpleNamespace(resolve_visibility_context=resolver, get_api_list_by_project=inventory),
        project_column=SimpleNamespace(get_api_list_by_project=columns),
        project=SimpleNamespace(
            get_details=Mock(return_value=(project, {})),
            get_api_assigned_internal_bot_list_with_setting_map=Mock(return_value=([], {})),
        ),
        internal_bot=SimpleNamespace(get_api_list=Mock(return_value=[])),
        chat=SimpleNamespace(get_api_template_list=Mock(return_value=[])),
    )
    BoardSettingApi.get_project_details("p", request, actor, service)
    resolver.assert_called_once_with("p", actor, effective)
    inventory.assert_called_once_with(project, actor, channel=effective)
    columns.assert_called_once_with(project, context=context)
    columns.reset_mock()
    BoardApi.get_project_columns("p", request, actor, service)
    columns.assert_called_once_with(project, context=context)
    resolver.return_value = None
    for callback in (BoardSettingApi.get_project_details, BoardApi.get_project_columns):
        columns.reset_mock()
        service.project.get_details.reset_mock()
        with pytest.raises(ApiException.NotFound_404):
            callback("p", request, actor, service)
        columns.assert_not_called()
        service.project.get_details.assert_not_called()
