"""Exercise real DB persistence, snapshot isolation, and local-first selection."""

from types import SimpleNamespace
import pytest
from langboard_shared.core.db import DbSession
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.domain.models import GlobalLabel, Project, ProjectLabel
from langboard_shared.domain.services.factory.ProjectLabelService import ProjectLabelService
from langboard_shared.infrastructure.repositories.factory.ProjectLabelRepository import ProjectLabelRepository
from sqlalchemy import create_engine, insert, select
from sqlalchemy.exc import IntegrityError


def test_global_selection_snapshot_local_priority_and_source_uniqueness(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (GlobalLabel, Project, ProjectLabel):
        model.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    project = Project(owner_id=1, title="Selection acceptance")
    definition = GlobalLabel(
        name="Contract",
        color="#112233",
        description="Development agreement",
        emoji="📜",
        translations={"ko": {"name": "컨트랙트", "description": "개발 계약"}},
    )
    with DbSession.use(readonly=False) as db:
        db.insert(project)
        db.insert(definition)
    repo = ProjectLabelRepository(lambda _: None, lambda _: None)
    svc = ProjectLabelService(lambda _: None, lambda _: None, SimpleNamespace(project_label=repo))
    published = []
    monkeypatch.setattr(svc, "dispatch_created", lambda *args: published.append(args[-1]))
    first = svc.use_global(object(), project, definition.get_uid())
    assert first["created"] and len(published) == 1
    label = first["label"]
    assert label["global_label_uid"] == definition.get_uid()
    assert label["global_display"]["emoji"] == "📜"
    assert label["global_display"]["translations"]["ko"]["name"] == "컨트랙트"
    # Source rename/edit must not silently overwrite an existing board snapshot.
    definition.name, definition.emoji = "Renamed Contract", "✨"
    definition.translations["ko"]["name"] = "변경됨"
    with DbSession.use(readonly=False) as db:
        db.update(definition)
    reused = svc.use_global(object(), project, definition.get_uid())
    assert not reused["created"]
    for key in ("uid", "name", "color", "description", "global_label_uid", "global_display"):
        assert reused["label"][key] == label[key]
    assert len(published) == 1
    local = ProjectLabel(
        project_id=project.id, name=" renamed contract ", color="#ABCDEF", description="Local override", order=1
    )
    with DbSession.use(readonly=False) as db:
        db.insert(local)
    local_result = svc.use_global(object(), project, definition.get_uid())
    assert not local_result["created"] and local_result["label"]["uid"] == local.get_uid()
    assert local_result["label"]["global_display"] is None
    assert local_result["label"]["global_label_uid"] is None
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                insert(ProjectLabel.__table__).values(
                    id=999,
                    project_id=int(project.id),
                    global_label_id=int(definition.id),
                    name="Duplicate",
                    color="#112233",
                    description="",
                    order=2,
                    created_at=definition.created_at,
                    updated_at=definition.updated_at,
                )
            )
    with engine.connect() as connection:
        assert len(connection.execute(select(ProjectLabel.__table__)).all()) == 2
    assert svc.use_global(object(), project, "missing") is None
