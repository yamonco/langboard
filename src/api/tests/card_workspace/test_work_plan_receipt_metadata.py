"""External metadata callers cannot read, forge, rename or erase plan receipts."""

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.domain.models import Card, CardMetadata
from langboard_shared.domain.services.factory.MetadataService import MetadataService


def test_receipt_is_private_and_server_owned():
    card = Card(id=1, project_id=1, project_column_id=1, title="Anchor", order=0)

    def record(key):
        return SimpleNamespace(key=key, value="value", card_id=1, api_response=lambda: {"key": key, "value": "value"})

    private, public = record("internal.work_plan.receipt"), record("note")
    repo = Mock()
    repo.get_list.return_value = [private, public]
    repo.get_by_foreign_ids.return_value = [private, public]
    repo.get_by_key.return_value = private
    service = MetadataService(None, None, SimpleNamespace(metadata=repo))
    assert service.get_all_as_api(CardMetadata, card, as_dict=True) == {"note": "value"}
    assert service.get_all_as_api(CardMetadata, card) == [{"key": "note", "value": "value"}]
    assert service.get_all_by_foreign_models_as_api(CardMetadata, "card_id", [card]) == {
        card.get_uid(): {"note": "value"}
    }
    assert service.get_by_key_as_api(CardMetadata, card, private.key) is None
    repo.get_by_key.assert_not_called()
    assert service.get_by_key_as_api(CardMetadata, card, private.key, internal=True)["key"] == private.key
    for key, old_key in ((private.key, None), ("note", private.key), (" INTERNAL.WORK_PLAN.receipt ", None)):
        with pytest.raises(ValueError, match="server-owned"):
            service.save(CardMetadata, card, key, "forged", old_key)
    for keys in (private.key, ["note", private.key]):
        with pytest.raises(ValueError, match="server-owned"):
            service.delete(CardMetadata, card, keys)
    repo.save.assert_not_called()
    repo.delete_keys.assert_not_called()
    service.save(CardMetadata, card, private.key, "receipt", internal=True)
    repo.save.assert_called_once_with(CardMetadata, card, private.key, "receipt", None)
    service.save(CardMetadata, card, "note", "ordinary")
    service.delete(CardMetadata, card, "note")
    repo.delete_keys.assert_called_once_with(CardMetadata, card, "note")
