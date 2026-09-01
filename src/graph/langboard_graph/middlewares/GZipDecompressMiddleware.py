from tempfile import TemporaryFile
from typing import cast, override
from zlib import MAX_WBITS, decompressobj
from zlib import error as ZlibError
from fastapi import status
from langboard_shared.core.routing import BaseMiddleware, JsonResponse
from langboard_shared.Env import Env
from starlette.datastructures import Headers
from starlette.types import Message, Receive, Scope, Send


_DECOMPRESSED_CHUNK_SIZE = 1024 * 1024


class GZipDecompressMiddleware(BaseMiddleware):
    @override
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if "gzip" not in headers.getlist("content-encoding"):
            await self.app(scope, receive, send)
            return

        decompressor = decompressobj(MAX_WBITS | 16)
        decompressed_size = 0
        max_decompressed_size = Env.MAX_FILE_SIZE_MB * 1024 * 1024
        disconnected = False

        with TemporaryFile() as decompressed_body:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    disconnected = True
                    break

                compressed_body = cast(bytes, message.get("body", b""))
                while compressed_body:
                    remaining_size = max_decompressed_size - decompressed_size
                    output_limit = min(_DECOMPRESSED_CHUNK_SIZE, remaining_size + 1)
                    try:
                        body = decompressor.decompress(compressed_body, output_limit)
                    except ZlibError:
                        await self._send_invalid_body(scope, receive, send)
                        return

                    decompressed_size += len(body)
                    if decompressed_size > max_decompressed_size:
                        await self._send_body_too_large(scope, receive, send)
                        return
                    _ = decompressed_body.write(body)
                    compressed_body = decompressor.unconsumed_tail

                if not message.get("more_body", False):
                    try:
                        tail = decompressor.flush()
                    except ZlibError:
                        await self._send_invalid_body(scope, receive, send)
                        return
                    decompressed_size += len(tail)
                    if decompressed_size > max_decompressed_size:
                        await self._send_body_too_large(scope, receive, send)
                        return
                    if not decompressor.eof:
                        await self._send_invalid_body(scope, receive, send)
                        return
                    _ = decompressed_body.write(tail)
                    break

            _ = decompressed_body.seek(0)
            replayed_size = 0
            sent_final_message = False

            async def replay_receive() -> Message:
                nonlocal replayed_size, sent_final_message
                body = decompressed_body.read(_DECOMPRESSED_CHUNK_SIZE)
                if body:
                    replayed_size += len(body)
                    more_body = replayed_size < decompressed_size or disconnected
                    sent_final_message = not more_body
                    return {"type": "http.request", "body": body, "more_body": more_body}
                if disconnected:
                    return {"type": "http.disconnect"}
                if not sent_final_message:
                    sent_final_message = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                return {"type": "http.disconnect"}

            await self.app(scope, replay_receive, send)

    @staticmethod
    async def _send_body_too_large(scope: Scope, receive: Receive, send: Send) -> None:
        response = JsonResponse(
            content={"message": f"Decompressed request body exceeds the {Env.MAX_FILE_SIZE_MB} MB limit"},
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
        await response(scope, receive, send)

    @staticmethod
    async def _send_invalid_body(scope: Scope, receive: Receive, send: Send) -> None:
        response = JsonResponse(
            content={"message": "Invalid gzip request body"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        await response(scope, receive, send)
