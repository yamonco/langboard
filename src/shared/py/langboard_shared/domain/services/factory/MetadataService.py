from typing import Any, Literal, Sequence, TypeVar, overload
from ....core.db import BaseDbModel
from ....core.domain import BaseDomainService
from ...models.bases import BaseMetadataModel


_TMetadata = TypeVar("_TMetadata", bound=BaseMetadataModel)


class MetadataService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "metadata"

    @overload
    def get_all_as_api(
        self,
        model: type[_TMetadata],
        foreign_model: BaseDbModel,
        as_dict: Literal[False],
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...
    @overload
    def get_all_as_api(
        self,
        model: type[_TMetadata],
        foreign_model: BaseDbModel,
        as_dict: Literal[True],
        limit: int | None = None,
    ) -> dict[str, Any]: ...
    def get_all_as_api(
        self,
        model: type[_TMetadata],
        foreign_model: BaseDbModel,
        as_dict: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """Return metadata, optionally enforcing a repository row limit."""

        metadata_list = self.repo.metadata.get_list(model, foreign_model, limit=limit)
        if not as_dict:
            return [metadata.api_response() for metadata in metadata_list]

        metadata = {}
        for data in metadata_list:
            metadata[data.key] = data.value
        return metadata

    def get_all_by_foreign_models_as_api(
        self, model: type[_TMetadata], foreign_key: str, foreign_models: Sequence[BaseDbModel]
    ) -> dict[str, dict[str, str]]:
        foreign_model_by_id = {int(foreign_model.id): foreign_model for foreign_model in foreign_models}
        foreign_ids = list(foreign_model_by_id.keys())
        metadata_list = self.repo.metadata.get_by_foreign_ids(model, foreign_key, foreign_ids)
        records: dict[int, dict[str, str]] = {}
        for data in metadata_list:
            foreign_id = int(getattr(data, foreign_key))
            if foreign_id not in records:
                records[foreign_id] = {}
            records[foreign_id][data.key] = data.value

        return {
            foreign_model_by_id[foreign_id].get_uid(): metadata
            for foreign_id, metadata in records.items()
            if foreign_id in foreign_model_by_id
        }

    def get_by_key_as_api(self, model: type[_TMetadata], foreign_model: BaseDbModel, key: str) -> dict[str, Any] | None:
        metadata = self.repo.metadata.get_by_key(model, foreign_model, key)
        return metadata.api_response() if metadata else None

    def save(
        self, model: type[_TMetadata], foreign_model: BaseDbModel, key: str, value: str, old_key: str | None = None
    ) -> _TMetadata | None:
        metadata = self.repo.metadata.save(model, foreign_model, key, value, old_key)
        return metadata

    def delete(self, model: type[_TMetadata], foreign_model: BaseDbModel, keys: str | list[str]) -> bool:
        return self.repo.metadata.delete(model, foreign_model, keys)
