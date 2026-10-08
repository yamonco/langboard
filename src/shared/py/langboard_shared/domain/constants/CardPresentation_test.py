import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from langboard_shared.domain.constants.CardPresentation import CARD_PRESENTATION_KEY, validate_card_presentation
from langboard_shared.domain.models import Card, CardMetadata
from langboard_shared.domain.services.factory.MetadataService import MetadataService


BASE = {
    "version": 1,
    "key": "app.github.issue",
    "axis": "origin",
    "name": "GitHub issue",
    "description": "Self-declared GitHub origin; workflow and approval are separate.",
}


def test_extension_metadata_roundtrips_without_authority_fields():
    item = {**BASE, "translations": {"ko-KR": {"name": "깃허브 이슈", "description": "앱 출처 표기입니다."}}}
    assert validate_card_presentation(json.dumps(item)) == item


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"axis": "visibility"},
        {"key": "visibility.private"},
        {"completed": True},
        {"visibility": "SHARED"},
        {"name": ""},
        {"icon": "a" * 33},
        {"translations": []},
        {"translations": {"../ko": {"name": "x", "description": "x"}}},
        {"translations": {"ko": {"name": "x"}}},
    ],
)
def test_invalid_or_authority_metadata_rejected(change):
    with pytest.raises(ValueError):
        validate_card_presentation(json.dumps({**BASE, **change}))


def test_validation_precedes_repository_write_for_every_metadata_entry():
    saver = Mock()
    service = SimpleNamespace(
        repo=SimpleNamespace(metadata=SimpleNamespace(save=saver)),
        _is_work_plan_receipt=MetadataService._is_work_plan_receipt,
    )
    card = Card(title="A", project_id=1, project_column_id=2)
    with pytest.raises(ValueError):
        MetadataService.save(service, CardMetadata, card, CARD_PRESENTATION_KEY, '{"visibility":"SHARED"}')
    saver.assert_not_called()
    value = json.dumps(BASE)
    MetadataService.save(service, CardMetadata, card, CARD_PRESENTATION_KEY, value)
    saver.assert_called_once_with(CardMetadata, card, CARD_PRESENTATION_KEY, value, None)
