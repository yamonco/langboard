import os
from types import SimpleNamespace
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard.routes.settings.Form import SaveGlobalLabelForm
from langboard_shared.domain.services.factory.GlobalLabelService import GlobalLabelService
from langboard_shared.helpers import InfraHelper


@pytest.fixture
def labels(monkeypatch):
    items = []
    monkeypatch.setattr(InfraHelper, "get_all", lambda model: items)
    monkeypatch.setattr(
        InfraHelper,
        "get_by",
        lambda model, key, value: next((item for item in items if getattr(item, key) == value), None),
    )
    monkeypatch.setattr(
        InfraHelper, "get_by_id_like", lambda model, uid: next((item for item in items if item.get_uid() == uid), None)
    )
    repository = SimpleNamespace(global_label=SimpleNamespace(insert=items.append, update=lambda item: None))
    return GlobalLabelService(lambda _: None, lambda _: None, repository), items


def test_global_label_translations_survive_update_and_english_is_canonical(labels):
    service, items = labels
    label = service.save(
        " Request ",
        "#aabbcc",
        "English description",
        translations={"ko": {"name": "요청", "description": "요청 설명"}, "en": {"name": "stale"}},
    )
    assert label.name == "Request"
    assert label.color == "#AABBCC"
    assert label.translations["en"] == {"name": "Request", "description": "English description"}
    assert label.translations["ko"]["name"] == "요청"
    updated = service.save("Request", "#112233", "Changed", label.get_uid(), {"ja": {"name": "依頼"}})
    assert updated is label
    assert len(items) == 1
    assert service.get_api_list()[0]["translations"]["ja"]["name"] == "依頼"


@pytest.mark.parametrize(
    "name,color,translations",
    [
        (" ", "#112233", {}),
        ("Label", "red", {}),
        ("Label", "#112233", {"../../bad": {"name": "x"}}),
        ("Label", "#112233", {"ko": {"name": "x", "policy": "bad"}}),
    ],
)
def test_invalid_labels_do_not_write(labels, name, color, translations):
    service, items = labels
    with pytest.raises(ValueError):
        service.save(name, color, "", translations=translations)
    assert not items


def test_duplicate_name_and_missing_uid_do_not_create_labels(labels):
    service, items = labels
    service.save("Existing", "#112233", "")
    with pytest.raises(ValueError):
        service.save("Existing", "#112233", "")
    assert service.save("Missing", "#112233", "", "missing") is None
    assert len(items) == 1


def test_form_rejects_whitespace_and_translation_field_types():
    with pytest.raises(ValueError):
        SaveGlobalLabelForm(name=" ", color="#112233")
    with pytest.raises(ValueError):
        SaveGlobalLabelForm(name="Label", color="#112233", translations={"ko": {"name": []}})
