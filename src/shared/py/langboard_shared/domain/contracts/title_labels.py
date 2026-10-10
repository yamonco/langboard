"""Exact, deterministic interpretation of consecutive leading label tokens."""

import re
from collections.abc import Mapping
from dataclasses import dataclass


_TOKEN = re.compile(r"\[([^\[\]\r\n]{1,100})\][ \t]*")


@dataclass(frozen=True)
class TitleLabels:
    title: str
    global_label_uids: tuple[str, ...] = ()


def parse_title_labels(title: str, names: Mapping[str, str | None]) -> TitleLabels:
    """Unknown/ambiguous names remain literal; no fuzzy, local or LLM lookup."""
    position = 0
    retained = []
    selected = []
    while match := _TOKEN.match(title, position):
        uid = names.get(match[1])
        if uid:
            if uid not in selected:
                selected.append(uid)
        else:
            retained.append(match[0])
        position = match.end()
    if not selected:
        return TitleLabels(title)
    result = ("".join(retained) + title[position:]).strip()
    # A token-only title must remain valid even when every token matches.
    return TitleLabels(result, tuple(selected)) if result else TitleLabels(title)


def global_label_names(labels: list[dict]) -> dict[str, str | None]:
    """One exact-name index; collisions cannot pick a label by iteration order."""
    names: dict[str, str | None] = {}
    for label in labels:
        candidates = [
            label["name"],
            *label.get("aliases", []),
            *(text.get("name") for text in label.get("translations", {}).values()),
        ]
        for name in candidates:
            if not name:
                continue
            if name in names and names[name] != label["uid"]:
                names[name] = None
            else:
                names[name] = label["uid"]
    return names
