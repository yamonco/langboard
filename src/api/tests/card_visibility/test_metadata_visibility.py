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


def test_sdk_presentation_write_stops_before_hidden_metadata_or_events():
    saver = Mock(side_effect=AssertionError("hidden write"))
    service = SimpleNamespace(
        card=SimpleNamespace(resolve_readable_card=Mock(return_value=None)), metadata=SimpleNamespace(save=saver)
    )
    with pytest.raises(ValueError, match="not found"):
        CardMcp.save_public_card_metadata("p", "c", "card.presentation.v1", "{}", object(), service)
    saver.assert_not_called()
    assert service.card.resolve_readable_card.call_args.args[-1] == CollaborationChannel.Mcp


def test_sdk_presentation_write_publishes_existing_metadata_update(monkeypatch):
    card = SimpleNamespace(is_linked_resource=False, get_uid=lambda: "c")
    service = SimpleNamespace(
        card=SimpleNamespace(resolve_readable_card=lambda *args: (object(), card, object())),
        metadata=SimpleNamespace(save=Mock(return_value=SimpleNamespace(value="value"))),
    )
    publisher = Mock()
    monkeypatch.setattr(CardMcp.MetadataPublisher, "updated_metadata", publisher)
    assert CardMcp.save_public_card_metadata("p", "c", "card.presentation.v1", "value", object(), service) == {
        "key": "card.presentation.v1",
        "value": "value",
        "total_chars": 5,
        "truncated": False,
    }
    publisher.assert_called_once()


def mutation_callbacks(actor, service, channel):
    request = SimpleNamespace(scope={"collaboration_channel": channel})
    form = SimpleNamespace(key="card.presentation.v1", value="{}", old_key=None, keys=["card.presentation.v1"])
    return [
        lambda: MetadataMcp.save_card_metadata("p", "c", form.key, form.value, None, actor, service),
        lambda: MetadataMcp.delete_card_metadata("p", "c", form.keys, actor, service),
        lambda: CardMcp.delete_public_card_metadata("p", "c", form.keys, actor, service),
        lambda: CardMetadataApi.save_card_metadata("p", "c", form, request, actor, service),
        lambda: CardMetadataApi.delete_card_metadata(form, "p", "c", request, actor, service),
    ]


@pytest.mark.parametrize("channel", [CollaborationChannel.Api, CollaborationChannel.HumanUI])
@pytest.mark.parametrize("index", range(5))
def test_all_metadata_mutations_block_hidden_cards_before_write_or_publish(monkeypatch, channel, index):
    writer = Mock(side_effect=AssertionError("hidden write"))
    events = Mock(side_effect=AssertionError("hidden event"))
    resolver = Mock(return_value=None)
    service = SimpleNamespace(
        card=SimpleNamespace(resolve_readable_card=resolver), metadata=SimpleNamespace(save=writer, delete=writer)
    )
    monkeypatch.setattr(CardMcp.MetadataPublisher, "updated_metadata", events)
    monkeypatch.setattr(CardMcp.MetadataPublisher, "deleted_metadata", events)
    actor = object()
    error = ValueError if index < 3 else ApiException.NotFound_404
    with pytest.raises(error):
        mutation_callbacks(actor, service, channel)[index]()
    assert resolver.call_args.args == ("p", "c", actor, CollaborationChannel.Mcp if index < 3 else channel)
    writer.assert_not_called()
    events.assert_not_called()


@pytest.mark.parametrize("index", range(5))
def test_linked_resource_metadata_is_read_only_before_publishing(monkeypatch, index):
    writer = Mock(side_effect=AssertionError("linked resource write"))
    events = Mock(side_effect=AssertionError("linked resource event"))
    card = SimpleNamespace(is_linked_resource=True)
    service = SimpleNamespace(
        card=SimpleNamespace(resolve_readable_card=lambda *args: (object(), card, object())),
        metadata=SimpleNamespace(save=writer, delete=writer),
    )
    monkeypatch.setattr(CardMcp.MetadataPublisher, "updated_metadata", events)
    monkeypatch.setattr(CardMcp.MetadataPublisher, "deleted_metadata", events)
    with pytest.raises(ValueError if index < 3 else ApiException.NotFound_404):
        mutation_callbacks(object(), service, CollaborationChannel.HumanUI)[index]()
    writer.assert_not_called()
    events.assert_not_called()


@pytest.mark.parametrize("index", range(5))
def test_readable_metadata_mutations_reach_current_card_and_publish(monkeypatch, index):
    card = SimpleNamespace(is_linked_resource=False, get_uid=lambda: "c")
    save = Mock(return_value=SimpleNamespace(value="{}"))
    delete = Mock(return_value=True)
    events = Mock()
    service = SimpleNamespace(
        card=SimpleNamespace(resolve_readable_card=lambda *args: (object(), card, object())),
        metadata=SimpleNamespace(save=save, delete=delete),
    )
    monkeypatch.setattr(CardMcp.MetadataPublisher, "updated_metadata", events)
    monkeypatch.setattr(CardMcp.MetadataPublisher, "deleted_metadata", events)
    mutation_callbacks(object(), service, CollaborationChannel.HumanUI)[index]()
    operation = save if index in (0, 3) else delete
    assert operation.call_args.args[1] is card
    events.assert_called_once()


def test_http_invalid_presentation_is_bad_request_without_event(monkeypatch):
    card = SimpleNamespace(is_linked_resource=False)
    service = SimpleNamespace(
        card=SimpleNamespace(resolve_readable_card=lambda *args: (object(), card, object())),
        metadata=SimpleNamespace(save=Mock(side_effect=ValueError("invalid metadata"))),
    )
    events = Mock()
    monkeypatch.setattr(CardMcp.MetadataPublisher, "updated_metadata", events)
    with pytest.raises(ApiException.BadRequest_400):
        mutation_callbacks(object(), service, CollaborationChannel.HumanUI)[3]()
    events.assert_not_called()
