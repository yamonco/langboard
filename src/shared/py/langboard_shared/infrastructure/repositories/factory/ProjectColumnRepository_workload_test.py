"""Unfinished-work projection: real relational reads, scopes, and completion changes."""

from sqlalchemy import create_engine, event
from ....core.db import DbSession
from ....core.db.DbEngine import DbEngine
from ....core.types import SafeDateTime
from ....domain.models import Card, Checkitem, Checklist, Project, ProjectColumn, User
from .ProjectColumnRepository import ProjectColumnRepository


def test_workload_counts_scope_completion_and_changed_state(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (User, Project, ProjectColumn, Card, Checklist, Checkitem):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    with DbSession.use(readonly=False) as db:
        owner = User(firstname="Workload", lastname="Test", email="workload@example.invalid", password="test-only")
        db.insert(owner)
        project = Project(owner_id=owner.id, title="Visible")
        foreign = Project(owner_id=owner.id, title="Not requested")
        db.insert(project)
        db.insert(foreign)
        active = ProjectColumn(project_id=project.id, name="Done", workflow_stage="active")
        closed = ProjectColumn(project_id=project.id, name="Not named Done", workflow_stage="closed")
        archive = ProjectColumn(project_id=project.id, name="Archive", is_archive=True)
        legacy_done = ProjectColumn(project_id=project.id, name=" Done ")
        reference = ProjectColumn(project_id=project.id, name="Reference", workflow_stage="reference")
        foreign_column = ProjectColumn(project_id=foreign.id, name="Private")
        empty = ProjectColumn(project_id=project.id, name="Empty")
        deleted_column = ProjectColumn(project_id=project.id, name="Deleted", deleted_at=SafeDateTime.now())
        for column in (active, closed, archive, legacy_done, reference, foreign_column, empty, deleted_column):
            db.insert(column)

        def card(title, column=active, **fields):
            value = Card(project_id=project.id, project_column_id=column.id, title=title, **fields)
            db.insert(value)
            return value

        open_card = card("No checklist")
        partial = card("Partial")
        complete = card("Complete")
        empty_list = card("Empty list")
        deleted_items = card("Only deleted items")
        deleted_list = card("Only deleted list")
        card("Legacy completed", legacy_done)
        card("Closed", closed)
        card("Archived column", archive)
        card("Reference", reference)
        card("Archived timestamp", archived_at=SafeDateTime.now())
        card("Deleted card", deleted_at=SafeDateTime.now())
        card("Wiki", source_type=Card.LINKED_RESOURCE_PROJECT_WIKI, source_uid="wiki")
        card("Cross project column", foreign_column)
        db.insert(Card(project_id=foreign.id, project_column_id=active.id, title="Foreign card in visible column"))
        db.insert(Card(project_id=foreign.id, project_column_id=foreign_column.id, title="Foreign"))
        lists = []
        for value in (partial, complete, empty_list, deleted_items, deleted_list):
            entry = Checklist(
                card_id=value.id, title=value.title, deleted_at=SafeDateTime.now() if value is deleted_list else None
            )
            db.insert(entry)
            lists.append(entry)
        unchecked = Checkitem(checklist_id=lists[0].id, title="Unchecked")
        for item in (
            unchecked,
            Checkitem(checklist_id=lists[0].id, title="Checked", is_checked=True),
            Checkitem(checklist_id=lists[1].id, title="Completed", is_checked=True),
            Checkitem(checklist_id=lists[3].id, title="Deleted", is_checked=True, deleted_at=SafeDateTime.now()),
            Checkitem(checklist_id=lists[4].id, title="Deleted parent", is_checked=True),
        ):
            db.insert(item)
    repository = ProjectColumnRepository(lambda _: None, lambda _: None)
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    assert repository.get_incomplete_work_counts([]) == {}
    assert statements == []
    counts = repository.get_incomplete_work_counts([project])
    assert len(statements) == 1  # batched by authorized scope, never per project/card
    assert counts == {active.id: 5, closed.id: 0, archive.id: 0, legacy_done.id: 0, reference.id: 0, empty.id: 0}
    assert foreign_column.id not in counts and deleted_column.id not in counts
    event.remove(engine, "before_cursor_execute", record)
    with DbSession.use(readonly=False) as db:
        unchecked.is_checked = True
        db.update(unchecked)
    assert repository.get_incomplete_work_counts(project)[active.id] == 4
    with DbSession.use(readonly=False) as db:
        unchecked.is_checked = False
        db.update(unchecked)
        open_card.project_column_id = archive.id
        db.update(open_card)
    assert repository.get_incomplete_work_counts(project)[active.id] == 4
    engine.dispose()
