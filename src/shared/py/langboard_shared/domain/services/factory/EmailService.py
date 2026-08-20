import asyncio
from json import loads as json_loads
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from pydantic import SecretStr
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

        if not self.__create_config():
            return False

        subject, template = self.__get_template(
            lang,
            template_name,
            {
                **formats,
                "app_name": Env.PROJECT_NAME.capitalize(),
                "logo_url": f"{Env.PUBLIC_UI_URL}/images/logo.png",
            },
        )

        message = MessageSchema(
            subject=subject,
            recipients=[to],
            body=template,
            subtype=MessageType.html,
            reply_to=[reply_to] if reply_to else [],
        )

        fm = FastMail(self.__config)
        try:
            asyncio.run(fm.send_message(message))
        except Exception:
            if Env.ENVIRONMENT == "development":
                return True
            return False

        return True

    def __create_config(self) -> bool:
        if hasattr(self, "__config"):
            return True

        try:
            self.__config = ConnectionConfig(
                MAIL_FROM=Env.MAIL_FROM,
                MAIL_FROM_NAME=Env.MAIL_FROM_NAME,
                MAIL_USERNAME=Env.MAIL_USERNAME,
                MAIL_PASSWORD=SecretStr(Env.MAIL_PASSWORD),
                MAIL_PORT=int(Env.MAIL_PORT),
                MAIL_SERVER=Env.MAIL_SERVER,
                MAIL_STARTTLS=Env.MAIL_STARTTLS,
                MAIL_SSL_TLS=Env.MAIL_SSL_TLS,
                USE_CREDENTIALS=bool(Env.MAIL_USERNAME) and bool(Env.MAIL_PASSWORD),
                TIMEOUT=5,
            )
            return True
        except Exception:
            return False

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
