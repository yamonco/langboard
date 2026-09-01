from contextlib import contextmanager
from enum import Enum
from time import sleep
from typing import Any, ClassVar, Dict, Generic, Iterable, Mapping, Optional, Sequence, TypeVar, Union, cast, overload
from pydantic import ValidationError
from sqlalchemy import CompoundSelect, Delete, Insert, Update, delete, insert, update
from sqlalchemy import Sequence as SqlSequence
from sqlalchemy.engine import Result as SQLAlchemyResult
from sqlalchemy.engine.row import Row
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.sql.base import Executable
from sqlalchemy.util import EMPTY_DICT
from ...Env import Env
from ..logger import Logger
from ..types import SafeDateTime, SnowflakeID
from .DbEngine import DbEngine
from .Models import BaseDbModel, SoftDeleteModel
from .queries.Select import SelectOfScalar, SelectRows


_TRow = TypeVar("_TRow", bound=tuple[Any, ...])
_TSelectParam = TypeVar("_TSelectParam")
_TResult = TypeVar("_TResult")
_TDmlParam = TypeVar("_TDmlParam")


class Result(Generic[_TResult]):
    __model_field_names: ClassVar[dict[type[BaseDbModel], tuple[str, ...]]] = {}
    __model_field_sets: ClassVar[dict[type[BaseDbModel], set[str]]] = {}

    def __init__(self, records: Sequence[Any]):
        self.__records = self.__prepare_records(records)

    def all(self) -> list[_TResult]:
        return self.__records

    def first(self) -> Optional[_TResult]:
        return self.__records[0] if self.__records else None

    def __prepare_records(self, records: Sequence[Any]) -> list[Any]:
        prepared = records if isinstance(records, list) else list(records)
        for index, record in enumerate(prepared):
            prepared[index] = self.__prepare_record(record)
        return prepared

    def __prepare_record(self, record: Any):
        if isinstance(record, BaseDbModel):
            return self.__prepare_model(record)
        if isinstance(record, (tuple, Row)):
            return self.__prepare_tuple_record(tuple(record))
        return record

    def __prepare_tuple_record(self, record: tuple) -> tuple:
        return tuple(self.__prepare_model(item) if isinstance(item, BaseDbModel) else item for item in record)

    def __prepare_model(self, record: BaseDbModel) -> BaseDbModel:
        model_cls = record.__class__
        field_set = self.__get_model_field_set(model_cls)
        return self.__prepare_model_with_fields(record, field_set)

    def __prepare_model_with_fields(self, record: BaseDbModel, field_set: set[str]) -> BaseDbModel:
        if not hasattr(record, "__pydantic_fields_set__"):
            object.__setattr__(record, "__pydantic_fields_set__", field_set.copy())
        if not hasattr(record, "__pydantic_extra__"):
            object.__setattr__(record, "__pydantic_extra__", None)
        if not hasattr(record, "__pydantic_private__"):
            object.__setattr__(record, "__pydantic_private__", None)
        object.__setattr__(record, "_initiated", True)
        record.clear_changes()
        return record

    @classmethod
    def __get_model_field_names(cls, model_cls: type[BaseDbModel]) -> tuple[str, ...]:
        field_names = cls.__model_field_names.get(model_cls)
        if field_names is None:
            field_names = tuple(model_cls.model_fields)
            cls.__model_field_names[model_cls] = field_names
        return field_names

    @classmethod
    def __get_model_field_set(cls, model_cls: type[BaseDbModel]) -> set[str]:
        field_set = cls.__model_field_sets.get(model_cls)
        if field_set is None:
            field_set = set(cls.__get_model_field_names(model_cls))
            cls.__model_field_sets[model_cls] = field_set
        return field_set


_logger = Logger.use("db")


class DbSession:
    """Manages the database sessions.

    The purpose of this class is to provide a single interface for multiple database sessions.
    """

    def __init__(self, session: Session, readonly: bool):
        self.__session = session
        self.__readonly = readonly

    @staticmethod
    @contextmanager
    def use(readonly: bool):
        session = None
        db = None
        try:
            engine = DbEngine.get_readonly_engine() if readonly else DbEngine.get_main_engine()
            with Session(engine, expire_on_commit=False) as db_session:
                db = DbSession(db_session, readonly=readonly)
                session = db_session
                if readonly:
                    yield db
                else:
                    with db_session.begin():
                        yield db
        except Exception as e:
            _logger.exception(e)
            raise
        finally:
            if db:
                db.close()
                db = None
            if session:
                session.close()
                session = None

    def close(self):
        self.__session = cast(Session, None)
        self.__readonly = True

    def insert(self, obj: BaseDbModel):
        """Inserts a new object into the database if it is new.

        :param obj: The object to be inserted; must be a subclass of :class:`BaseDbModel`.
        """
        if self.__readonly:
            raise Exception("Cannot insert into a readonly database")

        if not obj.is_new():
            return

        obj.id = SnowflakeID()
        obj.updated_at = obj.created_at
        self.__session.execute(insert(obj.__table__).values(self.__get_model_column_values(obj)))  # type: ignore[attr-defined]

    def insert_all(self, objs: Iterable[BaseDbModel]):
        """Inserts new objects into the database if they are new.

        :param objs: The objects to be inserted; must be a subclass of :class:`BaseDbModel`.
        """
        if self.__readonly:
            raise Exception("Cannot insert into a readonly database")

        for obj in objs:
            self.insert(obj)

    def update(self, obj: BaseDbModel):
        """Updates an object in the database if it is not new.

        :param obj: The object to be updated; must be a subclass of :class:`BaseDbModel`.
        """
        if self.__readonly:
            raise Exception("Cannot update in a readonly database")

        if obj.is_new() or not obj.has_changes():
            return

        obj.updated_at = SafeDateTime.now()
        values = self.__get_model_column_values(obj, exclude={"id", "created_at"})
        self.__session.execute(
            update(obj.__table__).where(obj.__table__.c.id == obj.id).values(values)  # type: ignore[attr-defined]
        )
        obj.clear_changes()

    @overload
    def delete(self, obj: BaseDbModel): ...
    @overload
    def delete(self, obj: SoftDeleteModel, purge: bool = False): ...
    def delete(self, obj: BaseDbModel, purge: bool = False):
        """Deletes an object from the database if it is not new.

        If the object is a subclass of :class:`SoftDeleteModel`, it will be soft-deleted by default.

        :param obj: The object to be deleted; must be a subclass of :class:`BaseDbModel`.
        :param purge: If `True`, the object will be hard-deleted for subclasses of :class:`SoftDeleteModel`.
        """
        if self.__readonly:
            raise Exception("Cannot delete from a readonly database")

        if obj.is_new():
            return

        if purge or not isinstance(obj, SoftDeleteModel):
            self.__session.execute(delete(obj.__table__).where(obj.__table__.c.id == obj.id))  # type: ignore[attr-defined]
            obj.clear_changes()
            return

        if obj.deleted_at is not None:
            return

        obj.deleted_at = SafeDateTime.now()
        obj.updated_at = SafeDateTime.now()
        self.__session.execute(
            update(obj.__table__)  # type: ignore[attr-defined]
            .where(obj.__table__.c.id == obj.id)  # type: ignore[attr-defined]
            .values(
                {
                    "deleted_at": obj.deleted_at,
                    "updated_at": obj.updated_at,
                }
            )
        )
        obj.clear_changes()

    @overload
    def exec(
        self,
        statement: SelectOfScalar[_TSelectParam],
        *,
        params: Optional[Union[Mapping[str, Any], SqlSequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
    ) -> Result[_TSelectParam]: ...
    @overload
    def exec(
        self,
        statement: SelectRows[_TRow],
        *,
        params: Optional[Union[Mapping[str, Any], SqlSequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
    ) -> Result[_TRow]: ...
    @overload
    def exec(
        self,
        statement: CompoundSelect[_TRow],
        *,
        params: Optional[Union[Mapping[str, Any], SqlSequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
    ) -> Result[_TRow]: ...
    @overload
    def exec(
        self,
        statement: Insert | Insert[_TDmlParam],
        *,
        params: Optional[Union[Mapping[str, Any], SqlSequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
    ) -> int: ...
    @overload
    def exec(
        self,
        statement: Update | Update[_TDmlParam],
        *,
        params: Optional[Union[Mapping[str, Any], SqlSequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
    ) -> int: ...
    @overload
    def exec(
        self,
        statement: Delete | Delete[_TDmlParam],
        *,
        params: Optional[Union[Mapping[str, Any], SqlSequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
        purge: bool = False,
    ) -> int: ...
    def exec(  # type: ignore
        self,
        statement: Union[
            SelectOfScalar[_TSelectParam],
            SelectRows[_TRow],
            CompoundSelect[_TRow],
            Executable,
        ],
        *,
        params: Optional[Union[Mapping[str, Any], SqlSequence[Mapping[str, Any]]]] = None,
        execution_options: Mapping[str, Any] = EMPTY_DICT,
        bind_arguments: Optional[Dict[str, Any]] = None,
        _parent_execute_state: Optional[Any] = None,
        _add_event: Optional[Any] = None,
        purge: bool = False,
    ) -> Result[_TSelectParam] | Result[_TRow] | int:
        """Executes a statement on the database.

        If the statement is a :class:`Delete` and the table is a subclass of :class:`SoftDeleteModel`,
        the statement will be converted to an :class:`Update` that sets the `deleted_at` column to the current time.
        However, if `purge` is `True`, the statement will be executed as a :class:`Delete`.

        :param statement: The statement to be executed.
        :param params: The parameters to be passed to the statement.
        :param purge: If `True`, the statement will be executed as a :class:`Delete`; Only applicable to :param:`statement` of type :class:`Delete`.
        :param execution_options: The execution options to be passed to the statement.
        :param bind_arguments: The bind arguments to be passed to the statement.
        :param _parent_execute_state: The parent execute state to be passed to the statement.
        :param _add_event: The event to be added to the statement.
        """
        if (
            isinstance(statement, Delete)
            and (
                isinstance(statement.table.entity_namespace, type)
                and issubclass(statement.table.entity_namespace, SoftDeleteModel)
            )
            and not purge
        ):
            statement = update(statement.table).values(deleted_at=SafeDateTime.now()).where(statement.whereclause)  # type: ignore

        should_return_count = not isinstance(statement, Select) and not isinstance(statement, CompoundSelect)

        if self.__readonly and should_return_count:
            raise Exception("Cannot execute non-select statements in a readonly database")

        args = {
            "statement": statement,
            "params": params,
            "execution_options": execution_options,
            "bind_arguments": bind_arguments,
            "_parent_execute_state": _parent_execute_state,
            "_add_event": _add_event,
        }

        if should_return_count:
            result = self.__session.execute(**args)
            rowcount = getattr(result, "rowcount", None)
            return rowcount if isinstance(rowcount, int) and rowcount >= 0 else 0

        select_statement = cast(SelectOfScalar[_TSelectParam] | SelectRows[_TRow] | CompoundSelect[_TRow], statement)
        return self.__exec_select(select_statement, args)

    @overload
    def __exec_select(
        self, statement: SelectOfScalar[_TSelectParam], args: dict[str, Any]
    ) -> Result[_TSelectParam]: ...
    @overload
    def __exec_select(
        self, statement: SelectRows[_TRow] | CompoundSelect[_TRow], args: dict[str, Any]
    ) -> Result[_TRow]: ...
    def __exec_select(
        self,
        statement: SelectOfScalar[_TSelectParam] | SelectRows[_TRow] | CompoundSelect[_TRow],
        args: dict[str, Any],
    ) -> Result[_TSelectParam] | Result[_TRow]:
        last_error: Exception | None = None
        retry_attempts = max(1, Env.DB_SELECT_RETRY_ATTEMPTS)

        for attempt in range(retry_attempts):
            try:
                if attempt == 0:
                    return self.__fetch_select_records(statement, self.__session, args, self.__readonly)
                return self.__exec_select_with_new_session(statement, args, self.__readonly)
            except (SQLAlchemyError, IndexError, ValidationError) as e:
                last_error = e
                if attempt < retry_attempts - 1:
                    _logger.warning(
                        f"Database select failed. Retrying with a new session ({attempt + 1}/{retry_attempts}): {e}"
                    )
                    sleep(min(0.1 * (attempt + 1), 0.5))
                    continue

        if self.__readonly and Env.DB_READONLY_FALLBACK_TO_MAIN:
            try:
                _logger.warning(
                    f"Readonly database select failed after {retry_attempts} attempts. "
                    f"Retrying on main database: {last_error}"
                )
                return self.__exec_select_with_new_session(statement, args, readonly=False)
            except (SQLAlchemyError, IndexError, ValidationError):
                pass

        if last_error:
            raise last_error

        raise RuntimeError("Database select failed without an error")

    @overload
    def __exec_select_with_new_session(
        self, statement: SelectOfScalar[_TSelectParam], args: dict[str, Any], readonly: bool
    ) -> Result[_TSelectParam]: ...
    @overload
    def __exec_select_with_new_session(
        self, statement: SelectRows[_TRow] | CompoundSelect[_TRow], args: dict[str, Any], readonly: bool
    ) -> Result[_TRow]: ...
    def __exec_select_with_new_session(
        self,
        statement: SelectOfScalar[_TSelectParam] | SelectRows[_TRow] | CompoundSelect[_TRow],
        args: dict[str, Any],
        readonly: bool,
    ) -> Result[_TSelectParam] | Result[_TRow]:
        engine = DbEngine.get_readonly_engine() if readonly else DbEngine.get_main_engine()
        with Session(engine, expire_on_commit=False) as db_session:
            if readonly:
                return self.__fetch_select_records(statement, db_session, args, readonly)
            with db_session.begin():
                return self.__fetch_select_records(statement, db_session, args, readonly)

    @overload
    def __fetch_select_records(
        self,
        statement: SelectOfScalar[_TSelectParam],
        session: Session,
        args: dict[str, Any],
        readonly: bool,
    ) -> Result[_TSelectParam]: ...
    @overload
    def __fetch_select_records(
        self,
        statement: SelectRows[_TRow] | CompoundSelect[_TRow],
        session: Session,
        args: dict[str, Any],
        readonly: bool,
    ) -> Result[_TRow]: ...
    def __fetch_select_records(
        self,
        statement: SelectOfScalar[_TSelectParam] | SelectRows[_TRow] | CompoundSelect[_TRow],
        session: Session,
        args: dict[str, Any],
        readonly: bool,
    ) -> Result[_TSelectParam] | Result[_TRow]:
        result = session.execute(**args)
        if not isinstance(result, SQLAlchemyResult):
            raise TypeError(f"Unexpected result type: {type(result)}")
        if self.__should_return_scalars(statement):
            records = result.scalars().all()
        else:
            records = result.all()
        if readonly and session.in_transaction():
            session.commit()
        return Result(records)

    def __get_model_column_values(self, obj: BaseDbModel, exclude: set[str] | None = None) -> dict[str, Any]:
        excluded = exclude or set()
        return {
            column.name: self.__get_column_value(getattr(obj, column.name))
            for column in obj.__table__.columns  # type: ignore[attr-defined]
            if column.name not in excluded
        }

    @staticmethod
    def __get_column_value(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        return value

    def __should_return_scalars(self, statement: Any) -> bool:
        return isinstance(statement, SelectOfScalar)
