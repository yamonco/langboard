"""Trusted host secret resolution; intentionally absent from MCP/value-read routes."""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4
from pydantic import SecretStr
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseDomainService
from ....core.security import KeyVault
from ....core.security.CollaborationChannel import CollaborationChannel
from ....core.security.vault.VaultProvider import VaultProvider
from ....helpers import InfraHelper
from ...models import (
    Card,
    Organization,
    ProjectWiki,
    ProjectWikiAssignedUser,
    SecretReference,
    SecretReferenceAudit,
    User,
)
from ...models.ProjectRole import ProjectRoleAction
from ..CardVisibilityPolicy import CardVisibility
from .CardService import CardService
from .ProjectWikiService import ProjectWikiService
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

    kind: Literal["runtime", "card", "wiki", "app_connection", "api", "cli", "workflow"] = "runtime"
    uid: str | None = None
    request_id: str | None = None
    reason_code: (
        Literal[
            "user_input",
            "integration_setup",
            "routine_rotation",
            "credential_expired",
            "security_response",
            "runtime_use",
            "reference_created",
            "reference_copied",
            "reference_renamed",
            "reference_moved",
            "reference_revoked",
            "value_rotated",
            "reference_bound",
            "provider_migrated",
        ]
        | None
    ) = None

    def __post_init__(self):
        if self.kind not in {"runtime", "card", "wiki", "app_connection", "api", "cli", "workflow"}:
            raise ValueError("Unknown secret audit source")
        if self.uid is not None and (
            not isinstance(self.uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.uid)
        ):
            raise ValueError("Invalid secret audit source identifier")
        if self.request_id is not None and (
            not isinstance(self.request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.request_id)
        ):
            raise ValueError("Invalid secret audit request identifier")
        if self.reason_code not in {
            None,
            "user_input",
            "integration_setup",
            "routine_rotation",
            "credential_expired",
            "security_response",
            "runtime_use",
            "reference_created",
            "reference_copied",
            "reference_renamed",
            "reference_moved",
            "reference_revoked",
            "value_rotated",
            "reference_bound",
            "provider_migrated",
        }:
            raise ValueError("Invalid secret audit reason code")


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
                request_id=source.request_id or uuid4().hex,
                reason_code=source.reason_code
                or {
                    "created": "reference_created",
                    "resolved": "runtime_use",
                    "renamed": "reference_renamed",
                    "moved": "reference_moved",
                    "revoked": "reference_revoked",
                    "rotated": "value_rotated",
                    "bound": "reference_bound",
                    "migrated": "provider_migrated",
                }[action],
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
                        lock=True,
                        revocation=True,
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

    def copy(self, actor: User, uri: str, name: str, expected_revision: int) -> dict:
        """Explicit native copy within the current scope; material never leaves the vault boundary."""
        if DbSession.has_active_transaction():
            raise RuntimeError("Credential storage must own its transaction")
        name = validate_secret_name(name)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Invalid secret copy revision")
        provider = KeyVault.provider
        new_locator = None
        try:
            with DbSession.atomic() as db:
                original = self._find(actor, uri, lock=True)
                if original.revision != expected_revision:
                    raise SecretReferenceConflict()
                if original.state != "active" or original.provider != provider.name():
                    raise SecretReferenceUnavailable()
                try:
                    material = provider.get_key(original.locator)
                except KeyError:
                    raise SecretReferenceUnavailable() from None
                if not isinstance(material, str) or not material:
                    raise SecretReferenceUnavailable()
                new_locator = provider.store_secret(uuid4().hex, material)
                reference = SecretReference(
                    scope=original.scope,
                    scope_id=original.scope_id,
                    name=name,
                    creator_id=actor.id,
                    provider=provider.name(),
                    locator=new_locator,
                )
                db.insert(reference)
                source = SecretAuditSource("api", "secret_copy", request_id=uuid4().hex, reason_code="reference_copied")
                self._audit(db, actor, original, "copied", source)
                self._audit(db, actor, reference, "created", source)
                return reference.metadata()
        except Exception:
            if new_locator is not None:
                provider.delete_key(new_locator)
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

    def _visible_card_sources(
        self, actor: User, rows: Sequence[SecretReferenceAudit], channel: CollaborationChannel
    ) -> dict[str, str]:
        """Bounded source projection; audit ownership never grants card access."""
        uids = {
            row.source_uid
            for row in rows
            if row.source_kind == "card"
            and isinstance(row.source_uid, str)
            and re.fullmatch(r"[A-Za-z0-9]{1,11}", row.source_uid)
        }
        if not uids:
            return {}
        with DbSession.use(readonly=False) as db:
            cards = db.exec(
                SqlBuilder.select.table(Card).where(
                    Card.id.in_([InfraHelper.convert_id(uid) for uid in uids]), Card.deleted_at.is_(None)
                )
            ).all()
        contexts = {}
        links = {}
        card_service = self._get_service(CardService)
        for card in cards:
            if card.project_id not in contexts:
                board = self._get_service(WorkflowStageService)._authorized_app_board(
                    actor, card.project_id, ProjectRoleAction.Read, revocation=True
                )
                contexts[card.project_id] = (
                    card_service.resolve_visibility_context(card.project_id, actor, channel) if board else None
                )
            resolved = contexts[card.project_id]
            if resolved is None:
                continue
            project, context = resolved
            if context.can_read_card(CardVisibility(card.visibility), owner_user_id=card.owner_user_id):
                links[card.get_uid()] = f"/board/{project.get_uid()}/{card.get_uid()}"
        return links

    def _visible_wiki_sources(self, actor: User, rows: Sequence[SecretReferenceAudit]) -> dict[str, str]:
        """Current board and native wiki authority; secret ownership grants neither."""
        uids = {
            row.source_uid
            for row in rows
            if row.source_kind == "wiki"
            and isinstance(row.source_uid, str)
            and re.fullmatch(r"[A-Za-z0-9]{1,11}", row.source_uid)
        }
        if not uids:
            return {}
        with DbSession.use(readonly=False) as db:
            wikis = db.exec(
                SqlBuilder.select.table(ProjectWiki).where(
                    ProjectWiki.id.in_([InfraHelper.convert_id(uid) for uid in uids]), ProjectWiki.deleted_at.is_(None)
                )
            ).all()
        with DbSession.use(readonly=False) as db:
            current = db.exec(SqlBuilder.select.table(User).where(User.id == actor.id)).first()
            assignments = (
                db.exec(
                    SqlBuilder.select.columns(ProjectWikiAssignedUser.project_wiki_id).where(
                        ProjectWikiAssignedUser.project_wiki_id.in_([wiki.id for wiki in wikis]),
                        ProjectWikiAssignedUser.user_id == actor.id,
                    )
                ).all()
                if wikis
                else []
            )
        assigned_wiki_ids = {row[0] for row in assignments}
        if current is None or current.deleted_at or not current.activated_at:
            return {}
        boards = {}
        links = {}
        wiki_service = self._get_service(ProjectWikiService)
        for wiki in wikis:
            if wiki.project_id not in boards:
                boards[wiki.project_id] = self._get_service(WorkflowStageService)._authorized_app_board(
                    actor, wiki.project_id, ProjectRoleAction.Read, revocation=True
                )
            project = boards[wiki.project_id]
            if project is not None and wiki_service.can_view(
                current, project, wiki, [current.id] if wiki.id in assigned_wiki_ids else []
            ):
                links[wiki.get_uid()] = f"/board/{project.get_uid()}/wiki/{wiki.get_uid()}"
        return links

    def list_audit(
        self,
        actor: User,
        uri: str,
        *,
        limit: int = 25,
        cursor: str | None = None,
        channel: CollaborationChannel = CollaborationChannel.Api,
    ) -> dict:
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
            source_links = {
                "card": self._visible_card_sources(actor, rows[:limit], channel),
                "wiki": self._visible_wiki_sources(actor, rows[:limit]),
            }
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
                        - (1 if row.action in {"renamed", "moved", "revoked", "rotated", "migrated"} else 0),
                        "revision_after": row.reference_revision,
                        # Cross-resource source links require their own current ACL.
                        "source_kind": row.source_kind,
                        **(
                            {
                                "source_link": {
                                    "kind": row.source_kind,
                                    "href": source_links[row.source_kind][row.source_uid],
                                }
                            }
                            if row.source_uid in source_links.get(row.source_kind, {})
                            else {}
                        ),
                        "request_id": hashlib.sha256(row.request_id.encode()).hexdigest()
                        if row.source_kind == "api"
                        and row.source_uid == "secret_input"
                        and isinstance(row.request_id, str)
                        and re.fullmatch(r"[A-Za-z0-9_-]{43}", row.request_id)
                        else row.request_id,
                        "reason_code": row.reason_code,
                    }
                    for row in rows[:limit]
                ],
                "next_cursor": rows[limit - 1].get_uid() if len(rows) > limit else None,
            }

    def audit_binding(self, actor: User, uri: str, expected_revision: int, *, source: SecretAuditSource) -> None:
        """Trusted host binding receipt, committed atomically with its destination."""
        if not DbSession.has_active_transaction():
            raise RuntimeError("Binding audit requires its destination transaction")
        if source.kind != "app_connection" or source.uid is None or source.reason_code not in {None, "reference_bound"}:
            raise ValueError("Binding audit requires a trusted connection source")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Invalid secret binding revision")
        with DbSession.atomic() as db:
            reference = self._find(actor, uri, lock=True)
            if reference.state != "active":
                raise SecretReferenceUnavailable()
            if reference.revision != expected_revision:
                raise SecretReferenceConflict()
            self._audit(db, actor, reference, "bound", source)

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

    def migrate_provider(
        self,
        actor: User,
        uri: str,
        expected_revision: int,
        source_provider: VaultProvider,
        *,
        source: SecretAuditSource = SecretAuditSource(),
    ) -> dict:
        """Trusted host migration to its configured provider; never a model tool.

        The operator supplies an already authenticated old provider instance.
        No endpoint, credential, locator or plaintext is accepted or returned.
        """
        if DbSession.has_active_transaction():
            raise RuntimeError("Credential storage must own its transaction")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Invalid secret migration revision")
        target = KeyVault.provider
        if not isinstance(source_provider, VaultProvider) or not isinstance(target, VaultProvider):
            raise ValueError("Migration requires trusted vault provider instances")
        if source_provider.name() == target.name() or source.reason_code not in {None, "provider_migrated"}:
            raise ValueError("Invalid secret provider migration")
        new_locator = None
        try:
            with DbSession.atomic() as db:
                reference = self._find(actor, uri, lock=True)
                if reference.revision != expected_revision:
                    raise SecretReferenceConflict()
                if reference.state != "active" or reference.provider != source_provider.name():
                    raise SecretReferenceUnavailable()
                old_locator = reference.locator
                try:
                    material = source_provider.get_key(old_locator)
                except KeyError:
                    raise SecretReferenceUnavailable() from None
                if not isinstance(material, str) or not material:
                    raise SecretReferenceUnavailable()
                new_locator = target.store_secret(uuid4().hex, material)
                # Verify the destination before committing or retiring source material.
                if target.get_key(new_locator) != material:
                    raise SecretReferenceUnavailable()
                reference.provider = target.name()
                reference.locator = new_locator
                reference.revision += 1
                db.update(reference)
                self._audit(db, actor, reference, "migrated", source)
                db.after_commit(lambda: source_provider.delete_key(old_locator))
                return reference.metadata()
        except Exception:
            if new_locator is not None:
                target.delete_key(new_locator)
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
