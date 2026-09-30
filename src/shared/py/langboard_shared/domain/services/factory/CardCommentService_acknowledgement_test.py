"""Exercise acknowledgement command/projection boundaries without a broker."""
import ast
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
import unittest


def load_service():
    source = ast.parse(Path(__file__).with_name("CardCommentService.py").read_text())
    cls = next(node for node in source.body if isinstance(node, ast.ClassDef))
    cls.bases = []
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in {
        "set_acknowledged", "convert_to_api_response", "toggle_reaction",
    }]
    lock = RLock()
    query = Mock()
    query.where.return_value = query
    query.with_for_update.return_value = query
    card = SimpleNamespace(id=2, project_id=1)
    comment = SimpleNamespace(id=3, card_id=2, deleted_at=None, api_response=lambda: {"uid": "comment"})
    db = Mock()
    db.exec.return_value.first.return_value = comment
    @contextmanager
    def atomic():
        with lock:
            yield db
    class User:
        def __init__(self, uid):
            self.uid = uid
        def api_response(self):
            return {"uid": self.uid}
    scope = {
        "User": User, "Project": object(), "Card": object(), "DbSession": SimpleNamespace(atomic=atomic),
        "InfraHelper": SimpleNamespace(get_records_with_foreign_by_params=Mock(
            return_value=(SimpleNamespace(id=1), card, comment))),
        "SqlBuilder": SimpleNamespace(select=SimpleNamespace(table=lambda _: query)),
        "CardComment": SimpleNamespace(column=lambda _: Mock()),
        "CardCommentReaction": object(), "COMMENT_ACKNOWLEDGEMENT": "acknowledged",
        "REACTION_TYPES": ["thumbs-up"], "CardCommentPublisher": SimpleNamespace(reacted=Mock()),
    }
    tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), "CardCommentService.py", "exec"), scope)
    service = scope["CardCommentService"]()
    acknowledged = set()
    def get_one(user, *_):
        return object() if user.uid in acknowledged else None
    def toggle(user, _, target, should_acknowledge, reaction, existing):
        assert target == comment.id and reaction == "acknowledged"
        (acknowledged.add if should_acknowledge else acknowledged.discard)(user.uid)
    service.repo = SimpleNamespace(reaction=SimpleNamespace(get_one=Mock(side_effect=get_one), toggle=Mock(side_effect=toggle)))
    service.get_as_api = lambda *_: {"acknowledged_user_uids": sorted(acknowledged)}
    return service, scope, query, comment, User


class CommentAcknowledgementTest(unittest.TestCase):
    def test_replays_and_parallel_same_user_acknowledgements_are_idempotent(self):
        service, scope, query, _, User = load_service()
        actor = User("member")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: service.set_acknowledged(actor, "board", "card", "comment", True), range(24)))
        self.assertEqual(service.repo.reaction.toggle.call_count, 1)
        self.assertEqual(scope["CardCommentPublisher"].reacted.call_count, 1)
        self.assertEqual(query.with_for_update.call_count, 24)
        self.assertEqual(service.get_as_api(), {"acknowledged_user_uids": ["member"]})
        for _ in range(2):
            self.assertEqual(service.set_acknowledged(actor, "board", "card", "comment", False), {"acknowledged_user_uids": []})
        self.assertEqual(service.repo.reaction.toggle.call_count, 2)
        self.assertEqual(scope["CardCommentPublisher"].reacted.call_count, 2)

    def test_foreign_deleted_and_nonuser_targets_never_write_and_projection_separates_emoji(self):
        service, scope, _, comment, User = load_service()
        actor = User("member")
        self.assertIsNone(service.set_acknowledged(object(), "board", "card", "comment", True))
        comment.card_id = 99
        self.assertIsNone(service.set_acknowledged(actor, "board", "card", "comment", True))
        comment.card_id = 2
        scope["DbSession"].atomic = Mock()
        scope["DbSession"].atomic.return_value.__enter__ = Mock(return_value=SimpleNamespace(exec=lambda _: SimpleNamespace(first=lambda: None)))
        scope["DbSession"].atomic.return_value.__exit__ = Mock(return_value=False)
        self.assertIsNone(service.set_acknowledged(actor, "board", "card", "comment", True))
        service.repo.reaction.toggle.assert_not_called()
        self.assertIsNone(service.toggle_reaction(actor, "board", "card", "comment", "acknowledged"))
        reactions = {"thumbs-up": ["member"], "acknowledged": ["member", "member"]}
        result = service.convert_to_api_response((comment, actor, None), reactions)
        self.assertEqual(result["acknowledged_user_uids"], ["member"])
        self.assertEqual(result["reactions"], {"thumbs-up": ["member"]})
        self.assertEqual(len(reactions["acknowledged"]), 2)


if __name__ == "__main__":
    unittest.main()
