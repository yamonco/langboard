import asyncio
from email.message import EmailMessage
from email.utils import formataddr
from json import loads as json_loads
import aiosmtplib
from ....core.domain import BaseDomainService
from ....core.resources import get_resource_path
from ....core.resources.locales.EmailTemplateNames import TEmailTemplateName
from ....Env import Env


class EmailService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "email"

    def send_template(
        self,
        lang: str,
        to: str,
        template_name: TEmailTemplateName,
        formats: dict[str, str],
        *,
        reply_to: str | None = None,
    ) -> bool:
        """Render and send one localized template through the configured SMTP transport."""

        subject, template = self.__get_template(
            lang,
            template_name,
            {
                **formats,
                "app_name": Env.PROJECT_NAME.capitalize(),
                "logo_url": f"{Env.PUBLIC_UI_URL}/images/logo.png",
            },
        )

        message = EmailMessage()
        message["From"] = formataddr((Env.MAIL_FROM_NAME, Env.MAIL_FROM))
        message["To"] = to
        message["Subject"] = subject
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(template, subtype="html")

        try:
            asyncio.run(
                aiosmtplib.send(
                    message,
                    hostname=Env.MAIL_SERVER,
                    port=int(Env.MAIL_PORT),
                    username=Env.MAIL_USERNAME or None,
                    password=Env.MAIL_PASSWORD or None,
                    start_tls=Env.MAIL_STARTTLS,
                    use_tls=Env.MAIL_SSL_TLS,
                    timeout=5,
                )
            )
        except Exception:
            if Env.ENVIRONMENT == "development":
                return True
            return False

        return True

    def __get_template(self, lang: str, template_name: TEmailTemplateName, formats: dict[str, str]) -> tuple[str, str]:
        locale_path = get_resource_path("locales", lang)
        template_path = locale_path / f"{template_name}_email.html"
        lang_path = locale_path / "lang.json"

        locale = json_loads(lang_path.read_text())
        subject: str = locale["subjects"][template_name]
        subject = self.__create_subject(subject.format_map(formats))

        template = template_path.read_text()
        template = template.format_map(formats)

        return subject, template

    def __create_subject(self, subject: str) -> str:
        return f"[{Env.PROJECT_NAME.capitalize()}] {subject}"
