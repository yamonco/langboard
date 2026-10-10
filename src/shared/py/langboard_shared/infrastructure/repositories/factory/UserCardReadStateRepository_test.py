"""Executable checks for existing read-cursor reuse and explicit unread override.

Run with python3 UserCardReadStateRepository_test.py. Transaction doubles do not
replace authenticated database and browser verification.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from types import SimpleNamespace


def check():
    source = ast.parse(Path(__file__).with_name("UserCardReadStateRepository.py").read_text())
    method = next(node for node in next(node for node in source.body if isinstance(node, ast.ClassDef)).body
                  if isinstance(node, ast.FunctionDef) and node.name == "set_read_state")
    method = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    class Query:
        def table(self, target): self.target = target; return self
        def where(self, condition): return self
        def with_for_update(self): return self
    class Model:
        @staticmethod
        def column(name): return 0
    class State(Model):
        def __init__(self, **values): self.__dict__.update(values)
    class Database:
        state = None
        writes = 0
        def exec(self, query): return SimpleNamespace(first=lambda: card if query.target is Model else self.state)
        def insert(self, state): self.state = state; self.writes += 1
        def update(self, state): self.state = state
    database = Database()
    lock = RLock()
    @contextmanager
    def atomic():
        with lock: yield database
    card = SimpleNamespace(id=4, last_change_seq=12)
    namespace = dict(TUserParam=object, Card=Model, UserCardReadState=State,
        InfraHelper=SimpleNamespace(convert_id=lambda user: user),
        DbSession=SimpleNamespace(atomic=atomic), SqlBuilder=SimpleNamespace(select=Query()),
        SafeDateTime=SimpleNamespace(now=lambda: "now"))
    exec(compile(method, "read-cursor", "exec"), namespace)
    setter = namespace["set_read_state"]
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(lambda _: setter(None, 9, card, True), range(32)))
    assert database.writes == 1 and database.state.seen_change_seq == 12
    setter(None, 9, card, False)
    assert database.state.seen_change_seq == -1
    # Explicit unread must win even when the project baseline covers the card.
    baseline = 100
    assert database.state.seen_change_seq < 0 or card.last_change_seq > max(database.state.seen_change_seq, baseline)
    setter(None, 9, card, True)
    assert database.state.seen_change_seq == 12
    card.last_change_seq = 11
    setter(None, 9, card, True)
    assert database.state.seen_change_seq == 12
    print("read cursor checks passed: concurrent create, unread override, reopen, monotonic cursor")


if __name__ == "__main__":
    check()
