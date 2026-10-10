"""Metadata and image compatibility reads must stop before hidden content loads."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.mcp_tools import CardMcp, MetadataMcp
from langboard.routes.metadata import CardMetadataApi
from langboard_shared.core.routing import ApiException
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel


def test_metadata_and_attachment_reads_stop_before_loading_hidden_data():
    reader = Mock(side_effect=AssertionError("hidden data loaded"))
    resolver = Mock(return_value=None)
    service = SimpleNamespace(
        card=SimpleNamespace(resolve_readable_card=resolver),
        metadata=SimpleNamespace(get_all_as_api=reader, get_by_key_as_api=reader),
        card_attachment=SimpleNamespace(get_api_list_by_card=reader),
    )
    actor = object()
    request = SimpleNamespace(scope={})
    for callback in (
        lambda: MetadataMcp.get_card_metadata("p", "c", actor, service),
        lambda: MetadataMcp.get_card_metadata_by_key("p", "c", "key", actor, service),
        lambda: CardMcp.get_card_attachments("p", "c", service, user_or_bot=actor),
    ):
        with pytest.raises(ValueError, match="not found"):
            callback()
        assert resolver.call_args.args[-1] == CollaborationChannel.Mcp
    for callback in (
        lambda: CardMetadataApi.get_card_metadata("p", "c", request, actor, service),
        lambda: CardMetadataApi.get_card_metadata_by_key("p", "c", request, actor, SimpleNamespace(key="key"), service),
    ):
        with pytest.raises(ApiException.NotFound_404):
            callback()
        assert resolver.call_args.args[-1] == CollaborationChannel.Api
    reader.assert_not_called()


def test_batch_metadata_loads_only_the_card_service_visible_set():
    visible = [object()]
    reader = Mock(return_value={"visible-card": {"key": "value"}})
    project = object()
    service = SimpleNamespace(
        project=SimpleNamespace(get_by_id_like=lambda _: project),
        card=SimpleNamespace(get_visible_by_project=Mock(return_value=visible)),
        metadata=SimpleNamespace(get_all_by_foreign_models_as_api=reader),
    )
    actor = object()
    request = SimpleNamespace(scope={"collaboration_channel": CollaborationChannel.HumanUI})
    CardMetadataApi.get_project_cards_metadata("p", request, actor, service)
    assert reader.call_args.args[2] is visible
    service.card.get_visible_by_project.assert_called_once_with(project, actor, CollaborationChannel.HumanUI)
