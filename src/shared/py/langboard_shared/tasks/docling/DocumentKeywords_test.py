import pytest
from langboard_shared.tasks.docling.DocumentKeywords import (
    keyword_languages,
    normalize_keywords,
    split_keyword_attributes,
)


def test_language_switches_and_untrusted_attribute_limits():
    assert keyword_languages({}) == ["ko", "en", "ja", "zh"]
    assert keyword_languages({"keyword_languages": []}) == []
    assert keyword_languages({"keyword_languages": ["ko", "ko"]}) == ["ko"]
    with pytest.raises(ValueError):
        keyword_languages({"keyword_languages": ["unsupported"]})
    assert normalize_keywords({"ko": [" 키워드 ", "키워드", 7], "en": ["disabled"]}, ["ko"]) == {"ko": ["키워드"]}
    text = 'original\n<!--LANGBOARD_SEARCH_KEYWORDS:{"ko":["키워드"],"en":["disabled"]}-->'
    assert split_keyword_attributes(text, ["ko"]) == ("original", {"ko": ["키워드"]})
    assert split_keyword_attributes(text, []) == ("original", {})
    assert split_keyword_attributes("original\n<!--LANGBOARD_SEARCH_KEYWORDS:{bad}-->", ["ko"]) == ("original", {})
    result = normalize_keywords({"en": [str(index) + "x" * 200 for index in range(30)]}, ["en"])
    assert len(result["en"]) == 8 and all(len(word) <= 80 for word in result["en"])
