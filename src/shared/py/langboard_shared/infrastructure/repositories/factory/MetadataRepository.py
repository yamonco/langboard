from typing import Any, TypeVar
from ....core.db import BaseDbModel, DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....domain.models.bases import BaseMetadataModel
from ....helpers import InfraHelper


_TMetadata = TypeVar("_TMetadata", bound=BaseMetadataModel)


class MetadataRepository(BaseRepository):
    @staticmethod
    def name() -> str:
        return "metadata"

    def get_list(self, model_cls: type[_TMetadata], foreign_model: BaseDbModel) -> list[_TMetadata]:
        foreign_key = self.__get_foreign_key(foreign_model)
        if foreign_key not in model_cls.model_fields:
            return []

        metadata_list = InfraHelper.get_all_by(model_cls, foreign_key, foreign_model.id)
        return metadata_list

    def get_by_key(self, model_cls: type[_TMetadata], foreign_model: BaseDbModel, key: str) -> _TMetadata | None:
        foreign_key = self.__get_foreign_key(foreign_model)
        if foreign_key not in model_cls.model_fields:
            return None

        metadata = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(model_cls).where(
                    (model_cls.column(foreign_key) == foreign_model.id) & (model_cls.column("key") == key)
                )
            )
            metadata = result.first()

        return metadata

    def get_by_foreign_ids_and_key(
        self, model_cls: type[_TMetadata], foreign_key: str, foreign_ids: list[int], key: str
    ) -> list[_TMetadata]:
        if foreign_key not in model_cls.model_fields or not foreign_ids:
            return []

        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(model_cls).where(
                    (model_cls.column(foreign_key).in_(foreign_ids)) & (model_cls.column("key") == key)
                )
            )
            return list(result.all())

    def get_by_foreign_ids(
        self, model_cls: type[_TMetadata], foreign_key: str, foreign_ids: list[int]
    ) -> list[_TMetadata]:
        if foreign_key not in model_cls.model_fields or not foreign_ids:
            return []

        with DbSession.use(readonly=True) as db:
            result = db.exec(SqlBuilder.select.table(model_cls).where(model_cls.column(foreign_key).in_(foreign_ids)))
            return list(result.all())

    def save(
        self, model_cls: type[_TMetadata], foreign_model: BaseDbModel, key: str, value: str, old_key: str | None = None
    ) -> _TMetadata | None:
        foreign_key = self.__get_foreign_key(foreign_model)
        if foreign_key not in model_cls.model_fields:
            return None

        metadata = None
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(model_cls).where(
                    (model_cls.column(foreign_key) == foreign_model.id) & (model_cls.column("key") == (old_key or key))
                )
            )
            metadata = result.first()

        with DbSession.use(readonly=False) as db:
            if not metadata:
                params: dict[str, Any] = {
                    "key": key,
                    "value": value,
                }
                params[foreign_key] = foreign_model.id
                metadata = model_cls(**params)
                db.insert(metadata)
            else:
                metadata.key = key
                metadata.value = value
                db.update(metadata)

        return metadata

    def delete(self, model_cls: type[_TMetadata], foreign_model: BaseDbModel, keys: str | list[str]) -> bool:
        foreign_key = self.__get_foreign_key(foreign_model)
        if foreign_key not in model_cls.model_fields:
            return False

        if isinstance(keys, str):
            keys = [keys]

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(model_cls).where(
                    (model_cls.column(foreign_key) == foreign_model.id) & (model_cls.column("key").in_(keys))
                )
            )

        return True

    def __get_foreign_key(self, foreign_model: BaseDbModel) -> str:
        return f"{foreign_model.__tablename__}_id"
