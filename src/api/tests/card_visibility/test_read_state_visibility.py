"""Read receipt transport must not disclose private card IDs to board members."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard.routes.board import BoardCardApi
from langboard_shared.core.routing import ApiException, SocketTopic
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.publishers import CardPublisher


@pytest.mark.parametrize("visibility", ["SHARED", "INTERNAL", "PRIVATE"])
def test_read_invalidation_uses_private_user_topic_for_nonshared_card(monkeypatch, visibility):
    publish = Mock()
    monkeypatch.setattr(CardPublisher, "put_dispather", publish)
    card = SimpleNamespace(visibility=visibility, project_id=SimpleNamespace(to_short_code=lambda: "board"), get_uid=lambda: "card")
    user = SimpleNamespace(get_uid=lambda: "actor")
    CardPublisher.read_state_changed(card, user)
    event = publish.call_args.args[1]
    assert event.topic == (SocketTopic.Board if visibility == "SHARED" else SocketTopic.UserPrivate)
    assert event.topic_id == ("board" if visibility == "SHARED" else "actor")


def test_read_receipt_routes_forward_server_channel_and_keep_not_found():
    reader, seen, unread = Mock(return_value=None), Mock(return_value=None), Mock(return_value=None)
    service = SimpleNamespace(card=SimpleNamespace(get_card_read_state=reader, mark_card_seen=seen, set_card_read_state=unread))
    actor = object()
    request = SimpleNamespace(scope={"collaboration_channel": CollaborationChannel.HumanUI})
    for callback in (BoardCardApi.get_card_read_state, BoardCardApi.mark_card_seen, BoardCardApi.mark_card_unread):
        with pytest.raises(ApiException.NotFound_404):
            callback("p", "c", request, actor, service)
    for mock in (reader, seen, unread):
        assert mock.call_args.kwargs["channel"] == CollaborationChannel.HumanUI
    assert reader.call_args.kwargs["user"] is actor
