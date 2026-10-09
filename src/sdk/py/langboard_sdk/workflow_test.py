from unittest import TestCase
from .workflow import WorkflowRequirements, WorkflowStage


class WorkflowTests(TestCase):
    def test_builtin_types_serialize_without_creating_app_stages(self):
        requirements = WorkflowRequirements((WorkflowStage.ACTIVE, WorkflowStage.REVIEW, WorkflowStage.CLOSED), (WorkflowStage.READY,))
        self.assertEqual(requirements.to_dict(), {"required": ["active", "review", "closed"], "optional": ["ready"]})

    def test_custom_and_duplicate_stages_are_rejected(self):
        for required, optional in [(('triage',), ()), ((WorkflowStage.ACTIVE,), (WorkflowStage.ACTIVE,)), ((), ())]:
            with self.assertRaises(ValueError):
                WorkflowRequirements(required, optional)
