import os


os.environ.setdefault("PROJECT_NAME", "langboard")

from datetime import datetime, timezone  # noqa: E402
import pytest  # noqa: E402
from langboard_shared.domain.contracts.workflow_pipeline import (  # noqa: E402
    WorkflowEvent,
    WorkflowRunStatus,
    WorkflowTemplate,
    WorkflowTrigger,
    condition_matches,
    plan_actions,
    record_run,
)
from langboard_shared.domain.contracts.workflow_template import (  # noqa: E402
    WorkflowAction,
    WorkflowCondition,
)


UTC = timezone.utc
BASE = datetime(2026, 9, 19, 10, 0, 0, tzinfo=UTC)


def event(**overrides) -> WorkflowEvent:
    defaults = dict(
        event_id="e1",
        project_uid="p1",
        trigger=WorkflowTrigger.CARD_MOVED,
        occurred_at=BASE,
        actor="user-1",
        card_uid="c1",
        from_column="Doing",
        to_column="Check",
    )
    defaults.update(overrides)
    return WorkflowEvent(**defaults)


def template(uid: str, name: str, to_column: str = "Check", actions=None, **overrides) -> WorkflowTemplate:
    defaults = dict(
        uid=uid,
        name=name,
        project_uid="p1",
        trigger=WorkflowTrigger.CARD_MOVED,
        actions=actions or (WorkflowAction.ASSIGN_REVIEWER,),
        condition=WorkflowCondition(to_column=to_column),
    )
    defaults.update(overrides)
    return WorkflowTemplate(**defaults)


class TestWorkflowEvent:
    def test_rejects_naive_timestamp(self):
        with pytest.raises(ValueError):
            event(occurred_at=datetime(2026, 9, 19))

    def test_requires_event_id(self):
        with pytest.raises(ValueError):
            event(event_id="")


class TestConditionMatches:
    def test_unconditional_matches_everything(self):
        assert condition_matches(WorkflowCondition(), event())

    def test_declared_fields_must_agree(self):
        condition = WorkflowCondition(to_column="Done", label="urgent")
        assert not condition_matches(condition, event())
        assert condition_matches(condition, event(to_column="Done", label="urgent"))


class TestPlanActions:
    def test_collects_matching_templates_in_order(self):
        templates = (
            template("t2", "beta flow"),
            template("t1", "alpha flow", actions=(WorkflowAction.ADD_LABEL, WorkflowAction.NOTIFY)),
        )
        plans = plan_actions(templates, event())
        assert [(p.template_uid, p.action) for p in plans] == [
            ("t1", WorkflowAction.ADD_LABEL),
            ("t1", WorkflowAction.NOTIFY),
            ("t2", WorkflowAction.ASSIGN_REVIEWER),
        ]

    def test_skips_other_projects_and_triggers(self):
        templates = (
            template("t1", "flow", project_uid="p2"),
            template("t2", "other trigger", trigger=WorkflowTrigger.CARD_CREATED, condition=WorkflowCondition()),
        )
        assert plan_actions(templates, event()) == ()

    def test_condition_narrows_matches(self):
        templates = (template("t1", "flow", to_column="Done"),)
        assert plan_actions(templates, event()) == ()
        assert len(plan_actions(templates, event(to_column="Done"))) == 1

    def test_disabled_template_skipped(self):
        templates = (template("t1", "flow", is_enabled=False),)
        assert plan_actions(templates, event()) == ()


class TestRecordRun:
    def test_no_match_records_skip(self):
        records = record_run(event(), (), run_uid="r1")
        assert len(records) == 1
        assert records[0].status is WorkflowRunStatus.SKIPPED

    def test_one_record_per_plan(self):
        templates = (template("t1", "flow", actions=(WorkflowAction.ADD_LABEL, WorkflowAction.NOTIFY)),)
        plans = plan_actions(templates, event())
        records = record_run(event(), plans, run_uid="r1")
        assert [r.status for r in records] == [WorkflowRunStatus.PLANNED] * 2
        assert records[0].run_uid == "r1:0"
        assert records[1].to_payload()["template_uid"] == "t1"
