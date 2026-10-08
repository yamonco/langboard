"""Trusted host secret resolution; intentionally absent from MCP/value-read routes."""

import re
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4
from pydantic import SecretStr
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseDomainService
from ....core.security import KeyVault
from ....helpers import InfraHelper
from ...models import Organization, SecretReference, SecretReferenceAudit, User
from ...models.ProjectRole import ProjectRoleAction
from .WorkflowStageService import WorkflowStageService


class SecretReferenceUnavailable(Exception):
    """Uniform error: absent, revoked, unauthorized, or wrong provider."""


class SecretReferenceConflict(Exception):
    pass


def validate_secret_name(name: str) -> str:
    if not isinstance(name, str) or len(name) > 256 or not re.fullmatch(r"[a-z0-9_-]+(?:/[a-z0-9_-]+){0,7}", name):
        raise ValueError("Invalid logical secret name")
    return name


@dataclass(frozen=True)
class SecretAuditSource:
    """Constructed by a trusted host adapter, never from a caller's arbitrary text."""

    kind: Literal["runtime", "card", "app_connection", "api", "cli", "workflow"] = "runtime"
    uid: str | None = None

    def __post_init__(self):
        if self.kind not in {"runtime", "card", "app_connection", "api", "cli", "workflow"}:
            raise ValueError("Unknown secret audit source")
        if self.uid is not None and (
            not isinstance(self.uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.uid)
        ):
            raise ValueError("Invalid secret audit source identifier")


class SecretReferenceService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "secret_reference"

    def _audit(self, db, actor: User, reference: SecretReference, action: str, source: SecretAuditSource):
        db.insert(
            SecretReferenceAudit(
                reference_id=reference.id,
                actor_id=actor.id,
                action=action,
                source_kind=source.kind,
                source_uid=source.uid,
                scope=reference.scope,
                scope_id=reference.scope_id,
                reference_revision=reference.revision,
            )
        )

    def _authorize(self, actor: User, scope: str, scope_id: int) -> bool:
        with DbSession.use(readonly=False) as db:
            if not isinstance(actor, User):
                return False
            current = db.exec(SqlBuilder.select.table(User).where(User.id == actor.id).with_for_update()).first()
            if current is None or current.deleted_at or not current.activated_at:
                return False
            if scope == "personal":
                return current.id == scope_id
            if scope == "project":
                return (
                    self._get_service(WorkflowStageService)._authorized_app_board(
                        current,
                        scope_id,
                        ProjectRoleAction.Update,
                    )
                    is not None
                )
            if scope == "workspace":
                workspace = db.exec(
                    SqlBuilder.select.table(Organization).where(Organization.id == scope_id).with_for_update()
                ).first()
                return bool(
                    workspace
                    and workspace.is_active
                    and not workspace.suspended_at
                    and workspace.owner_user_id == current.id
                )
            return False

    def create(
        self,
        actor: User,
        scope: str,
        scope_uid: str,
        name: str,
        value: SecretStr,
        *,
        source: SecretAuditSource = SecretAuditSource(),
    ) -> dict:
        if DbSession.has_active_transaction():
            raise RuntimeError("Credential storage must own its transaction")
        name = validate_secret_name(name)
        scope_id = int(actor.id) if scope == "personal" and scope_uid == "me" else InfraHelper.convert_id(scope_uid)
        if not isinstance(value, SecretStr) or not value.get_secret_value():
            raise ValueError("Secret material must be a nonempty SecretStr")
        locator = None
        try:
            with DbSession.atomic() as db:
                if not self._authorize(actor, scope, scope_id):
                    raise SecretReferenceUnavailable()
                reference = SecretReference(
                    scope=scope,
                    scope_id=scope_id,
                    name=name,
                    creator_id=actor.id,
                    provider=KeyVault.provider.name(),
                    locator="",
                )
                # Separate opaque storage ID; URI/name changes never rename a vault path.
                locator = KeyVault.store_secret(uuid4().hex, value.get_secret_value())
                reference.locator = locator
                db.insert(reference)
                self._audit(db, actor, reference, "created", source)
                return reference.metadata()
        except Exception:
            if locator is not None:
                KeyVault.delete_key(locator)
            raise

    def _find(self, actor: User, uri: str, *, lock=False) -> SecretReference:
        if not isinstance(uri, str) or not uri.startswith("secret://"):
            raise SecretReferenceUnavailable()
        parts = uri.removeprefix("secret://").split("/")
        statement = SqlBuilder.select.table(SecretReference)
        if len(parts) == 2 and parts[0] == "ref" and re.fullmatch(r"[A-Za-z0-9]{1,11}", parts[1]):
            statement = statement.where(SecretReference.id == InfraHelper.convert_id(parts[1]))
        elif len(parts) >= 2 and parts[0] == "me":
            if not isinstance(actor, User):
                raise SecretReferenceUnavailable()
            scope, scope_id, name = "personal", actor.id, "/".join(parts[1:])
            validate_secret_name(name)
            statement = statement.where(
                SecretReference.scope == scope, SecretReference.scope_id == scope_id, SecretReference.name == name
            )
        elif len(parts) >= 3 and parts[0] in {"project", "workspace"} and re.fullmatch(r"[A-Za-z0-9]{1,11}", parts[1]):
            validate_secret_name("/".join(parts[2:]))
            statement = statement.where(
                SecretReference.scope == parts[0],
                SecretReference.scope_id == InfraHelper.convert_id(parts[1]),
                SecretReference.name == "/".join(parts[2:]),
            )
        else:
            raise SecretReferenceUnavailable()
        with DbSession.use(readonly=False) as db:
            reference = db.exec(statement.with_for_update() if lock else statement).first()
            if reference is None or not self._authorize(actor, reference.scope, reference.scope_id):
                raise SecretReferenceUnavailable()
            return reference

    def get_metadata(self, actor: User, uri: str) -> dict:
        with DbSession.atomic():
            return self._find(actor, uri).metadata()

    def list_audit(self, actor: User, uri: str, *, limit: int = 25, cursor: str | None = None) -> dict:
        """Current authority plus bounded per-reference history, never vault reads."""
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid secret history limit")
        if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r"[A-Za-z0-9]{1,11}", cursor)):
            raise SecretReferenceUnavailable()
        with DbSession.atomic() as db:
            reference = self._find(actor, uri, lock=True)
            statement = SqlBuilder.select.table(SecretReferenceAudit).where(
                SecretReferenceAudit.reference_id == reference.id
            )
            if cursor is not None:
                anchor = db.exec(
                    SqlBuilder.select.table(SecretReferenceAudit).where(
                        SecretReferenceAudit.reference_id == reference.id,
                        SecretReferenceAudit.id == InfraHelper.convert_id(cursor),
                    )
                ).first()
                if anchor is None:
                    raise SecretReferenceUnavailable()
                statement = statement.where(SecretReferenceAudit.id < anchor.id)
            rows = db.exec(statement.order_by(SecretReferenceAudit.id.desc()).limit(limit + 1)).all()
            return {
                "secret_ref": reference.metadata()["uri"],
                "items": [
                    {
                        "uid": row.get_uid(),
                        "created_at": row.created_at.isoformat(),
                        "actor_uid": InfraHelper.convert_uid(row.actor_id),
                        "action": row.action,
                        "revision_before": None
                        if row.action == "created"
                        else row.reference_revision
                        - (1 if row.action in {"renamed", "moved", "revoked", "rotated"} else 0),
                        "revision_after": row.reference_revision,
                        # Cross-resource source links require their own current ACL.
                        "source_kind": row.source_kind,
                    }
                    for row in rows[:limit]
                ],
                "next_cursor": rows[limit - 1].get_uid() if len(rows) > limit else None,
            }

    def resolve_for_runtime(
        self, actor: User, uri: str, *, source: SecretAuditSource = SecretAuditSource()
    ) -> SecretStr:
        with DbSession.atomic() as db:
            reference = self._find(actor, uri, lock=True)
            if reference.state != "active" or reference.provider != KeyVault.provider.name():
                raise SecretReferenceUnavailable()
            try:
                material = KeyVault.get_key(reference.locator)
                if not material:
                    raise SecretReferenceUnavailable()
                self._audit(db, actor, reference, "resolved", source)
                return SecretStr(material)
            except KeyError:
                raise SecretReferenceUnavailable() from None

    def rename(
        self,
        actor: User,
        uri: str,
        name: str,
        expected_revision: int,
        *,
        source: SecretAuditSource = SecretAuditSource(),
    ) -> dict:
        name = validate_secret_name(name)
        with DbSession.atomic() as db:
            reference = self._find(actor, uri, lock=True)
            if reference.revision != expected_revision:
                raise SecretReferenceConflict()
            reference.name = name
            reference.revision += 1
            db.update(reference)
            self._audit(db, actor, reference, "renamed", source)
            return reference.metadata()

    def move(
        self,
        actor: User,
        uri: str,
        scope: str,
        scope_uid: str,
        expected_revision: int,
        *,
        source: SecretAuditSource = SecretAuditSource(),
    ) -> dict:
        scope_id = int(actor.id) if scope == "personal" and scope_uid == "me" else InfraHelper.convert_id(scope_uid)
        with DbSession.atomic() as db:
            reference = self._find(actor, uri, lock=True)
            if reference.revision != expected_revision:
                raise SecretReferenceConflict()
            if not self._authorize(actor, scope, scope_id):
                raise SecretReferenceUnavailable()
            reference.scope = scope
            reference.scope_id = scope_id
            reference.revision += 1
            db.update(reference)
            self._audit(db, actor, reference, "moved", source)
            return reference.metadata()

    def rotate(
        self,
        actor: User,
        uri: str,
        value: SecretStr,
        expected_revision: int,
        *,
        source: SecretAuditSource = SecretAuditSource(),
    ) -> dict:
        if DbSession.has_active_transaction():
            raise RuntimeError("Credential storage must own its transaction")
        if not isinstance(value, SecretStr) or not value.get_secret_value():
            raise ValueError("Secret material must be a nonempty SecretStr")
        new_locator = None
        provider = KeyVault.provider
        try:
            with DbSession.atomic() as db:
                reference = self._find(actor, uri, lock=True)
                if reference.revision != expected_revision:
                    raise SecretReferenceConflict()
                if reference.state != "active" or reference.provider != provider.name():
                    raise SecretReferenceUnavailable()
                old_locator = reference.locator
                new_locator = provider.store_secret(uuid4().hex, value.get_secret_value())
                reference.locator = new_locator
                reference.revision += 1
                db.update(reference)
                self._audit(db, actor, reference, "rotated", source)
                # Commit the new reference before retiring old material. Callback
                # failure leaves a valid new reference and a cleanup obligation.
                db.after_commit(lambda: provider.delete_key(old_locator))
                return reference.metadata()
        except Exception:
            if new_locator is not None:
                provider.delete_key(new_locator)
            raise

    def revoke(
        self, actor: User, uri: str, expected_revision: int, *, source: SecretAuditSource = SecretAuditSource()
    ) -> dict:
        with DbSession.atomic() as db:
            reference = self._find(actor, uri, lock=True)
            if reference.revision != expected_revision:
                raise SecretReferenceConflict()
            reference.state = "revoked"
            reference.revision += 1
            db.update(reference)
            self._audit(db, actor, reference, "revoked", source)
            # Deny immediately in host storage, even when KMS cannot erase ciphertext.
            return reference.metadata()
