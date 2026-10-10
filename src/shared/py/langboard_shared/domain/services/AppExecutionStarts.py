"""Accept app-reported process starts only under a current live runtime permit."""

from hmac import compare_digest
from ...core.db import DbSession, SqlBuilder
from ...core.types import SafeDateTime
from ..models import AppExecutionLease, AppExecutionStart
from .AppEventDelivery import _expired
from .AppExecutionAcknowledgments import _request
from .AppExecutionLeases import _hash, _result
from .AppExecutionRequests import AppExecutionRequestConflict
from .AppGovernance import AppGovernanceDenied


def report_app_execution_start(token, project_id, card_id, request_id, lease_id, runtime_token, execution_reference):
    if not isinstance(execution_reference, str) or not execution_reference.strip() or len(execution_reference) > 200:
        raise ValueError("Execution reference must contain 1 to 200 characters")
    digest = _hash(runtime_token)
    with DbSession.atomic() as db:
        # Same app/project/card -> lease lock order as authorization/check. A
        # replay rechecks authority; an old receipt cannot reauthorize execution.
        request = _request(db, token, project_id, card_id, request_id)
        lease = db.exec(
            SqlBuilder.select.table(AppExecutionLease)
            .where(AppExecutionLease.id == lease_id, AppExecutionLease.request_id == request.id)
            .with_for_update()
        ).first()
        if (
            lease is None
            or not compare_digest(lease.runtime_token_hash, digest)
            or lease.state != "authorized"
            or _expired(lease.expires_at, SafeDateTime.now())
        ):
            raise AppGovernanceDenied()
        identity = _result(db, lease)
        receipt = db.exec(
            SqlBuilder.select.table(AppExecutionStart).where(AppExecutionStart.lease_id == lease.id)
        ).first()
        changed = receipt is None
        if receipt is None:
            receipt = AppExecutionStart(
                lease_id=lease.id,
                request_id=request.id,
                acknowledgment_id=lease.acknowledgment_id,
                generation=request.generation,
                runtime_reference=identity["runtime_reference"],
                execution_reference=execution_reference,
            )
            db.insert(receipt)
        elif receipt.execution_reference != execution_reference:
            raise AppExecutionRequestConflict()
        return {
            **{
                key: identity[key]
                for key in (
                    "schema_version",
                    "request_uid",
                    "acknowledgment_uid",
                    "runtime_reference",
                    "generation",
                    "lease_uid",
                )
            },
            "start_uid": receipt.get_uid(),
            "state": "start_reported",
            "evidence_kind": "app_attestation",
            "execution_reference": receipt.execution_reference,
            "reported_at": receipt.created_at.isoformat(),
            "changed": changed,
        }
