from json import loads
import requests
from ...core.broker import Broker
from ...core.logger import Logger
from ...core.types import SnowflakeID
from ...domain.models.OllamaModelPull import OllamaModelPull, OllamaModelPullStatus
from ...domain.services import DomainService
from ...Env import Env


_MAX_STATUS_LINE_BYTES = 64 * 1024
_logger = Logger.use("ollama-pull")


@Broker.wrap_sync_task_decorator
def pull_model(pull_id: int, attempt: int) -> None:
    service = DomainService()
    try:
        repository = service.ollama_model_pull.repo.ollama_model_pull
        identifier = SnowflakeID(pull_id)
        if not repository.claim(identifier, attempt):
            return

        pull = repository.get_by_id(identifier)
        ollama_url = Env.OLLAMA_API_URL
        if pull is None or pull.attempt != attempt or not ollama_url:
            if pull is not None:
                service.ollama_model_pull.finish(pull, False, "Ollama is not configured")
            return

        try:
            with requests.post(
                f"{ollama_url.rstrip('/')}/api/pull",
                json={"model": pull.model_name, "stream": True},
                stream=True,
                timeout=(10, Env.AI_REQUEST_TIMEOUT),
            ) as response:
                response.raise_for_status()
                completed = _consume_stream(response, pull, service)
                if completed is None:
                    return
                if not completed:
                    raise ValueError("Ollama pull ended without a success status")
            service.ollama_model_pull.finish(pull, True)
        except Exception as error:
            _logger.exception("Ollama model pull failed")
            service.ollama_model_pull.finish(pull, False, str(error)[:1000])
    finally:
        service.close()


def _consume_stream(response: requests.Response, pull: OllamaModelPull, service: DomainService) -> bool | None:
    buffer = bytearray()
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        buffer.extend(chunk)
        while (line_end := buffer.find(b"\n")) >= 0:
            if line_end > _MAX_STATUS_LINE_BYTES:
                raise ValueError("Ollama pull status line exceeded its size limit")
            line = bytes(buffer[:line_end]).strip()
            del buffer[: line_end + 1]
            if line:
                result = _consume_line(line, pull, service)
                if result is not False:
                    return result
        if len(buffer) > _MAX_STATUS_LINE_BYTES:
            raise ValueError("Ollama pull status line exceeded its size limit")

    if buffer.strip():
        return _consume_line(bytes(buffer).strip(), pull, service)
    return False


def _consume_line(line: bytes, pull: OllamaModelPull, service: DomainService) -> bool | None:
    data = loads(line)
    if not isinstance(data, dict):
        raise ValueError("Invalid Ollama pull status")
    error = data.get("error")
    if isinstance(error, str) and error:
        raise ValueError(error)
    if data.get("status") == OllamaModelPullStatus.Success.value:
        return True

    percent = pull.percent
    total = data.get("total")
    completed = data.get("completed")
    if isinstance(total, (int, float)) and isinstance(completed, (int, float)) and total > 0:
        percent = max(0.0, min(100.0, round(completed / total * 100, 1)))
    status_text: str | None = data.get("status") if isinstance(data.get("status"), str) else None
    if not service.ollama_model_pull.report(pull, percent, status_text[:255] if status_text else None):
        return None
    pull.percent = percent
    return False
