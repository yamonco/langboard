from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from pydantic import BaseModel
from ...Env import Env
from ..types import SafeDateTime
from ..utils.String import create_short_unique_id
from .DispatcherModel import DispatcherModel


_BROADCAST_DIR: Path = Env.DATA_DIR / "broadcast"


class BaseDispatcherQueue(ABC):
    @abstractmethod
    def put(self, event: str | BaseModel, data: dict[str, Any] | None = None): ...

    def _record_model(self, event: str | DispatcherModel, data: dict[str, Any] | None = None) -> str:
        now_str = str(SafeDateTime.now().timestamp()).replace(".", "_")
        random_str = create_short_unique_id(10)

        model = DispatcherModel(event=event, data=data or {}) if isinstance(event, str) else event

        name = f"{now_str}-{random_str}-fileonly.json"

        if not _BROADCAST_DIR.is_dir():
            return name

        file_path = _BROADCAST_DIR / name

        with open(file_path, "w", encoding="utf-8") as file:
            file.write(model.model_dump_json())

        return name
