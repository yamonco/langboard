import re
from ....core.domain import BaseDomainService
from ....helpers import InfraHelper
from ...models import GlobalLabel


class GlobalLabelService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "global_label"

    def get_api_list(self) -> list[dict]:
        return [
            label.api_response()
            for label in sorted(InfraHelper.get_all(GlobalLabel), key=lambda label: label.name.casefold())
        ]

    def save(
        self,
        name: str,
        color: str,
        description: str,
        uid: str | None = None,
        translations: dict[str, dict[str, str]] | None = None,
        emoji: str | None = None,
    ) -> GlobalLabel | None:
        name = name.strip()
        if not name or len(name) > 100 or not re.fullmatch(r"#[0-9a-fA-F]{6}", color) or len(description) > 4000:
            raise ValueError("Invalid label fields")
        if emoji is not None:
            emoji = emoji.strip()

            def allowed(char: str) -> bool:
                return (
                    0x1F000 <= ord(char) <= 0x1FAFF
                    or 0x2300 <= ord(char) <= 0x23FF
                    or 0x2600 <= ord(char) <= 0x27BF
                    or 0x2B00 <= ord(char) <= 0x2BFF
                    or 0x2194 <= ord(char) <= 0x21FF
                    or 0xE0020 <= ord(char) <= 0xE007F
                    or ord(char)
                    in {
                        0x200D,
                        0xFE0F,
                        0x20E3,
                        0xA9,
                        0xAE,
                        0x203C,
                        0x2049,
                        0x2122,
                        0x2139,
                        0x3030,
                        0x303D,
                        0x3297,
                        0x3299,
                    }
                    or char in "0123456789#*"
                    and "\u20e3" in emoji
                )

            if len(emoji) > 32 or any(not allowed(char) for char in emoji):
                raise ValueError("Invalid label emoji")
        translations = {language: dict(text) for language, text in (translations or {}).items()}
        if len(set(translations) | {"en"}) > 30:
            raise ValueError("Too many label languages")
        for language, text in translations.items():
            if not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
                raise ValueError("Invalid language code")
            if (
                set(text) - {"name", "description"}
                or len(text.get("name", "")) > 100
                or len(text.get("description", "")) > 4000
            ):
                raise ValueError("Invalid label translation")
        translations["en"] = {"name": name, "description": description}
        label = InfraHelper.get_by_id_like(GlobalLabel, uid) if uid else None
        if uid and not label:
            return None
        existing = InfraHelper.get_by(GlobalLabel, "name", name)
        if existing and (not label or existing.id != label.id):
            raise ValueError("Label name already exists")
        if label:
            label.name, label.color, label.description = name, color.upper(), description
            label.translations = translations
            if emoji is not None:
                label.emoji = emoji
            self.repo.global_label.update(label)
        else:
            label = GlobalLabel(
                name=name, color=color.upper(), description=description, translations=translations, emoji=emoji or ""
            )
            self.repo.global_label.insert(label)
        return label
