"""Run publisher methods with transport doubles; no database or broker required."""

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest


class CardTimestampPublisherTest(unittest.TestCase):
    def test_details_nested_changes_and_moves_publish_the_persisted_timestamp(self):
        source = ast.parse(Path(__file__).with_name("CardPublisher.py").read_text())
        publisher_class = next(node for node in source.body if isinstance(node, ast.ClassDef))
        publisher_class.decorator_list = []
        scope = {
            "BaseSocketPublisher": object,
            "SocketPublishModel": lambda **fields: SimpleNamespace(**fields),
            "SocketTopic": SimpleNamespace(Board="board", BoardCard="card", Dashboard="dashboard"),
        }
        module = ast.Module(
            body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), publisher_class],
            type_ignores=[],
        )
        exec(compile(ast.fix_missing_locations(module), "CardPublisher.py", "exec"), scope)
        publisher = scope["CardPublisher"]
        publisher.put_dispather = Mock()
        timestamp = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
        card = SimpleNamespace(
            get_uid=lambda: "card", updated_at=timestamp, order=2, archived_at=None, source_type="internal",
            project_id=SimpleNamespace(to_short_code=lambda: "board"),
        )
        project = SimpleNamespace(get_uid=lambda: "board")
        original = {"title": "changed"}
        publisher.updated(project, card, None, original)
        model, events = publisher.put_dispather.call_args.args
        self.assertEqual(original, {"title": "changed"})
        self.assertEqual(model["updated_at"], timestamp.isoformat())
        self.assertIn("updated_at", events[0].data_keys)
        publisher.metadata_changed(card)
        model, event = publisher.put_dispather.call_args.args
        self.assertEqual(model, {"updated_at": timestamp.isoformat()})
        self.assertEqual(event.event, "board:card:details:changed:card")
        self.assertEqual(event.topic_id, "board")
        for destination in [None, SimpleNamespace(get_uid=lambda: "new", name="New")]:
            publisher.order_changed(project, card, SimpleNamespace(get_uid=lambda: "old"), destination)
            model, events = publisher.put_dispather.call_args.args
            self.assertEqual(model["updated_at"], timestamp.isoformat())
            for event in events:
                if event.event.startswith("board:card:order:") and getattr(event, "custom_data", {}).get("move_type") != "from_column":
                    self.assertIn("updated_at", event.data_keys)


if __name__ == "__main__":
    unittest.main()
