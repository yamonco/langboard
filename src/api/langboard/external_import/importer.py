from __future__ import annotations
from collections import Counter
from hashlib import sha256
from json import dumps
from pathlib import Path
from typing import Any, Callable, TypeVar
from langboard_shared.core.db import DbSession, EditorContentModel, SqlBuilder
from langboard_shared.core.logger import Logger
from langboard_shared.core.storage import FileModel, Storage, StorageName
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import (
    Card,
    CardAssignedProjectLabel,
    CardAssignedUser,
    CardAttachment,
    CardComment,
    CardRelationship,
    Checkitem,
    Checklist,
    ExternalImportRecord,
    GlobalCardRelationshipType,
    Project,
    ProjectAssignedUser,
    ProjectColumn,
    ProjectLabel,
    ProjectRole,
    User,
    UserIdentityLink,
)
from langboard_shared.domain.models.UserIdentityLink import IdentityProvider
from langboard_shared.Env import Env
from langboard_shared.publishers import (
    CardAttachmentPublisher,
    CardCommentPublisher,
    CardPublisher,
    CardRelationshipPublisher,
    CheckitemPublisher,
    ChecklistPublisher,
    ProjectColumnPublisher,
    ProjectLabelPublisher,
)
from langboard_shared.tasks.activities import (
    CardActivityTask,
    CardAttachmentActivityTask,
    CardCheckitemActivityTask,
    CardChecklistActivityTask,
    CardCommentActivityTask,
    CardRelationshipActivityTask,
    ProjectColumnActivityTask,
    ProjectLabelActivityTask,
)
from pydantic import BaseModel
from .contract import (
    ExternalAttachment,
    ExternalCard,
    ExternalCheckitem,
    ExternalChecklist,
    ExternalColumn,
    ExternalComment,
    ExternalLabel,
    ExternalRelationship,
    ExternalWorkBundle,
)


class ExternalImportError(ValueError):
    pass


class ExternalImportReceipt(BaseModel):
    dry_run: bool
    created: dict[str, int]
    unchanged: dict[str, int]


TImportEffectDispatcher = Callable[
    [str, BaseModel, Any, Project, User, dict[tuple[str, str], Any], dict[str, tuple[User, ProjectAssignedUser]]],
    None,
]


_Model = TypeVar("_Model")
_TARGET_MODELS = {
    "column": ProjectColumn,
    "label": ProjectLabel,
    "card": Card,
    "checklist": Checklist,
    "checkitem": Checkitem,
    "relationship": CardRelationship,
    "comment": CardComment,
    "attachment": CardAttachment,
}


class ExternalWorkImporter:
    """Restartable, provider-neutral anti-corruption boundary for legacy work data."""

    def __init__(
        self,
        attachments_root: Path | None = None,
        effect_dispatcher: TImportEffectDispatcher | None = None,
    ):
        self._attachments_root = attachments_root.resolve() if attachments_root else None
        self._effect_dispatcher = effect_dispatcher or self._dispatch_native_effects

    def import_bundle(
        self,
        bundle: ExternalWorkBundle,
        *,
        project_uid: str,
        actor_uid: str,
        dry_run: bool = False,
    ) -> ExternalImportReceipt:
        files = self._verify_attachments(bundle.attachments)
        with DbSession.use(readonly=True) as db:
            project = self._require_uid(db, Project, project_uid, "project")
            actor = self._require_uid(db, User, actor_uid, "actor")
            self._authorize(db, project, actor)
            existing = self._load_existing(db, project, bundle)
            targets = self._resolve_existing_targets(db, existing)
            principals = self._resolve_principals(db, project, bundle)
            self._reject_name_collisions(db, project, bundle, existing)
            self._validate_relationship_graph(db, project, bundle, existing, targets)

        pending = [(kind, item) for kind, item in bundle.records() if (kind, item.source_id) not in existing]
        unchanged = Counter(kind for kind, item in bundle.records() if (kind, item.source_id) in existing)
        if dry_run:
            return ExternalImportReceipt(
                dry_run=True,
                created=dict(Counter(kind for kind, _ in pending)),
                unchanged=dict(unchanged),
            )

        for kind, record in bundle.records():
            key = (kind, record.source_id)
            lineage = existing.get(key)
            if lineage:
                if lineage.effects_dispatched_at is None:
                    self._dispatch_and_checkpoint(
                        kind, record, targets[key], project, actor, targets, principals, lineage
                    )
                continue

            staged_file = (
                self._upload_attachment(project_uid, bundle, record, files)
                if isinstance(record, ExternalAttachment)
                else None
            )
            try:
                with DbSession.use(readonly=False) as db:
                    current_project = self._require_uid(db, Project, project_uid, "project")
                    current_actor = self._require_uid(db, User, actor_uid, "actor")
                    self._authorize(db, current_project, current_actor)
                    target = self._create_target(
                        db,
                        current_project,
                        record,
                        targets,
                        principals,
                        staged_file,
                    )
                    lineage = ExternalImportRecord(
                        project_id=current_project.id,
                        source_namespace=bundle.source.namespace,
                        source_container_id=bundle.source.container_id,
                        record_type=kind,
                        source_record_id=record.source_id,
                        target_type=kind,
                        target_uid=target.get_uid(),
                        source_fingerprint=record.fingerprint(),
                        batch_id=bundle.source.batch_id,
                        provenance=dumps(
                            {"schema_version": bundle.schema_version, "source": bundle.source.model_dump()},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                    db.insert(lineage)
            except Exception:
                if staged_file is not None and not self._matching_lineage_exists(
                    project_uid,
                    bundle,
                    kind,
                    record,
                ):
                    self._delete_staged_file(staged_file)
                raise

            project, actor = current_project, current_actor
            targets[key] = target
            existing[key] = lineage
            self._dispatch_and_checkpoint(kind, record, target, project, actor, targets, principals, lineage)

        return ExternalImportReceipt(
            dry_run=False,
            created=dict(Counter(kind for kind, _ in pending)),
            unchanged=dict(unchanged),
        )

    @staticmethod
    def _upload_attachment(
        project_uid: str,
        bundle: ExternalWorkBundle,
        record: ExternalAttachment,
        files: dict[str, Path],
    ) -> FileModel:
        extension = Path(record.original_filename).suffix.lower()[:32]
        object_key = (
            sha256(
                "\0".join(
                    (
                        bundle.source.namespace,
                        bundle.source.container_id,
                        project_uid,
                        record.source_id,
                        record.sha256,
                    )
                ).encode()
            ).hexdigest()
            + extension
        )
        with files[record.source_id].open("rb") as stream:
            file_model = Storage.upload_named(
                stream,
                StorageName.CardAttachment,
                object_key,
                Path(record.original_filename).name,
            )
        if not file_model:
            raise ExternalImportError(f"attachment upload failed: {record.relative_path}")
        return file_model

    @staticmethod
    def _delete_staged_file(file_model: FileModel) -> None:
        if not Storage.delete(file_model):
            raise ExternalImportError(f"failed to compensate staged attachment: {file_model.original_filename}")

    @staticmethod
    def _matching_lineage_exists(
        project_uid: str,
        bundle: ExternalWorkBundle,
        kind: str,
        record: BaseModel,
    ) -> bool:
        """Protect an object won by a concurrent import before compensating ours."""

        try:
            with DbSession.use(readonly=True) as db:
                project = ExternalWorkImporter._require_uid(db, Project, project_uid, "project")
                lineage = db.exec(
                    SqlBuilder.select.table(ExternalImportRecord)
                    .where(
                        (ExternalImportRecord.project_id == project.id)
                        & (ExternalImportRecord.source_namespace == bundle.source.namespace)
                        & (ExternalImportRecord.source_container_id == bundle.source.container_id)
                        & (ExternalImportRecord.record_type == kind)
                        & (ExternalImportRecord.source_record_id == record.source_id)
                        & (ExternalImportRecord.source_fingerprint == record.fingerprint())
                    )
                    .limit(1)
                ).first()
            return lineage is not None
        except Exception:
            # If database visibility is unavailable, retaining one deterministic
            # key is safer than deleting an object committed by a race winner.
            Logger.main.exception("Could not verify import lineage before attachment compensation")
            return True

    def _verify_attachments(self, attachments: list[ExternalAttachment]) -> dict[str, Path]:
        if not attachments:
            return {}
        if not self._attachments_root:
            raise ExternalImportError("attachments_root is required when the bundle contains attachments")
        files: dict[str, Path] = {}
        for attachment in attachments:
            candidate = (self._attachments_root / attachment.relative_path).resolve()
            try:
                candidate.relative_to(self._attachments_root)
            except ValueError as exc:
                raise ExternalImportError("attachment path escapes attachments_root") from exc
            if not candidate.is_file():
                raise ExternalImportError(f"attachment file is missing: {attachment.relative_path}")
            if attachment.size > Env.MAX_FILE_SIZE_MB * 1024 * 1024:
                raise ExternalImportError(f"attachment exceeds the {Env.MAX_FILE_SIZE_MB} MB upload limit")
            digest, size = sha256(), 0
            with candidate.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
            if size != attachment.size or digest.hexdigest() != attachment.sha256:
                raise ExternalImportError(f"attachment integrity mismatch: {attachment.relative_path}")
            files[attachment.source_id] = candidate
        return files

    @staticmethod
    def _require_uid(db: DbSession, model: type[_Model], uid: str, label: str) -> _Model:
        value = db.exec(
            SqlBuilder.select.table(model).where(model.column("id") == SnowflakeID.from_short_code(uid)).limit(1)
        ).first()
        if not value:
            raise ExternalImportError(f"unknown {label}")
        return value

    @staticmethod
    def _authorize(db: DbSession, project: Project, actor: User) -> None:
        if actor.is_admin or project.owner_id == actor.id:
            return
        role = db.exec(
            SqlBuilder.select.table(ProjectRole)
            .where((ProjectRole.project_id == project.id) & (ProjectRole.user_id == actor.id))
            .limit(1)
        ).first()
        if not role or not role.is_all_granted():
            raise ExternalImportError("actor requires project owner, administrator, or full project access")

    @staticmethod
    def _load_existing(
        db: DbSession, project: Project, bundle: ExternalWorkBundle
    ) -> dict[tuple[str, str], ExternalImportRecord]:
        rows = db.exec(
            SqlBuilder.select.table(ExternalImportRecord).where(
                (ExternalImportRecord.project_id == project.id)
                & (ExternalImportRecord.source_namespace == bundle.source.namespace)
                & (ExternalImportRecord.source_container_id == bundle.source.container_id)
            )
        ).all()
        incoming = {(kind, item.source_id): item for kind, item in bundle.records()}
        selected = {
            (row.record_type, row.source_record_id): row
            for row in rows
            if (row.record_type, row.source_record_id) in incoming
        }
        for key, row in selected.items():
            if row.source_fingerprint != incoming[key].fingerprint():
                raise ExternalImportError(f"source record changed after import: {key[0]}:{key[1]}")
        return selected

    def _resolve_existing_targets(
        self, db: DbSession, existing: dict[tuple[str, str], ExternalImportRecord]
    ) -> dict[tuple[str, str], Any]:
        targets: dict[tuple[str, str], Any] = {}
        for key, row in existing.items():
            model = _TARGET_MODELS.get(row.target_type)
            if model is None or row.target_type != key[0]:
                raise ExternalImportError(f"invalid import lineage target: {key[0]}:{key[1]}")
            targets[key] = self._require_uid(db, model, row.target_uid, f"import target for {key[0]}:{key[1]}")
        return targets

    @staticmethod
    def _reject_name_collisions(db, project, bundle, existing) -> None:
        for kind, model, records in (
            ("column", ProjectColumn, bundle.columns),
            ("label", ProjectLabel, bundle.labels),
        ):
            names = {item.name for item in records if (kind, item.source_id) not in existing}
            if not names:
                continue
            collision = db.exec(
                SqlBuilder.select.table(model).where(
                    (model.column("project_id") == project.id) & model.column("name").in_(names)
                )
            ).first()
            if collision:
                raise ExternalImportError(f"unmapped {kind} name already exists in the project: {collision.name}")

    @staticmethod
    def _resolve_principals(db, project, bundle) -> dict[str, tuple[User, ProjectAssignedUser]]:
        external_ids = {external_id for card in bundle.cards for external_id in card.assignee_scim_external_ids}
        external_ids.update(item.author_scim_external_id for item in [*bundle.comments, *bundle.attachments])
        if not external_ids:
            return {}
        if not Env.SCIM_ISSUER:
            raise ExternalImportError("SCIM_ISSUER is required for imported principals")
        links = db.exec(
            SqlBuilder.select.table(UserIdentityLink).where(
                (UserIdentityLink.provider == IdentityProvider.Scim)
                & (UserIdentityLink.issuer == Env.SCIM_ISSUER)
                & UserIdentityLink.external_id.in_(external_ids)
            )
        ).all()
        links_by_id = {link.external_id: link for link in links}
        missing = external_ids - links_by_id.keys()
        if missing:
            raise ExternalImportError(f"unknown SCIM principal: {sorted(missing)[0]}")
        memberships = db.exec(
            SqlBuilder.select.table(ProjectAssignedUser).where(
                (ProjectAssignedUser.project_id == project.id)
                & ProjectAssignedUser.user_id.in_(link.user_id for link in links)
            )
        ).all()
        memberships_by_user = {item.user_id: item for item in memberships}
        principals = {}
        for external_id, link in links_by_id.items():
            membership = memberships_by_user.get(link.user_id)
            user = db.exec(SqlBuilder.select.table(User).where(User.id == link.user_id).limit(1)).first()
            if not membership or not user:
                raise ExternalImportError(f"SCIM principal is not an active project member: {external_id}")
            principals[external_id] = (user, membership)
        return principals

    @staticmethod
    def _validate_relationship_graph(db, project, bundle, existing, targets) -> None:
        cards = db.exec(SqlBuilder.select.table(Card).where(Card.project_id == project.id)).all()
        card_ids = {card.id for card in cards}
        edges: set[tuple[int | str, int | str]] = set()
        if card_ids:
            relationships = db.exec(
                SqlBuilder.select.table(CardRelationship).where(
                    CardRelationship.card_id_parent.in_(card_ids) & CardRelationship.card_id_child.in_(card_ids)
                )
            ).all()
            edges.update((int(item.card_id_parent), int(item.card_id_child)) for item in relationships)
        refs = {
            card.source_id: int(targets[("card", card.source_id)].id)
            if ("card", card.source_id) in targets
            else f"new:{card.source_id}"
            for card in bundle.cards
        }
        for item in bundle.relationships:
            if ("relationship", item.source_id) in existing:
                continue
            edge = (refs[item.parent_card_source_id], refs[item.child_card_source_id])
            if edge in edges:
                raise ExternalImportError("relationship edge already exists without import lineage")
            edges.add(edge)
        if ExternalWorkBundle._has_cycle(edges):
            raise ExternalImportError("import would create a relationship cycle")

    def _create_target(self, db, project, record, targets, principals, staged_file: FileModel | None):
        if isinstance(record, ExternalColumn):
            target = ProjectColumn(project_id=project.id, name=record.name, order=record.order)
        elif isinstance(record, ExternalLabel):
            target = ProjectLabel(
                project_id=project.id,
                name=record.name,
                color=record.color,
                description=record.description,
                order=record.order,
            )
        elif isinstance(record, ExternalCard):
            target = Card(
                project_id=project.id,
                project_column_id=targets[("column", record.column_source_id)].id,
                title=record.title,
                description=EditorContentModel(content=record.description),
                deadline_at=record.deadline_at,
                order=record.order,
            )
            db.insert(target)
            for label_id in record.label_source_ids:
                db.insert(CardAssignedProjectLabel(card_id=target.id, project_label_id=targets[("label", label_id)].id))
            for external_id in record.assignee_scim_external_ids:
                user, membership = principals[external_id]
                db.insert(CardAssignedUser(project_assigned_id=membership.id, card_id=target.id, user_id=user.id))
            return target
        elif isinstance(record, ExternalChecklist):
            target = Checklist(
                card_id=targets[("card", record.card_source_id)].id, title=record.title, order=record.order
            )
        elif isinstance(record, ExternalCheckitem):
            target = Checkitem(
                checklist_id=targets[("checklist", record.checklist_source_id)].id,
                title=record.title,
                order=record.order,
                is_checked=record.is_checked,
            )
        elif isinstance(record, ExternalRelationship):
            relationship_type = self._require_uid(
                db, GlobalCardRelationshipType, record.relationship_type_uid, "relationship type"
            )
            target = CardRelationship(
                relationship_type_id=relationship_type.id,
                card_id_parent=targets[("card", record.parent_card_source_id)].id,
                card_id_child=targets[("card", record.child_card_source_id)].id,
            )
        elif isinstance(record, ExternalComment):
            user, _ = principals[record.author_scim_external_id]
            target = CardComment(
                card_id=targets[("card", record.card_source_id)].id,
                user_id=user.id,
                content=EditorContentModel(content=record.content),
                created_at=record.created_at,
                updated_at=record.created_at,
            )
        elif isinstance(record, ExternalAttachment):
            user, _ = principals[record.author_scim_external_id]
            if staged_file is None:
                raise ExternalImportError("attachment was not staged")
            target = CardAttachment(
                user_id=user.id,
                card_id=targets[("card", record.card_source_id)].id,
                filename=record.original_filename,
                file=staged_file,
                created_at=record.created_at,
                updated_at=record.created_at,
            )
        else:
            raise TypeError(f"unsupported external work record: {type(record).__name__}")
        db.insert(target)
        return target

    def _dispatch_and_checkpoint(
        self,
        kind: str,
        record: BaseModel,
        target: Any,
        project: Project,
        actor: User,
        targets: dict[tuple[str, str], Any],
        principals: dict[str, tuple[User, ProjectAssignedUser]],
        lineage: ExternalImportRecord,
    ) -> None:
        try:
            self._effect_dispatcher(kind, record, target, project, actor, targets, principals)
        except Exception as exc:
            self._checkpoint_effects(lineage, error=str(exc))
            raise
        self._checkpoint_effects(lineage)

    @staticmethod
    def _checkpoint_effects(lineage: ExternalImportRecord, error: str | None = None) -> None:
        with DbSession.use(readonly=False) as db:
            current = db.exec(
                SqlBuilder.select.table(ExternalImportRecord).where(ExternalImportRecord.id == lineage.id).limit(1)
            ).first()
            if current is None:
                raise ExternalImportError("import lineage disappeared before side-effect checkpoint")
            current.effects_attempts += 1
            current.effects_error = error[:4000] if error else None
            if error is None:
                current.effects_dispatched_at = SafeDateTime.now()
            db.update(current)
            lineage.effects_attempts = current.effects_attempts
            lineage.effects_error = current.effects_error
            lineage.effects_dispatched_at = current.effects_dispatched_at

    @staticmethod
    def _dispatch_native_effects(
        kind: str,
        record: BaseModel,
        target: Any,
        project: Project,
        actor: User,
        targets: dict[tuple[str, str], Any],
        principals: dict[str, tuple[User, ProjectAssignedUser]],
    ) -> None:
        """Emit the same realtime and activity signals as native creation paths.

        Historical imports deliberately do not notify mentions, execute bots, or alter
        approval state. Those are live workflow actions rather than imported domain data.
        """

        if kind == "column" and isinstance(record, ExternalColumn):
            ProjectColumnPublisher.created(project, target)
            ProjectColumnActivityTask.project_column_created(actor, project, target)
            return
        if kind == "label" and isinstance(record, ExternalLabel):
            ProjectLabelPublisher.created(project, target)
            ProjectLabelActivityTask.project_label_created(actor, project, target)
            return
        if kind == "card" and isinstance(record, ExternalCard):
            column = targets[("column", record.column_source_id)]
            member_uids = [principals[external_id][0].get_uid() for external_id in record.assignee_scim_external_ids]
            labels = [targets[("label", source_id)].api_response() for source_id in record.label_source_ids]
            CardPublisher.created(
                project,
                column,
                {"card": target.board_api_response(0, member_uids, [], labels)},
            )
            CardActivityTask.card_created(actor, project, target)
            return
        if kind == "checklist" and isinstance(record, ExternalChecklist):
            card = targets[("card", record.card_source_id)]
            ChecklistPublisher.created(card, target)
            CardChecklistActivityTask.card_checklist_created(actor, project, card, target)
            return
        if kind == "checkitem" and isinstance(record, ExternalCheckitem):
            checklist = targets[("checklist", record.checklist_source_id)]
            card = ExternalWorkImporter._card_for_checklist(checklist)
            CheckitemPublisher.created(card, checklist, target)
            CardCheckitemActivityTask.card_checkitem_created(actor, project, card, target)
            return
        if kind == "relationship" and isinstance(record, ExternalRelationship):
            parent = targets[("card", record.parent_card_source_id)]
            child = targets[("card", record.child_card_source_id)]
            relationships = ExternalWorkImporter._relationships_for_card(parent)
            CardRelationshipPublisher.updated(project, parent, relationships)
            CardRelationshipActivityTask.card_relationship_updated(actor, project, parent, [], [child.id], False)
            return
        if kind == "comment" and isinstance(record, ExternalComment):
            card = targets[("card", record.card_source_id)]
            author, _ = principals[record.author_scim_external_id]
            CardCommentPublisher.created(author, project, card, target)
            CardCommentActivityTask.card_comment_added(author, project, card, target)
            return
        if kind == "attachment" and isinstance(record, ExternalAttachment):
            card = targets[("card", record.card_source_id)]
            author, _ = principals[record.author_scim_external_id]
            CardAttachmentPublisher.uploaded(author, card, target)
            CardAttachmentActivityTask.card_attachment_uploaded(author, project, card, target)
            return
        raise ExternalImportError(f"unsupported side-effect record: {kind}")

    @staticmethod
    def _card_for_checklist(checklist: Checklist) -> Card:
        with DbSession.use(readonly=True) as db:
            card = db.exec(SqlBuilder.select.table(Card).where(Card.id == checklist.card_id).limit(1)).first()
        if card is None:
            raise ExternalImportError("checklist card disappeared before side-effect dispatch")
        return card

    @staticmethod
    def _relationships_for_card(card: Card) -> list[dict[str, Any]]:
        with DbSession.use(readonly=True) as db:
            rows = db.exec(
                SqlBuilder.select.table(CardRelationship).where(
                    (CardRelationship.card_id_parent == card.id) | (CardRelationship.card_id_child == card.id)
                )
            ).all()
        return [relationship.api_response() for relationship in rows]
