"""Approved external issues use native card creation and durable import lineage."""

from hashlib import sha256
from json import dumps
from ...core.db import DbSession, EditorContentModel, SqlBuilder
from ...core.types import SafeDateTime, SnowflakeID
from ..constants.CardPresentation import CARD_PRESENTATION_KEY, validate_card_presentation
from ..models import (
    AppConnection,
    AppDefinition,
    AppResourceBinding,
    BoardAppBinding,
    Card,
    ExternalImportRecord,
    Project,
    ProjectColumn,
    User,
    WorkflowStageDefinition,
)
from ..models.ProjectRole import ProjectRoleAction
from .AppConnectionAuthentication import authenticate_connection_credential
from .AppGovernance import AppGovernanceDenied, _current, require_connection_access
from .DomainService import DomainService


class AppCardCreationConflict(Exception):
    """A source identity cannot create a second card or overwrite its original input."""


def create_app_card(token, project_id, resource_id, external_id, title, *, description="", presentation=None):
    if not isinstance(external_id, str) or not external_id.strip() or len(external_id) > 200:
        raise ValueError("A stable external issue ID is required")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError("A card title of at most 200 characters is required")
    if not isinstance(description, str) or len(description) > 100000:
        raise ValueError("Invalid issue description")
    if presentation is not None:
        validate_card_presentation(dumps(presentation, ensure_ascii=False))
    fingerprint = sha256(
        dumps([title, description, presentation], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    service = DomainService()
    try:
        with DbSession.atomic() as db:
            # Serialize board writes before source receipt lookup. The lineage unique key
            # remains a final database fence across independent application processes.
            principal = authenticate_connection_credential(token)
            project = _current(db, Project, project_id)
            actor = _current(db, User, principal.owner_id)
            connection = _current(db, AppConnection, principal.connection_id)
            if project is None or actor is None or connection is None:
                raise AppGovernanceDenied()
            require_connection_access(db, actor, project, connection, unattended=True)
            # Automation never produces a human-only PRIVATE card. Internal access
            # remains the native instance policy; presentation does not grant it.
            if service.card._resolve_internal_access(actor) is not True:
                raise AppGovernanceDenied()
            if (
                service.workflow_stage._authorized_app_board(actor, project.id, ProjectRoleAction.CardUpdate, lock=True)
                is None
            ):
                raise AppGovernanceDenied()
            definition = db.exec(
                SqlBuilder.select.table(AppDefinition).where(AppDefinition.key == principal.app_key).with_for_update()
            ).first()
            binding = db.exec(
                SqlBuilder.select.table(BoardAppBinding)
                .where(
                    BoardAppBinding.project_id == project.id,
                    BoardAppBinding.app_key == principal.app_key,
                )
                .with_for_update()
            ).first()
            required = {"cards.create", "resources.read"} | (
                {"cards.presentation"} if presentation is not None else set()
            )
            if (
                definition is None
                or not definition.is_enabled
                or binding is None
                or binding.state != "enabled"
                or not required.issubset(definition.declaration.get("capabilities", []))
                or not required.issubset(binding.granted_capabilities)
            ):
                raise AppGovernanceDenied()
            if presentation is not None and not presentation["key"].startswith(f"app.{principal.app_key}."):
                raise AppGovernanceDenied()
            resource = _current(db, AppResourceBinding, resource_id)
            if (
                resource is None
                or resource.board_binding_id != binding.id
                or resource.connection_id != connection.id
                or not resource.is_selected
                or resource.access_state != "granted"
                or resource.resource_type not in definition.declaration.get("resource_types", [])
            ):
                raise AppGovernanceDenied()
            stage = db.exec(
                SqlBuilder.select.table(WorkflowStageDefinition)
                .where(WorkflowStageDefinition.key == "backlog")
                .with_for_update()
            ).first()
            column = _current(
                db, ProjectColumn, SnowflakeID.from_short_code(binding.workflow_mapping.get("backlog", ""))
            )
            if (
                stage is None
                or not stage.is_builtin
                or not stage.is_active
                or column is None
                or column.project_id != project.id
                or column.deleted_at
                or column.is_archive
                or column.workflow_stage != "backlog"
            ):
                raise AppGovernanceDenied()
            namespace = f"app:{principal.app_key}:{connection.get_uid()}"
            receipt = db.exec(
                SqlBuilder.select.table(ExternalImportRecord)
                .where(
                    ExternalImportRecord.project_id == project.id,
                    ExternalImportRecord.source_namespace == namespace,
                    ExternalImportRecord.source_container_id == resource.get_uid(),
                    ExternalImportRecord.record_type == "app_card",
                    ExternalImportRecord.source_record_id == external_id,
                )
                .with_for_update()
            ).first()
            if receipt is not None:
                if receipt.source_fingerprint != fingerprint:
                    raise AppCardCreationConflict()
                card = _current(db, Card, SnowflakeID.from_short_code(receipt.target_uid))
                if card is None or service.card.resolve_readable_card(project, card, actor) is None:
                    raise AppGovernanceDenied()
                return _receipt(receipt, created=False)
            result = service.card.create(
                actor, project, column, title, EditorContentModel(content=description), dispatch_effects=False
            )
            if result is None:
                raise AppGovernanceDenied()
            card, payload = result
            if card.visibility == "PRIVATE":
                card.visibility = "INTERNAL"
                card.owner_user_id = None
                db.update(card)
                payload["visibility"] = "INTERNAL"
                payload["owner_user_uid"] = None
            if presentation is not None:
                service.metadata.save_card(
                    actor, project, card, CARD_PRESENTATION_KEY, dumps(presentation, ensure_ascii=False)
                )
            receipt = ExternalImportRecord(
                project_id=project.id,
                source_namespace=namespace,
                source_container_id=resource.get_uid(),
                record_type="app_card",
                source_record_id=external_id,
                target_type="card",
                target_uid=card.get_uid(),
                source_fingerprint=fingerprint,
                batch_id=external_id,
                provenance=dumps(
                    {
                        "app_key": principal.app_key,
                        "connection_uid": connection.get_uid(),
                        "resource_uid": resource.get_uid(),
                    }
                ),
            )
            db.insert(receipt)
            db.after_commit(lambda: _dispatch(receipt.id, actor, project, column, card, payload, presentation))
            return _receipt(receipt, created=True)
    finally:
        service.close()


def _receipt(receipt, *, created):
    return {
        "card_uid": receipt.target_uid,
        "receipt_uid": receipt.get_uid(),
        "created": created,
        "effects_state": "dispatched"
        if receipt.effects_dispatched_at
        else "failed"
        if receipt.effects_error
        else "pending",
    }


def _dispatch(receipt_id, actor, project, column, card, payload, presentation):
    service = DomainService()
    error = None
    try:
        service.card.dispatch_created(actor, project, column, card, {"card": payload})
        if presentation is not None:
            from ...core.routing import SocketTopic
            from ...publishers import MetadataPublisher

            MetadataPublisher.updated_metadata(
                SocketTopic.BoardCard,
                card.get_uid(),
                CARD_PRESENTATION_KEY,
                dumps(presentation, ensure_ascii=False),
                None,
            )
    except Exception:
        # Keep the committed card and receipt; do not replay possibly delivered effects.
        error = "Native card effects failed; inspect delivery before retrying effects."
    finally:
        service.close()
    with DbSession.atomic() as db:
        receipt = _current(db, ExternalImportRecord, receipt_id)
        receipt.effects_attempts += 1
        receipt.effects_error = error
        if error is None:
            receipt.effects_dispatched_at = SafeDateTime.now()
        db.update(receipt)
