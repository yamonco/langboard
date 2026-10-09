"""Optional app display traits, never authorization, workflow or material policy."""

import json
import re


CARD_PRESENTATION_KEY = "card.presentation.v1"


def validate_card_presentation(value: str) -> dict:
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError("Card presentation exceeds the display limit")
    try:
        item = json.loads(value)
    except (ValueError, TypeError):
        raise ValueError("Invalid card presentation") from None
    allowed = {"version", "key", "axis", "name", "description", "icon", "translations"}
    if not isinstance(item, dict) or set(item) - allowed:
        raise ValueError("Invalid card presentation fields")
    if type(item.get("version")) is not int or item["version"] != 1 or item.get("axis") not in ("type", "origin"):
        raise ValueError("Invalid card presentation version or axis")
    if not isinstance(item.get("key"), str) or not re.fullmatch(
        r"app\.[a-z][a-z0-9_-]{0,31}\.[a-z][a-z0-9_-]{0,63}", item["key"]
    ):
        raise ValueError("App card presentation requires a namespaced key")

    def text(value, maximum):
        return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum

    if not text(item.get("name"), 80) or not text(item.get("description"), 1000):
        raise ValueError("Card presentation requires English fallback text")
    if "icon" in item and not text(item["icon"], 32):
        raise ValueError("Invalid card presentation icon")
    translations = item.get("translations", {})
    if not isinstance(translations, dict) or len(translations) > 16:
        raise ValueError("Invalid card presentation translations")
    for locale, translation in translations.items():
        if not isinstance(locale, str) or not re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}", locale):
            raise ValueError("Invalid card presentation locale")
        if not isinstance(translation, dict) or set(translation) != {"name", "description"}:
            raise ValueError("Invalid card presentation translation")
        if not text(translation["name"], 80) or not text(translation["description"], 1000):
            raise ValueError("Invalid card presentation translation text")
    return item
