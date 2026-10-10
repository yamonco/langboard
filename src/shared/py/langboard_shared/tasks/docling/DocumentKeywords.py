"""Bound and separate optional multilingual search attributes from transcription."""

from json import loads
from re import DOTALL, search
from typing import Any


KEYWORD_LANGUAGES = {"ko": "Korean", "en": "English", "ja": "Japanese", "zh": "Chinese"}
KEYWORD_MARKER = "LANGBOARD_SEARCH_KEYWORDS:"


def keyword_languages(config: dict[str, Any]) -> list[str]:
    value = config.get("keyword_languages", list(KEYWORD_LANGUAGES))
    if not isinstance(value, list) or any(language not in KEYWORD_LANGUAGES for language in value):
        raise ValueError("keyword_languages must contain only ko, en, ja and zh")
    return list(dict.fromkeys(value))


def normalize_keywords(value: Any, languages: list[str], limit: int = 8) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for language in languages:
        words = value.get(language)
        if not isinstance(words, list):
            continue
        unique = {}
        for word in words[:128]:
            if not isinstance(word, str):
                continue
            word = " ".join(word.split())[:80]
            if word and len(unique) < limit:
                unique.setdefault(word.casefold(), word)
        if unique:
            result[language] = list(unique.values())
    return result


def split_keyword_attributes(text: str, languages: list[str]) -> tuple[str, dict[str, list[str]]]:
    match = search(r"\n?<!--LANGBOARD_SEARCH_KEYWORDS:\s*(\{.*?\})\s*-->\s*$", text, DOTALL)
    if not match:
        return text, {}
    body = text[: match.start()].rstrip()
    if not languages or len(match.group(1)) > 16_384:
        return body, {}
    try:
        keywords = loads(match.group(1))
    except ValueError:
        return body, {}
    return body, normalize_keywords(keywords, languages)
