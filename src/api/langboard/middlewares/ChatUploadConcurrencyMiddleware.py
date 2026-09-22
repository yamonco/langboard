from threading import BoundedSemaphore
from fastapi import status
from langboard_shared.core.routing import BaseMiddleware, JsonResponse
from langboard_shared.Env import Env
from starlette.types import ASGIApp, Receive, Scope, Send


_TOO_MANY_UPLOADS_MESSAGE = "Too many concurrent chat uploads."


class ChatUploadConcurrencyMiddleware(BaseMiddleware):
    __auto_load__ = False

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._slots = BoundedSemaphore(max(0, Env.CHAT_UPLOAD_MAX_CONCURRENCY))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_chat_upload(scope):
            await self.app(scope, receive, send)
            return

        if not self._slots.acquire(blocking=False):
            response = JsonResponse(
                content={"message": _TOO_MANY_UPLOADS_MESSAGE},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            await response(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            self._slots.release()

    @staticmethod
    def _is_chat_upload(scope: Scope) -> bool:
        path = scope.get("path")
        if scope.get("type") != "http" or scope.get("method") != "POST" or not isinstance(path, str):
            return False
        parts = path.split("/")
        return len(parts) == 5 and parts[1] == "board" and bool(parts[2]) and parts[3:] == ["chat", "upload"]
