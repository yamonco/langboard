from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from types import UnionType
from typing import Any, ClassVar, Literal, TypeVar, get_args, get_origin, overload
from pydantic import BaseModel, ConfigDict, SecretStr, model_serializer
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import configure_mappers, declared_attr, instrumentation, registry
from sqlalchemy.orm.attributes import InstrumentedAttribute
from ..types import SafeDateTime, SnowflakeID
from ..utils.StringCase import StringCase
from .ApiField import ApiField
from .ColumnTypes import DateTimeField, SnowflakeIDField
from .Field import Field, SqlFieldMetadata


_TColumnType = TypeVar("_TColumnType")

MODEL_METADATA = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_`%(constraint_name)s`",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)
default_registry = registry(metadata=MODEL_METADATA)


class BaseDbModel(ABC, BaseModel):
    """Base class for application models mapped with SQLAlchemy."""

    __db_table__: ClassVar[bool] = False
    __table_args__: ClassVar[tuple[Any, ...]] = ()
    __table__: ClassVar[Table]
    __pydantic_post_init__ = "model_post_init"
    metadata: ClassVar[MetaData] = MODEL_METADATA
    model_config = ConfigDict(arbitrary_types_allowed=True, from_attributes=True)

    id: SnowflakeID = SnowflakeIDField(primary_key=True, api_field=ApiField(name="uid"))
    created_at: SafeDateTime = DateTimeField(default=SafeDateTime.now, nullable=False, api_field=ApiField())
    updated_at: SafeDateTime = DateTimeField(
        default=SafeDateTime.now, nullable=False, onupdate=True, api_field=ApiField()
    )

    @property
    def __changes(self) -> dict[str, Any]:
        changes = getattr(self, "_changes", None)
        if changes is None:
            changes = {}
            object.__setattr__(self, "_changes", changes)
        return changes

    @property
    def changes(self) -> dict[str, Any]:
        """Get the changes made to the object."""
        if not isinstance(self, BaseDbModel) or not self.__changes:
            return {}
        return {**self.__changes}

    @property
    def changes_dict(self) -> dict[str, Any]:
        """Get the changed values as a dictionary if the object is a model."""
        if not isinstance(self, BaseDbModel) or not self.__changes:
            return {}
        changed_values = {}
        for key, value in self.__changes.items():
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            elif isinstance(value, BaseModel):
                value = value.model_dump()
            changed_values[key] = value
        return changed_values

    @declared_attr.directive
    def __tablename__(cls) -> str:
        return StringCase(cls.__name__).to_snake()

    def __str__(self) -> str:
        return self._repr(self._get_repr_keys())

    def __repr__(self) -> str:
        return str(self)

    def __eq__(self, target: object) -> bool:
        return isinstance(target, self.__class__) and self.id != 0 and self.id == target.id

    def __ne__(self, target: object) -> bool:
        return not self.__eq__(target)

    def __init_subclass__(cls, table: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if table:
            cls.__db_table__ = True
        elif "__db_table__" not in cls.__dict__:
            cls.__db_table__ = False

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        if cls.__db_table__:
            cls.__map_table()

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_sa_instance_state":
            if not hasattr(self, "_initiated"):
                object.__setattr__(self, "_initiated", True)
            object.__setattr__(self, name, value)
            return

        if not isinstance(self, BaseDbModel) or not hasattr(self, "_initiated") or name == "_initiated":
            super().__setattr__(name, value)
            return

        if not self.is_new() and name in self.model_fields.keys():
            old_value = getattr(self, name)
            if old_value != value:
                if name not in self.__changes:
                    self.__changes[name] = old_value
                elif self.__changes[name] == value:
                    del self.__changes[name]
        super().__setattr__(name, value)

    @classmethod
    def column(cls, name: str, _: type[_TColumnType] | None = None) -> InstrumentedAttribute[_TColumnType]:
        """Cast a column to :class:`sqlalchemy.orm.attributes.InstrumentedAttribute`.

        E.g.::

            ModelClass.column("column_name")
            User.column("id")
            ModelClass.column("column_name", int)
            User.column("id", int | None)

        :param name: The column name existing in the model.
        :param _: The type of the column. If provided, it will be assigned to :class:`sqlalchemy.orm.attributes.InstrumentedAttribute`.
        """
        if not isinstance(cls, type) or not issubclass(cls, BaseDbModel):  # type: ignore
            return None  # type: ignore
        column = getattr(cls, name, None)
        if column is None:
            raise ValueError(f"Column {name} not found in {cls.__name__}")
        if not isinstance(column, InstrumentedAttribute):
            raise ValueError(f'Must use {cls.__name__}.column("{name}")')
        return column

    @classmethod
    def expr(cls, name: str) -> str:
        """Get the column expression from a model column.

        E.g.::

            ModelClass.expr("column_name")
            User.expr("id")

        :param name: The column name existing in the model.
        """
        column = cls.column(name)
        if column is None:
            return name
        return str(column.expression)

    def model_post_init(self, *args: Any, **kwargs: Any) -> None:
        if self.__db_table__:
            instrumentation.manager_of_class(type(self)).setup_instance(self)
        object.__setattr__(self, "_changes", {})
        object.__setattr__(self, "_initiated", True)

    def is_new(self) -> bool:
        """Checks if the object is new and has not been saved to the database."""
        if not isinstance(self, BaseDbModel):
            return False
        return self.id == 0

    def get_uid(self) -> str:
        """Get the short code of the object's ID."""
        if not isinstance(self, BaseDbModel):
            return ""
        if not isinstance(self.id, SnowflakeID) and isinstance(self.id, int):
            return SnowflakeID(self.id).to_short_code()
        return self.id.to_short_code()

    def has_changes(self) -> bool:
        """Check if the object has changes."""
        if not isinstance(self, BaseDbModel) or not self.__changes:
            return False
        return bool(self.__changes)

    def clear_changes(self) -> None:
        """Clear the changes made to the object."""
        if not isinstance(self, BaseDbModel) or not self.__changes:
            return
        self.__changes.clear()

    @model_serializer
    def serialize(self) -> dict[str, Any]:
        serialized = {}
        for key in self.model_fields:
            value = getattr(self, key)
            if isinstance(value, datetime):
                value = value.isoformat()
                if not value.count("+"):
                    value = f"{value}+00:00"
            elif isinstance(value, SecretStr):
                value = value.get_secret_value()
            serialized[key] = value
        return serialized

    @classmethod
    def api_schema(cls, schema: dict | None = None, **kwargs) -> dict[str, Any]:
        return {
            **ApiField.create_schema(cls, **kwargs),
            **(schema or {}),
        }

    def api_response(self, **kwargs) -> dict[str, Any]:
        return ApiField.convert(self, **kwargs)

    @abstractmethod
    def notification_data(self) -> dict[str, Any]: ...

    @overload
    @classmethod
    def get_foreign_models(cls) -> dict[str, type["BaseDbModel"]]: ...
    @overload
    @classmethod
    def get_foreign_models(cls, opposite: Literal[False]) -> dict[str, type["BaseDbModel"]]: ...
    @overload
    @classmethod
    def get_foreign_models(cls, opposite: Literal[True]) -> dict[type["BaseDbModel"], set[str]]: ...
    @classmethod
    def get_foreign_models(
        cls, opposite: bool = False
    ) -> dict[str, type["BaseDbModel"]] | dict[type["BaseDbModel"], set[str]]:
        foreign_models = {}
        for field_name, field in cls.model_fields.items():
            sql_extra = cls.__get_field_sql_metadata(field)
            if "foreign_table" not in sql_extra:
                continue

            foreign_table = sql_extra["foreign_table"]
            if not isinstance(foreign_table, type) or not issubclass(foreign_table, BaseDbModel):
                continue

            if opposite:
                if foreign_table not in foreign_models:
                    foreign_models[foreign_table] = set()
                foreign_models[foreign_table].add(field_name)
            else:
                foreign_models[field_name] = foreign_table

        return foreign_models

    @abstractmethod
    def _get_repr_keys(self) -> list[str | tuple[str, str]]: ...

    def _repr(self, representable_keys: list[str | tuple[str, str]]) -> str:
        chunks = []
        if not self.is_new():
            chunks.append(f"id={self.id}")

        for representable in representable_keys:
            if isinstance(representable, tuple):
                key, repr_key = representable
            else:
                key = repr_key = representable

            if key == "id":
                continue

            value = getattr(self, key)
            if value is not None:
                chunks.append(f"{repr_key}={value}")

        if hasattr(self, "deleted_at") and getattr(self, "deleted_at") is not None:
            chunks.append(f"deleted_at={getattr(self, 'deleted_at')}")

        info = ", ".join(chunks)
        return f"{self.__class__.__name__}({info})"

    @classmethod
    def __map_table(cls) -> None:
        columns = []
        for field_name, field in cls.model_fields.items():
            columns.append(cls.__create_column(field_name, field))

        table = default_registry.metadata.tables.get(cls.__tablename__)
        if table is None:
            table_args = [*cls.__table_args__, *cls.__create_unique_constraints()]
            table = Table(cls.__tablename__, default_registry.metadata, *columns, *table_args)

        default_registry.map_imperatively(cls, table)
        configure_mappers()

    @classmethod
    def __create_unique_constraints(cls) -> list[UniqueConstraint]:
        constraints: list[UniqueConstraint] = []
        unique_groups: dict[str, list[str]] = {}

        for field_name, field in cls.model_fields.items():
            sql_extra = cls.__get_field_sql_metadata(field)
            if not isinstance(sql_extra, dict):
                continue

            unique = cls.__get_sql_value(sql_extra, "unique")
            index = cls.__get_sql_value(sql_extra, "index")
            if unique is True and index is True:
                constraints.append(UniqueConstraint(field_name))

            groups = cls.__get_sql_value(sql_extra, "unique_groups", ())
            if groups is PydanticUndefined:
                continue

            for group in groups:
                unique_groups.setdefault(group, []).append(field_name)

        for group, columns in unique_groups.items():
            constraints.append(UniqueConstraint(*columns, name=f"uq_{cls.__tablename__}_{group}"))

        return constraints

    @classmethod
    def __create_column(cls, field_name: str, field: FieldInfo) -> Column:
        sql_extra = cls.__get_field_sql_metadata(field)
        if not isinstance(sql_extra, dict):
            sql_extra = {}

        sa_column = sql_extra.get("sa_column", PydanticUndefined)
        if sa_column is not PydanticUndefined:
            return sa_column

        column_args = list(cls.__get_sql_value(sql_extra, "sa_column_args", []))
        column_kwargs = dict(cls.__get_sql_value(sql_extra, "sa_column_kwargs", {}))
        foreign_key = cls.__get_sql_value(sql_extra, "foreign_key")
        if foreign_key is not PydanticUndefined:
            ondelete = cls.__get_sql_value(sql_extra, "ondelete")
            foreign_key_kwargs = {"ondelete": ondelete} if ondelete is not PydanticUndefined else {}
            column_args.insert(0, ForeignKey(foreign_key, **foreign_key_kwargs))

        primary_key = cls.__get_sql_value(sql_extra, "primary_key")
        if primary_key is not PydanticUndefined:
            column_kwargs.setdefault("primary_key", bool(primary_key))

        unique = cls.__get_sql_value(sql_extra, "unique")
        if unique is not PydanticUndefined:
            column_kwargs.setdefault("unique", bool(unique))

        index = cls.__get_sql_value(sql_extra, "index")
        if index is not PydanticUndefined:
            column_kwargs.setdefault("index", bool(index))

        nullable = cls.__get_sql_value(sql_extra, "nullable")
        if nullable is not PydanticUndefined:
            column_kwargs.setdefault("nullable", bool(nullable))
        elif not column_kwargs.get("primary_key"):
            column_kwargs.setdefault("nullable", cls.__is_nullable_field(field))

        return Column(field_name, cls.__get_column_type(field, sql_extra), *column_args, **column_kwargs)

    @staticmethod
    def __get_sql_value(sql_extra: dict[str, Any], key: str, default: Any = PydanticUndefined) -> Any:
        value = sql_extra.get(key, default)
        return default if value is PydanticUndefined else value

    @staticmethod
    def __get_field_sql_metadata(field: FieldInfo) -> dict[str, Any]:
        for metadata in field.metadata:
            if isinstance(metadata, SqlFieldMetadata):
                return metadata.values
        return {}

    @classmethod
    def __get_column_type(cls, field: FieldInfo, sql_extra: dict[str, Any]) -> Any:
        sa_type = cls.__get_sql_value(sql_extra, "sa_type")
        if sa_type is not PydanticUndefined:
            return sa_type

        annotation = cls.__unwrap_annotation(field.annotation)
        if annotation is str:
            return String
        if annotation is int or annotation is SnowflakeID:
            return Integer
        if annotation is bool:
            return Boolean
        if annotation is float:
            return Float
        if annotation is datetime or annotation is SafeDateTime:
            return DateTime(timezone=True)
        if annotation is dict or get_origin(annotation) is dict:
            return JSON
        if annotation is list or get_origin(annotation) is list:
            return JSON
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            return String
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return JSON
        return String

    @staticmethod
    def __unwrap_annotation(annotation: Any) -> Any:
        origin = get_origin(annotation)
        if origin is UnionType or origin is None and isinstance(annotation, UnionType):
            args = [arg for arg in get_args(annotation) if arg is not type(None)]
            return args[0] if args else annotation
        if origin is not None and type(None) in get_args(annotation):
            args = [arg for arg in get_args(annotation) if arg is not type(None)]
            return args[0] if args else annotation
        return annotation

    @classmethod
    def __is_nullable_field(cls, field: FieldInfo) -> bool:
        if field.default is None:
            return True
        return type(None) in get_args(field.annotation)


class SoftDeleteModel(BaseDbModel):
    """Base model for soft-deleting objects in the database inherited from :class:`BaseDbModel`."""

    deleted_at: SafeDateTime | None = DateTimeField(default=None, nullable=True)


class EditorContentModel(BaseModel):
    content: str = Field(default="", description="The content of the editor in markdown format.")

    @staticmethod
    def api_schema() -> dict[str, Any]:
        return {"content": "string"}


class ChatContentModel(BaseModel):
    content: str = Field(default="")
    graph_interrupt: dict[str, Any] | None = Field(default=None)
    graph_resume_error: str | None = Field(default=None)

    @staticmethod
    def api_schema() -> dict[str, Any]:
        return {"content": "string", "graph_interrupt": "object", "graph_resume_error": "string"}
