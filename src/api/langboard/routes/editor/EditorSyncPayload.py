from json import dumps as json_dumps
from langboard_shared.Env import Env


def rich_patch_request_fits_limit(document_name: str, value: str) -> bool:
    payload = json_dumps({"document_name": document_name, "value": value}, ensure_ascii=False, separators=(",", ":"))
    return len(payload.encode("utf-8")) <= Env.EDITOR_SYNC_MAX_REQUEST_SIZE_MB * 1024 * 1024
