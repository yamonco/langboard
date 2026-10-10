from email.message import EmailMessage
from typing import Any
import pytest
from langboard_shared.domain.services.factory.EmailService import EmailService
from langboard_shared.Env import Env


def test_send_template_preserves_smtp_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """The direct SMTP adapter preserves sender, reply-to, TLS, and credentials."""

    sent: dict[str, Any] = {}

    async def send(message: EmailMessage, **kwargs: Any) -> None:
        sent.update(message=message, **kwargs)

    settings = {
        "MAIL_FROM": "noreply@example.test",
        "MAIL_FROM_NAME": "Langboard",
        "MAIL_USERNAME": "smtp-user",
        "MAIL_PASSWORD": "smtp-password",
        "MAIL_SERVER": "smtp.example.test",
        "MAIL_PORT": 587,
        "MAIL_STARTTLS": True,
        "MAIL_SSL_TLS": False,
        "PROJECT_NAME": "langboard",
        "PUBLIC_UI_URL": "https://board.example.test",
    }
    for name, value in settings.items():
        monkeypatch.setattr(type(Env), name, property(lambda self, value=value: value))
    monkeypatch.setattr(
        EmailService,
        "_EmailService__get_template",
        lambda self, *args: ("Subject", "<strong>Hello</strong>"),
    )
    monkeypatch.setattr("aiosmtplib.send", send)

    service = EmailService(lambda *_: None, lambda *_: None, None)  # type: ignore[arg-type]
    assert service.send_template("en", "person@example.test", "verify", {}, reply_to="reply@example.test")

    message = sent["message"]
    assert message["From"] == "Langboard <noreply@example.test>"
    assert message["To"] == "person@example.test"
    assert message["Reply-To"] == "reply@example.test"
    assert sent["hostname"] == "smtp.example.test"
    assert sent["start_tls"] is True


@pytest.mark.parametrize("language", ["ko-KR", "ja-JP", "zh-CN"])
def test_missing_locale_uses_english_template(monkeypatch: pytest.MonkeyPatch, tmp_path, language: str) -> None:
    import importlib

    english = tmp_path / "en-US"
    english.mkdir()
    (english / "lang.json").write_text('{"subjects": {"verify": "Hello {recipient}"}}')
    (english / "verify_email.html").write_text("<p>Hello {recipient}</p>")
    module = importlib.import_module("langboard_shared.domain.services.factory.EmailService")
    monkeypatch.setattr(module, "get_resource_path", lambda resource, locale: tmp_path / locale)
    monkeypatch.setattr(type(Env), "PROJECT_NAME", property(lambda self: "langboard"))
    service = EmailService(lambda *_: None, lambda *_: None, None)
    assert service._EmailService__get_template(language, "verify", {"recipient": "Tester"}) == (
        "[Langboard] Hello Tester", "<p>Hello Tester</p>"
    )
