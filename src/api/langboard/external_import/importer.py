from __future__ import annotations
from collections import Counter
from datetime import datetime
from functools import partial
from hashlib import sha256
from itertools import batched, groupby
from json import dumps
from pathlib import Path
from typing import Any, Callable, TypeVar
from langboard_shared.core.db import DbSession, EditorContentModel, SqlBuilder
from langboard_shared.core.logger import Logger
from langboard_shared.core.storage import FileModel, Storage, StorageName
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import (
    Card,
    CardAttachment,
    CardComment,
    CardRelationship,
    Checkitem,
    Checklist,
    ExternalImportRecord,
    Project,
    ProjectAssignedUser,
    ProjectColumn,
    ProjectLabel,
    ProjectRole,
    User,
    UserIdentityLink,
)
from langboard_shared.domain.models.UserIdentityLink import IdentityProvider
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
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
from .effects import dispatch_imported_effects


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
        self._domain = DomainService()
        self._effect_dispatcher = effect_dispatcher or partial(dispatch_imported_effects, self._domain)

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

        for (_, was_imported), records in groupby(
            bundle.records(), key=lambda pair: (pair[0], (pair[0], pair[1].source_id) in existing)
        ):
            if was_imported:
                for kind, record in records:
                    key = (kind, record.source_id)
                    lineage = existing[key]
                    if lineage.effects_dispatched_at is None:
                        self._dispatch_and_checkpoint(
                            kind, record, targets[key], project, actor, targets, principals, lineage
                        )
            else:
                for chunk in batched(records, 25):
                    self._import_chunk(chunk, bundle, project_uid, actor_uid, files, targets, principals, existing)

        return ExternalImportReceipt(
            dry_run=False,
            created=dict(Counter(kind for kind, _ in pending)),
            unchanged=dict(unchanged),
        )

    def _import_chunk(self, chunk, bundle, project_uid, actor_uid, files, targets, principals, existing) -> None:
        staged: dict[tuple[str, str], FileModel] = {}
        created = []
        try:
            for kind, record in chunk:
                if isinstance(record, ExternalAttachment):
                    staged[(kind, record.source_id)] = self._upload_attachment(project_uid, bundle, record, files)
            with DbSession.atomic() as db:
                project = self._require_uid(db, Project, project_uid, "project")
                actor = self._require_uid(db, User, actor_uid, "actor")
                self._authorize(db, project, actor)
                for kind, record in chunk:
                    key = (kind, record.source_id)
                    target = self._create_target(db, project, actor, record, targets, principals, staged.get(key))
                    lineage = ExternalImportRecord(
                        project_id=project.id,
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
                    targets[key] = target
                    created.append((kind, record, target, lineage))
        except Exception:
            for kind, record in chunk:
                file = staged.get((kind, record.source_id))
                if file is not None and not self._matching_lineage_exists(project_uid, bundle, kind, record):
                    self._delete_staged_file(file)
            raise
        for kind, record, target, lineage in created:
            existing[(kind, record.source_id)] = lineage
            self._dispatch_and_checkpoint(kind, record, target, project, actor, targets, principals, lineage)

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
        for kind, rows in groupby(
            sorted(existing.items(), key=lambda pair: pair[0][0]), key=lambda pair: pair[0][0]
        ):
            model = _TARGET_MODELS.get(kind)
            for batch in batched(rows, 500):
                if model is None or any(row.target_type != kind for _, row in batch):
                    raise ExternalImportError(f"invalid import lineage target: {kind}")
                ids = [SnowflakeID.from_short_code(row.target_uid) for _, row in batch]
                found = {
                    target.id: target for target in db.exec(
                        SqlBuilder.select.table(model).where(model.column("id").in_(ids))
                    ).all()
                }
                if len(found) != len(set(ids)):
                    raise ExternalImportError(f"unknown import target for {kind}")
                targets.update((key, found[target_id]) for (key, _), target_id in zip(batch, ids))
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
        card_ids = SqlBuilder.select.columns(Card.id).where(Card.project_id == project.id)
        relationships = db.exec(
            SqlBuilder.select.table(CardRelationship).where(
                CardRelationship.card_id_parent.in_(card_ids) & CardRelationship.card_id_child.in_(card_ids)
            )
        ).all()
        edges: set[tuple[int | str, int | str]] = {
            (int(item.card_id_parent), int(item.card_id_child)) for item in relationships
        }
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

    def _create_target(self, db, project, actor, record, targets, principals, staged_file: FileModel | None):
        if isinstance(record, ExternalColumn):
            target = self._domain.project_column.create(
                actor, project, record.name, dispatch_effects=False, order_override=record.order
            )
            if target is None:
                raise ExternalImportError("project column creation failed")
            return target
        elif isinstance(record, ExternalLabel):
            created = self._domain.project_label.create(
                actor, project, record.name, record.color, record.description,
                dispatch_effects=False, order_override=record.order,
            )
            if created is None:
                raise ExternalImportError("project label creation failed")
            target, _ = created
            return target
        elif isinstance(record, ExternalCard):
            column = targets[("column", record.column_source_id)]
            assignee_uids = [principals[external_id][0].get_uid() for external_id in record.assignee_scim_external_ids]
            created = self._domain.card.create(
                actor,
                project,
                column,
                record.title,
                EditorContentModel(content=record.description),
                assignee_uids,
                dispatch_effects=False,
                order_override=record.order,
            )
            if created is None:
                raise ExternalImportError("card creation failed")
            target, _ = created
            target.deadline_at = record.deadline_at
            db.update(target)
            if record.label_source_ids:
                label_uids = [targets[("label", label_id)].get_uid() for label_id in record.label_source_ids]
                if self._domain.card.update_labels(actor, project, target, label_uids, dispatch_effects=False) is None:
                    raise ExternalImportError("card label assignment failed")
            return target
        elif isinstance(record, ExternalChecklist):
            card = targets[("card", record.card_source_id)]
            target = self._domain.checklist.create(
                actor, project, card, record.title, dispatch_effects=False, order_override=record.order
            )
            if target is None:
                raise ExternalImportError("checklist creation failed")
            return target
        elif isinstance(record, ExternalCheckitem):
            checklist = targets[("checklist", record.checklist_source_id)]
            card = self._card_for_checklist(checklist)
            target = self._domain.checkitem.create(
                actor, project, card, checklist, record.title,
                dispatch_effects=False, order_override=record.order,
            )
            if target is None:
                raise ExternalImportError("checkitem creation failed")
            target.is_checked = record.is_checked
            db.update(target)
            return target
        elif isinstance(record, ExternalRelationship):
            parent = targets[("card", record.parent_card_source_id)]
            child = targets[("card", record.child_card_source_id)]
            result = self._domain.card_relationship.apply_graph_patch(
                actor,
                project,
                parent,
                [],
                [(parent.get_uid(), child.get_uid(), record.relationship_type_uid)],
                [],
                dispatch_effects=False,
            )
            if result is None or len(result["created_relationships"]) != 1:
                raise ExternalImportError("relationship creation failed")
            return self._require_uid(
                db, CardRelationship, result["created_relationships"][0]["uid"], "relationship"
            )
        elif isinstance(record, ExternalComment):
            user, _ = principals[record.author_scim_external_id]
            target = self._domain.card_comment.create(
                user,
                project,
                targets[("card", record.card_source_id)],
                EditorContentModel(content=record.content),
                dispatch_effects=False,
            )
            if target is None:
                raise ExternalImportError("comment creation failed")
            self._restore_historical_timestamps(db, target, record.created_at)
            return target
        elif isinstance(record, ExternalAttachment):
            user, _ = principals[record.author_scim_external_id]
            if staged_file is None:
                raise ExternalImportError("attachment was not staged")
            target = self._domain.card_attachment.create(
                user,
                project,
                targets[("card", record.card_source_id)],
                staged_file,
                dispatch_effects=False,
            )
            if target is None:
                raise ExternalImportError("attachment creation failed")
            self._restore_historical_timestamps(db, target, record.created_at)
            return target
        raise TypeError(f"unsupported external work record: {type(record).__name__}")

    @staticmethod
    def _restore_historical_timestamps(
        db: DbSession, target: CardComment | CardAttachment, created_at: datetime
    ) -> None:
        model = type(target)
        db.exec(
            SqlBuilder.update.table(model).where(model.column("id") == target.id).values({
                model.column("created_at"): created_at,
                model.column("updated_at"): created_at,
            })
        )
        target.created_at = created_at
        target.updated_at = created_at

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
            updated = db.exec(
                SqlBuilder.update.table(ExternalImportRecord)
                .where(ExternalImportRecord.id == lineage.id)
                .values(
                    effects_attempts=ExternalImportRecord.effects_attempts + 1,
                    effects_error=error[:4000] if error else None,
                    effects_dispatched_at=SafeDateTime.now() if error is None else None,
                )
            )
            if updated != 1:
                raise ExternalImportError("import lineage disappeared before side-effect checkpoint")

    @staticmethod
    def _card_for_checklist(checklist: Checklist) -> Card:
        with DbSession.use(readonly=True) as db:
            card = db.exec(SqlBuilder.select.table(Card).where(Card.id == checklist.card_id).limit(1)).first()
        if card is None:
            raise ExternalImportError("checklist card disappeared before side-effect dispatch")
        return card
