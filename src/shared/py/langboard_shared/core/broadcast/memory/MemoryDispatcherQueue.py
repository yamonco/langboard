from typing import Any
from ..BaseDispatcherQueue import BaseDispatcherQueue
from ..DispatcherModel import DispatcherModel


class MemoryDispatcherQueue(BaseDispatcherQueue):
    def put(self, event: str | DispatcherModel, data: dict[str, Any] | None = None):
        self._record_model(event, data)
