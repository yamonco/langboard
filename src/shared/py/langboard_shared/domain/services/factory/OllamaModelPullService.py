from datetime import timedelta
from typing import Any
from ....core.broker import Broker
from ....core.domain import BaseDomainService
from ....core.logger import Logger
from ....core.publisher import BaseSocketPublisher, SocketPublishModel
from ....core.routing import GLOBAL_TOPIC_ID, SocketTopic
from ....core.types import SafeDateTime
from ....Env import Env
from ...models import OllamaModelPull
from ...models.OllamaModelPull import OllamaModelPullStatus


PULL_TASK = "langboard_shared.tasks.ollama.OllamaModelPullTask.pull_model"
PULL_STATUS_EVENT = "settings:ollama:model:pull:status"
_logger = Logger.use("ollama-pull")


class OllamaModelPullService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "ollama_model_pull"

    def request_pull(self, model_name: str) -> OllamaModelPull:
        model_name = model_name.strip()
        if not model_name or len(model_name) > 255:
            raise ValueError("Invalid Ollama model name")

        pull, accepted = self.repo.ollama_model_pull.accept(model_name)
        if accepted and self._queue(pull):
            pull.status = OllamaModelPullStatus.Queued
        return pull

    def get_active(self, limit: int = 100) -> list[OllamaModelPull]:
        return self.repo.ollama_model_pull.get_active(limit)

    def get_recent(self, limit: int = 100) -> list[OllamaModelPull]:
        return self.repo.ollama_model_pull.get_recent(limit)

    def recover(self, limit: int = 100) -> tuple[int, int]:
        older_than = SafeDateTime.now() - timedelta(seconds=max(3 * Env.AI_REQUEST_TIMEOUT, 300))
        stale = self.repo.ollama_model_pull.mark_stale_uncertain(older_than, limit)
        self.repo.ollama_model_pull.mark_stale_queued_pending(SafeDateTime.now() - timedelta(minutes=10), limit)
        for pull in stale:
            self.publish(pull.model_name, {"status": "error", "error": pull.failure_reason or "Pull outcome is uncertain"})

        pending = self.repo.ollama_model_pull.get_active(limit)
        queued = 0
        for pull in pending:
            if pull.status != OllamaModelPullStatus.Pending:
                continue
            if self._queue(pull):
                queued += 1
        return len(stale), queued

    def _queue(self, pull: OllamaModelPull) -> bool:
        if not self.repo.ollama_model_pull.reserve_dispatch(pull.id, pull.attempt):
            return False
        try:
            Broker.celery.send_task(PULL_TASK, args=[int(pull.id), pull.attempt])
            return True
        except Exception:
            self.repo.ollama_model_pull.release_dispatch(pull.id, pull.attempt)
            _logger.exception("Ollama pull queue dispatch failed; the accepted request remains pending")
            return False

    def report(self, pull: OllamaModelPull, percent: float, status_text: str | None) -> bool:
        updated = self.repo.ollama_model_pull.report(pull.id, pull.attempt, percent, status_text)
        if updated:
            data: dict[str, Any] = {"percent": percent} if percent > 0 else {"status": status_text or "pulling"}
            self.publish(pull.model_name, data)
        return updated

    def finish(self, pull: OllamaModelPull, succeeded: bool, error: str | None = None) -> bool:
        status = OllamaModelPullStatus.Success if succeeded else OllamaModelPullStatus.Failed
        updated = self.repo.ollama_model_pull.finish(pull.id, pull.attempt, status, error)
        if updated:
            data = {"status": "success"} if succeeded else {"status": "error", "error": error or "Pull failed"}
            self.publish(pull.model_name, data)
        return updated

    @staticmethod
    def publish(model_name: str, data: dict[str, Any]) -> None:
        payload = {"model": model_name, **data}
        try:
            BaseSocketPublisher.put_dispather(
                payload,
                SocketPublishModel(
                    topic=SocketTopic.OllamaManager,
                    topic_id=GLOBAL_TOPIC_ID,
                    event=PULL_STATUS_EVENT,
                    data_keys=list(payload),
                ),
            )
        except Exception:
            _logger.exception("Ollama pull status fanout failed; persisted state remains authoritative")
