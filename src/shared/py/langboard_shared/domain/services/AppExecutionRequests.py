"""Accept once per generation, rechecking authority even for duplicate requests."""

from ...core.db import DbSession, SqlBuilder
from ...core.types import SnowflakeID
from ..models import AppExecutionRequest
from .AppExecutionGrant import evaluate_current_execution_grant
from .AppGovernance import AppGovernanceDenied


class AppExecutionRequestConflict(Exception):
    pass


def request_app_execution(token, project_id, card_id, generation):
    with DbSession.atomic() as db:
        # Current authority locks project/card before idempotency lookup. Reading an
        # old receipt must never bypass current consent or resource revocation.
        authority = evaluate_current_execution_grant(token, project_id, card_id, generation)
        row = db.exec(
            SqlBuilder.select.table(AppExecutionRequest).where(
                AppExecutionRequest.card_id == card_id,
                AppExecutionRequest.generation == generation,
            )
        ).first()
        if row:
            if row.app_key != authority["app_key"] or row.connection_id != SnowflakeID.from_short_code(
                authority["connection_uid"]
            ):
                raise AppExecutionRequestConflict()
            for key in ("ownership_revision", "selection_revision", "binding_revision", "resource_revisions"):
                if row.authority.get(key) != authority[key]:
                    raise AppExecutionRequestConflict()
            if row.project_id != project_id:
                raise AppGovernanceDenied()
            changed = False
        else:
            row = AppExecutionRequest(
                project_id=project_id,
                card_id=card_id,
                app_key=authority["app_key"],
                connection_id=SnowflakeID.from_short_code(authority["connection_uid"]),
                generation=generation,
                authority=authority,
            )
            db.insert(row)
            changed = True
        return {
            "schema_version": 1,
            "request_uid": row.get_uid(),
            "card_uid": SnowflakeID(card_id).to_short_code(),
            "generation": row.generation,
            "state": "requested",
            "started": False,
            "changed": changed,
        }
