import os
import pytest


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.db import EditorContentModel  # noqa: E402
from langboard_shared.domain.models import Card  # noqa: E402


def _card(description: str) -> Card:
    return Card(project_id=1, project_column_id=2, title="Card", description=EditorContentModel(content=description))


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("본문이 있습니다.", True),
        ("   ", False),
        ("", False),
    ],
)
def test_board_api_response_reports_has_description(description: str, expected: bool) -> None:
    """Board summaries expose body presence so the UI never reads full descriptions."""

    response = _card(description).board_api_response(0, [], [], [])
    assert response["has_description"] is expected
