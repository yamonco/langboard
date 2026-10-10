"""Blocks-only SQL conditions shared without initializing application services."""

BLOCKING_RELATION_JOINS = """
    JOIN global_card_relationship_type dependency_type
      ON dependency_type.id = r.relationship_type_id
      AND dependency_type.machine_semantic = 'blocks'
    LEFT JOIN card prerequisite ON prerequisite.id = r.card_id_parent
    LEFT JOIN project_column prerequisite_column ON prerequisite_column.id = prerequisite.project_column_id
    LEFT JOIN workflow_stage_definition prerequisite_stage ON prerequisite_stage.key = prerequisite_column.workflow_stage
"""
UNSATISFIED_PREREQUISITE = """
    (prerequisite.id IS NULL OR prerequisite.deleted_at IS NOT NULL
     OR prerequisite.project_id IS DISTINCT FROM c.project_id
     OR prerequisite.archived_at IS NOT NULL OR prerequisite.source_type IS NOT NULL
     OR prerequisite_column.id IS NULL OR prerequisite_column.deleted_at IS NOT NULL
     OR prerequisite_column.project_id IS DISTINCT FROM c.project_id
     OR prerequisite_column.is_archive
     OR prerequisite_stage.counts_as_completed IS DISTINCT FROM TRUE)
"""
