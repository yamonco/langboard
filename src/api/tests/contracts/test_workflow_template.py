import os


os.environ.setdefault("PROJECT_NAME", "langboard")

import pytest  # noqa: E402
from langboard_shared.domain.contracts.workflow_template import (  # noqa: E402
    MAX_ACTIONS_PER_TEMPLATE,
    WorkflowAction,
    WorkflowCondition,
    WorkflowTemplate,
    WorkflowTemplateCatalog,
    WorkflowTrigger,
)


def template(uid: str = "t1", name: str = "review flow", **overrides) -> WorkflowTemplate:
    defaults = dict(
        uid=uid,
        name=name,
        project_uid="p1",
        trigger=WorkflowTrigger.CARD_MOVED,
        actions=(WorkflowAction.ASSIGN_REVIEWER,),
        condition=WorkflowCondition(to_column="Check"),
    )
    defaults.update(overrides)
    return WorkflowTemplate(**defaults)


class TestWorkflowTemplate:
    def test_payload_round_trip(self):
        original = template()
        assert WorkflowTemplate.from_payload(original.to_payload()) == original

    def test_requires_action(self):
        with pytest.raises(ValueError):
            template(actions=())

    def test_rejects_duplicate_actions(self):
        with pytest.raises(ValueError):
            template(actions=(WorkflowAction.NOTIFY, WorkflowAction.NOTIFY))

    def test_rejects_action_overflow(self):
        with pytest.raises(ValueError):
            template(actions=(WorkflowAction.NOTIFY,) * (MAX_ACTIONS_PER_TEMPLATE + 1))

    def test_card_moved_requires_to_column(self):
        with pytest.raises(ValueError):
            template(condition=WorkflowCondition())

    def test_blank_name_rejected(self):
        with pytest.raises(ValueError):
            template(name="   ")


class TestWorkflowTemplateCatalog:
    def test_upsert_and_lookup(self):
        catalog = WorkflowTemplateCatalog()
        catalog.upsert(template())
        assert catalog.get("t1") is not None
        assert catalog.for_trigger("p1", WorkflowTrigger.CARD_MOVED) == (template(),)

    def test_upsert_replaces_same_uid(self):
        catalog = WorkflowTemplateCatalog()
        catalog.upsert(template())
        catalog.upsert(template(actions=(WorkflowAction.ADD_LABEL,), condition=WorkflowCondition(to_column="Done")))
        assert len(catalog.all()) == 1
        assert catalog.get("t1").actions == (WorkflowAction.ADD_LABEL,)

    def test_name_collision_within_project(self):
        catalog = WorkflowTemplateCatalog()
        catalog.upsert(template())
        with pytest.raises(ValueError):
            catalog.upsert(template(uid="t2"))

    def test_same_name_other_project_allowed(self):
        catalog = WorkflowTemplateCatalog()
        catalog.upsert(template())
        catalog.upsert(template(uid="t2", project_uid="p2"))
        assert len(catalog.all()) == 2

    def test_disabled_templates_hidden_from_trigger(self):
        catalog = WorkflowTemplateCatalog()
        catalog.upsert(template())
        catalog.upsert(template(uid="t2", name="disabled flow", is_enabled=False))
        assert len(catalog.for_trigger("p1", WorkflowTrigger.CARD_MOVED)) == 1

    def test_remove(self):
        catalog = WorkflowTemplateCatalog()
        catalog.upsert(template())
        assert catalog.remove("t1") is True
        assert catalog.remove("t1") is False
        assert catalog.all() == ()
