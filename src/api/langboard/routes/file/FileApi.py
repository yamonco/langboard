from mimetypes import guess_type
from tempfile import SpooledTemporaryFile
from typing import Iterator
from fastapi import Path
from langboard_shared.core.routing import ApiException, AppRouter
from langboard_shared.core.storage import Storage
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse


_DOWNLOAD_CHUNK_SIZE = 64 * 1024
_DOWNLOAD_SPOOL_MEMORY_LIMIT = 1024 * 1024


def _read_chunks(file: SpooledTemporaryFile[bytes]) -> Iterator[bytes]:
    while chunk := file.read(_DOWNLOAD_CHUNK_SIZE):
        yield chunk


@AppRouter.api.get("/file/{storage_type}/{storage_name}/{filename}", tags=["General"])
def get_file(storage_type: str = Path(), storage_name: str = Path(), filename: str = Path()) -> StreamingResponse:
    media_type, _ = guess_type(filename)

    file = SpooledTemporaryFile(max_size=_DOWNLOAD_SPOOL_MEMORY_LIMIT, mode="w+b")
    if not Storage.download(storage_type, storage_name, filename, file):
        file.close()
        raise ApiException.NotFound_404()
    file.seek(0)

    return StreamingResponse(
        _read_chunks(file),
        media_type=media_type,
        background=BackgroundTask(file.close),
    )
