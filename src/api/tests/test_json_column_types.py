"""Regression tests for native JSON column serialization."""

# ruff: noqa: E402, I001

import os

os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.db.ColumnTypes import ModelColumnListType, ModelColumnType


def test_model_column_type_returns_native_json_value() -> None:
    """A JSON column must receive an object, not an already encoded string."""

    column = ModelColumnType(EditorContentModel)()

    assert column.process_bind_param(EditorContentModel(content="plain markdown"), None) == {
        "content": "plain markdown"
    }


def test_model_column_type_still_reads_legacy_encoded_json() -> None:
    """Rows written by the old double-encoding path remain readable."""

    column = ModelColumnType(EditorContentModel)()

    assert column.process_result_value('{"content":"legacy"}', None) == EditorContentModel(
        content="legacy"
    )


def test_model_column_list_type_returns_native_json_array() -> None:
    """A JSON list column must receive an array rather than encoded text."""

    column = ModelColumnListType(EditorContentModel)()

    assert column.process_bind_param([EditorContentModel(content="one")], None) == [
        {"content": "one"}
    ]
