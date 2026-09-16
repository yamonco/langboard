from logging.config import fileConfig
from typing import Any
from alembic import context
from alembic.autogenerate.api import AutogenContext
from alembic.operations import ops
from langboard_shared.core.db import BaseDbModel
from langboard_shared.core.db.DbConfigHelper import DbConfigHelper  # type: ignore
from langboard_shared.Env import Env  # type: ignore
from langboard_shared.helpers import ensure_models_imported
from sqlalchemy import DateTime, pool
from sqlalchemy.engine import Connection, engine_from_config


ensure_models_imported()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

config.set_main_option("sqlalchemy.url", DbConfigHelper.get_sanitized_driver(Env.MAIN_DATABASE_URL))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = BaseDbModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def render_item(type_: str, obj: Any, autogen_context: AutogenContext):
    """Apply custom rendering for selected items."""
    if type_ == "type" and isinstance(obj, object):
        if obj.__class__.__name__ == "SecretStrType":
            autogen_context.imports.add(f"from {obj.__class__.__module__} import SecretStrType")
            return "SecretStrType"
        elif obj.__class__.__name__ == "_ModelColumnType":
            model_type_class: type = obj._model_type_class  # type: ignore
            autogen_context.imports.add(f"from {obj.__class__.__module__} import ModelColumnType")
            autogen_context.imports.add(f"from {model_type_class.__module__} import {model_type_class.__name__}")
            return f"ModelColumnType({model_type_class.__name__})"
        elif obj.__class__.__name__ == "_ModelColumnListType":
            model_type_class: type = obj._model_type_class  # type: ignore
            autogen_context.imports.add(f"from {obj.__class__.__module__} import ModelColumnListType")
            autogen_context.imports.add(f"from {model_type_class.__module__} import {model_type_class.__name__}")
            return f"ModelColumnListType({model_type_class.__name__})"
        elif obj.__class__.__name__ == "SnowflakeIDType":
            autogen_context.imports.add(f"from {obj.__class__.__module__} import SnowflakeIDType")
            return "SnowflakeIDType"
        elif obj.__class__.__name__ == "_CSVType":
            item_type_class: type = obj._item_type_class  # type: ignore
            autogen_context.imports.add(f"from {obj.__class__.__module__} import CSVType")
            if item_type_class is not str:
                autogen_context.imports.add(f"from {item_type_class.__module__} import {item_type_class.__name__}")
            return f"CSVType({item_type_class.__name__})"
        elif obj.__class__.__name__ == "_EnumLikeType":
            enum_type_class: type = obj._enum_type_class  # type: ignore
            autogen_context.imports.add(f"from {obj.__class__.__module__} import EnumLikeType")
            autogen_context.imports.add(f"from {enum_type_class.__module__} import {enum_type_class.__name__}")
            return f"EnumLikeType({enum_type_class.__name__})"

    return False


def compare_type(
    context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    if isinstance(inspected_type, DateTime) and isinstance(metadata_type, DateTime):
        return False
    return None


def __is_sqlite_id_column_noise(operation: ops.MigrateOperation) -> bool:
    if not isinstance(operation, ops.AlterColumnOp):
        return False
    if operation.column_name != "id":
        return False
    if operation.modify_type is not None:
        return False
    if operation.modify_name is not None:
        return False
    if operation.modify_server_default is not False:
        return False
    if operation.modify_comment is not False:
        return False

    # SQLite reflects BIGINT primary keys inconsistently around nullable and
    # autoincrement. Snowflake IDs are app-generated, so this is autogen noise.
    return operation.modify_nullable is not None or "autoincrement" in operation.kw


def __filter_sqlite_autogen_noise(container: ops.OpContainer) -> None:
    filtered_operations: list[ops.MigrateOperation] = []
    for operation in container.ops:
        if isinstance(operation, ops.OpContainer):
            __filter_sqlite_autogen_noise(operation)
            if not operation.ops:
                continue
        if __is_sqlite_id_column_noise(operation):
            continue
        filtered_operations.append(operation)
    container.ops = filtered_operations


def process_revision_directives(context: Any, revision: Any, directives: list[Any]) -> None:
    if DbConfigHelper.get_driver_type(Env.MAIN_DATABASE_URL) != "sqlite":
        return

    for directive in directives:
        __filter_sqlite_autogen_noise(directive.upgrade_ops)
        __filter_sqlite_autogen_noise(directive.downgrade_ops)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    driver_type = DbConfigHelper.get_driver_type(Env.MAIN_DATABASE_URL)
    render_as_batch = driver_type == "sqlite"

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
        compare_type=compare_type,
        process_revision_directives=process_revision_directives,
        render_as_batch=render_as_batch,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    driver_type = DbConfigHelper.get_driver_type(Env.MAIN_DATABASE_URL)
    render_as_batch = driver_type == "sqlite"

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        compare_type=compare_type,
        process_revision_directives=process_revision_directives,
        render_as_batch=render_as_batch,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
