from dataclasses import dataclass
from typing import AbstractSet, Any, Callable, Dict, Mapping, Optional, Sequence, Type, Union, overload
from pydantic import Field as PydanticField
from pydantic_core import PydanticUndefined as Undefined
from pydantic_core import PydanticUndefinedType as UndefinedType
from sqlalchemy import Column
from typing_extensions import Literal
from .ApiField import ApiField


NoArgAnyCallable = Callable[[], Any]
OnDeleteType = Literal["CASCADE", "SET NULL", "RESTRICT"]
ForeignKeyType = Union[str, UndefinedType]


@dataclass(frozen=True)
class SqlFieldMetadata:
    values: dict[str, Any]


# include sa_type, sa_column_args, sa_column_kwargs
@overload
def Field(
    default: Any = Undefined,
    *,
    default_factory: Optional[NoArgAnyCallable] = None,
    alias: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    api_field: Optional[ApiField] = None,
    exclude: Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any] = None,
    include: Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any] = None,
    const: Optional[bool] = None,
    gt: Optional[float] = None,
    ge: Optional[float] = None,
    lt: Optional[float] = None,
    le: Optional[float] = None,
    multiple_of: Optional[float] = None,
    max_digits: Optional[int] = None,
    decimal_places: Optional[int] = None,
    min_items: Optional[int] = None,
    max_items: Optional[int] = None,
    unique_items: Optional[bool] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    allow_mutation: bool = True,
    regex: Optional[str] = None,
    discriminator: Optional[str] = None,
    repr: bool = True,
    primary_key: Union[bool, UndefinedType] = Undefined,
    foreign_key: UndefinedType = Undefined,
    unique: Union[bool, UndefinedType] = Undefined,
    unique_groups: Union[Sequence[str], UndefinedType] = Undefined,
    nullable: Union[bool, UndefinedType] = Undefined,
    index: Union[bool, UndefinedType] = Undefined,
    sa_type: Union[Type[Any], UndefinedType] = Undefined,
    sa_column_args: Union[Sequence[Any], UndefinedType] = Undefined,
    sa_column_kwargs: Union[Mapping[str, Any], UndefinedType] = Undefined,
    schema_extra: Optional[Dict[str, Any]] = None,
) -> Any: ...


# When foreign_key is str, include ondelete
# include sa_type, sa_column_args, sa_column_kwargs
@overload
def Field(
    default: Any = Undefined,
    *,
    default_factory: Optional[NoArgAnyCallable] = None,
    alias: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    api_field: Optional[ApiField] = None,
    exclude: Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any] = None,
    include: Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any] = None,
    const: Optional[bool] = None,
    gt: Optional[float] = None,
    ge: Optional[float] = None,
    lt: Optional[float] = None,
    le: Optional[float] = None,
    multiple_of: Optional[float] = None,
    max_digits: Optional[int] = None,
    decimal_places: Optional[int] = None,
    min_items: Optional[int] = None,
    max_items: Optional[int] = None,
    unique_items: Optional[bool] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    allow_mutation: bool = True,
    regex: Optional[str] = None,
    discriminator: Optional[str] = None,
    repr: bool = True,
    primary_key: Union[bool, UndefinedType] = Undefined,
    foreign_key: str,
    ondelete: Union[OnDeleteType, UndefinedType] = Undefined,
    unique: Union[bool, UndefinedType] = Undefined,
    unique_groups: Union[Sequence[str], UndefinedType] = Undefined,
    nullable: Union[bool, UndefinedType] = Undefined,
    index: Union[bool, UndefinedType] = Undefined,
    sa_type: Union[Type[Any], UndefinedType] = Undefined,
    sa_column_args: Union[Sequence[Any], UndefinedType] = Undefined,
    sa_column_kwargs: Union[Mapping[str, Any], UndefinedType] = Undefined,
    schema_extra: Optional[Dict[str, Any]] = None,
) -> Any: ...


# Include sa_column, don't include
# primary_key
# foreign_key
# ondelete
# unique
# nullable
# index
# sa_type
# sa_column_args
# sa_column_kwargs
@overload
def Field(
    default: Any = Undefined,
    *,
    default_factory: Optional[NoArgAnyCallable] = None,
    alias: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    api_field: Optional[ApiField] = None,
    exclude: Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any] = None,
    include: Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any] = None,
    const: Optional[bool] = None,
    gt: Optional[float] = None,
    ge: Optional[float] = None,
    lt: Optional[float] = None,
    le: Optional[float] = None,
    multiple_of: Optional[float] = None,
    max_digits: Optional[int] = None,
    decimal_places: Optional[int] = None,
    min_items: Optional[int] = None,
    max_items: Optional[int] = None,
    unique_items: Optional[bool] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    allow_mutation: bool = True,
    regex: Optional[str] = None,
    discriminator: Optional[str] = None,
    repr: bool = True,
    sa_column: Union[Column[Any], UndefinedType] = Undefined,
    schema_extra: Optional[Dict[str, Any]] = None,
) -> Any: ...


def Field(
    default: Any = Undefined,
    *,
    default_factory: Optional[NoArgAnyCallable] = None,
    alias: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    api_field: Optional[ApiField] = None,
    exclude: Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any] = None,
    include: Union[AbstractSet[Union[int, str]], Mapping[Union[int, str], Any], Any] = None,
    const: Optional[bool] = None,
    gt: Optional[float] = None,
    ge: Optional[float] = None,
    lt: Optional[float] = None,
    le: Optional[float] = None,
    multiple_of: Optional[float] = None,
    max_digits: Optional[int] = None,
    decimal_places: Optional[int] = None,
    min_items: Optional[int] = None,
    max_items: Optional[int] = None,
    unique_items: Optional[bool] = None,
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    allow_mutation: bool = True,
    regex: Optional[str] = None,
    discriminator: Optional[str] = None,
    repr: bool = True,
    primary_key: Union[bool, UndefinedType] = Undefined,
    foreign_key: ForeignKeyType = Undefined,
    ondelete: Union[OnDeleteType, UndefinedType] = Undefined,
    unique: Union[bool, UndefinedType] = Undefined,
    unique_groups: Union[Sequence[str], UndefinedType] = Undefined,
    nullable: Union[bool, UndefinedType] = Undefined,
    index: Union[bool, UndefinedType] = Undefined,
    sa_type: Union[Type[Any], UndefinedType] = Undefined,
    sa_column: Union[Column, UndefinedType] = Undefined,  # type: ignore
    sa_column_args: Union[Sequence[Any], UndefinedType] = Undefined,
    sa_column_kwargs: Union[Mapping[str, Any], UndefinedType] = Undefined,
    schema_extra: Optional[Dict[str, Any]] = None,
) -> Any:
    schema_extra = schema_extra or {}
    if default is Undefined and default_factory is None and nullable is True:
        default = None

    json_schema_extra = schema_extra.pop("json_schema_extra", None)
    if not isinstance(json_schema_extra, dict):
        json_schema_extra = {}

    foreign_table = json_schema_extra.pop("foreign_table", Undefined)
    sql_metadata = {
        "primary_key": primary_key,
        "foreign_key": foreign_key if foreign_key is not Undefined else Undefined,
        "ondelete": ondelete,
        "unique": unique,
        "unique_groups": unique_groups,
        "nullable": nullable,
        "index": index,
        "sa_type": sa_type,
        "sa_column": sa_column,
        "sa_column_args": sa_column_args,
        "sa_column_kwargs": sa_column_kwargs,
        "foreign_table": foreign_table,
    }

    field_kwargs = {
        "default": default,
        "repr": repr,
        "json_schema_extra": json_schema_extra or None,
    }
    optional_field_kwargs = {
        "default_factory": default_factory,
        "alias": alias,
        "title": title,
        "description": description,
        "exclude": exclude,
        "gt": gt,
        "ge": ge,
        "lt": lt,
        "le": le,
        "multiple_of": multiple_of,
        "max_digits": max_digits,
        "decimal_places": decimal_places,
        "min_length": min_length if min_length is not None else min_items,
        "max_length": max_length if max_length is not None else max_items,
        "pattern": regex,
        "discriminator": discriminator,
    }
    field_kwargs.update({key: value for key, value in optional_field_kwargs.items() if value is not None})
    if allow_mutation is False:
        field_kwargs["frozen"] = True

    field = PydanticField(**field_kwargs)
    field.metadata.append(SqlFieldMetadata(sql_metadata))

    if api_field:
        field.metadata.append(api_field)
        api_field.assign_field(field)

    return field
