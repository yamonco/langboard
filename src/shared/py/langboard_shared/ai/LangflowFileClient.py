from dataclasses import dataclass
from io import BufferedIOBase
from typing import BinaryIO
from urllib.parse import quote, urlparse
import httpx
from ..domain.models.InternalBot import InternalBot
from ..Env import Env


@dataclass(frozen=True)
class LangflowFile:
    file_id: str
    path: str


class LangflowFileClient:
    @staticmethod
    def _base_url(bot: InternalBot) -> str:
        if not bot.api_url or not bot.api_key:
            raise ValueError("Langflow file credentials are not configured")
        parsed = urlparse(bot.api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.fragment:
            raise ValueError("Langflow file endpoint is invalid")
        return bot.api_url.rstrip("/")

    @classmethod
    def upload(
        cls,
        bot: InternalBot,
        file: BinaryIO,
        filename: str,
        content_type: str | None,
        size: int | None,
    ) -> LangflowFile:
        if not filename or any(value in filename for value in ("..", "/", "\\", "\x00", "\n", "\r")):
            raise ValueError("Langflow attachment filename is invalid")
        if size is None or size <= 0 or size > Env.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise ValueError("Langflow attachment size is invalid")
        if not isinstance(file, BufferedIOBase):
            try:
                file.seek(0)
            except (AttributeError, OSError) as error:
                raise ValueError("Langflow attachment stream is not seekable") from error
        else:
            file.seek(0)

        try:
            response = httpx.post(
                f"{cls._base_url(bot)}/api/v2/files",
                headers={"x-api-key": bot.api_key},
                files={"file": (filename, file, content_type or "application/octet-stream")},
                timeout=httpx.Timeout(Env.AI_REQUEST_TIMEOUT, connect=10),
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ValueError("Langflow file upload failed") from error

        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str) or not isinstance(payload.get("path"), str):
            raise ValueError("Langflow file upload response is invalid")
        return LangflowFile(file_id=payload["id"], path=payload["path"])

    @classmethod
    def delete(cls, bot: InternalBot, file_id: str) -> bool:
        if not file_id:
            return False
        try:
            response = httpx.delete(
                f"{cls._base_url(bot)}/api/v2/files/{quote(file_id, safe='')}",
                headers={"x-api-key": bot.api_key},
                timeout=httpx.Timeout(Env.AI_REQUEST_TIMEOUT, connect=10),
                follow_redirects=False,
            )
            return response.status_code in {200, 204, 404}
        except (httpx.HTTPError, ValueError):
            return False
