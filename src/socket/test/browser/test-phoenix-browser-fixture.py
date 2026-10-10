import argparse
import json
from datetime import timedelta
from pathlib import Path
from secrets import token_urlsafe
from time import monotonic, sleep
from uuid import UUID
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.storage import Storage
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import (
    Bot,
    Card,
    GlobalCardRelationshipType,
    InternalBot,
    OllamaModelPull,
    Project,
    ProjectWiki,
    User,
    UserNotification,
)
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.domain.models.OllamaModelPull import OllamaModelPullStatus
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.models.UserNotification import NotificationType
from langboard_shared.domain.models.UserNotificationUnsubscription import NotificationChannel
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import UserPublisher


parser = argparse.ArgumentParser()
parser.add_argument(
    "action",
    choices=[
        "create",
        "configure-langflow",
        "configure-editor-ai",
        "create-wiki",
        "create-setting-bot",
        "create-authz-targets",
        "delete-authz-targets",
        "credentials",
        "update-peer-name",
        "notify",
        "replay-notify",
        "replay-deleted-notify",
        "status",
        "revoke",
        "restore",
        "prepare-ollama-pull",
        "track-ollama-pull",
        "age-ollama-pull",
        "cleanup",
    ],
)
parser.add_argument("run_id", type=UUID)
parser.add_argument("--access-ttl", type=int)
parser.add_argument("--api-url")
parser.add_argument("--api-key")
parser.add_argument("--admin-owner", action="store_true")
parser.add_argument("--peer-card-write", action="store_true")
parser.add_argument("--relationship-type", action="store_true")
parser.add_argument("--pull-uid")
parser.add_argument("--model-name")
parser.add_argument("--notification-uid")
args = parser.parse_args()
run_id = str(args.run_id)
manifest_path = Path("/app/local/socket-migration") / f"editor-access-{run_id}.json"
title = f"Migration editor access probe {run_id}"
isolation_title = f"Migration isolation probe {run_id}"
service = DomainService()


def prepare_peer(project: Project, peer: User, *, include_wiki: bool = False, card_write: bool = False) -> None:
    service.project.repo.project_assigned_user.ensure_assigned(project, peer)
    actions = [ProjectRoleAction.Read.value, ProjectRoleAction.CardUpdate.value]
    if include_wiki:
        actions.append(ProjectRoleAction.Update.value)
    if card_write:
        actions.append(ProjectRoleAction.CardWrite.value)
    service.project.repo.role.project.grant(actions=actions, project_id=project.id, user_id=peer.id)
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if service.project.is_assigned(peer, project)[0] and set(actions).issubset(
            service.project.get_user_role_actions_by_project(peer, project)
        ):
            return
        sleep(0.1)
    raise RuntimeError("Synthetic membership and roles are not readable")


def require_synthetic_user(kind: str, user: User | None) -> User:
    if not isinstance(user, User) or user.email != f"editor-{kind}-{run_id}@example.invalid":
        raise ValueError("Not this run's synthetic user")
    return user


def require_synthetic_project(project: Project | None, expected_title: str) -> Project:
    if not isinstance(project, Project) or project.title != expected_title:
        raise ValueError("Not this run's synthetic project")
    return project


def require_synthetic_card(card: Card | None, project_uid: str, expected_title: str) -> Card:
    if (
        not isinstance(card, Card)
        or card.project_id != SnowflakeID.from_short_code(project_uid)
        or card.title != expected_title
    ):
        raise ValueError("Not this run's synthetic Card")
    return card


try:
    if args.action == "create":
        if manifest_path.exists():
            raise ValueError("Fixture already exists")
        users = []
        for kind in ("owner", "peer", "outsider"):
            user, _profile = service.user.create(
                {
                    "email": f"editor-{kind}-{run_id}@example.invalid",
                    "firstname": f"Migration {kind.title()}",
                    "lastname": run_id[:8],
                    "password": token_urlsafe(32),
                    "activated_at": SafeDateTime.now(),
                    "is_admin": args.admin_owner and kind == "owner",
                    "preferred_lang": "en-US",
                    "industry": "Software",
                    "purpose": "Migration verification",
                }
            )
            users.append(user)
        owner, peer, outsider = users
        for user in users:
            service.user_notification_setting.toggle_all(user, NotificationChannel.Email, True)
        if args.admin_owner:
            service.user.grant_all_setting_roles(owner)
            service.api_key.grant_all_roles(owner)
            service.mcp_tool_group.grant_all_roles(owner)
        project = service.project.create(owner, title)
        isolation_project = service.project.create(owner, isolation_title)
        prepare_peer(project, peer, card_write=args.peer_card_write)
        column = service.project_column.create(owner, project, "Editor verification")
        card_title = f"Migration card {run_id}"
        result = service.card.create(owner, project, column, card_title)
        if not result:
            raise RuntimeError("Could not create the synthetic Card")
        card, _response = result
        relationship_type = (
            service.app_setting.create_global_relationship(
                f"Migration parent {run_id}", f"Migration child {run_id}"
            )
            if args.relationship_type
            else None
        )
        manifest = {
            "project_uid": project.get_uid(),
            "isolation_project_uid": isolation_project.get_uid(),
            "card_uid": card.get_uid(),
            "card_title": card_title,
            "owner_uid": owner.get_uid(),
            "peer_uid": peer.get_uid(),
            "outsider_uid": outsider.get_uid(),
            "relationship_type_uid": relationship_type.get_uid() if relationship_type else None,
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        print(json.dumps(manifest))
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        project = service.project.get_by_id_like(manifest["project_uid"])
        isolation_project = service.project.get_by_id_like(manifest.get("isolation_project_uid"))
        card = service.card.get_by_id_like(manifest["card_uid"])
        owner = require_synthetic_user("owner", service.user.get_by_id_like(manifest["owner_uid"]))
        peer = require_synthetic_user("peer", service.user.get_by_id_like(manifest["peer_uid"]))
        outsider = require_synthetic_user("outsider", service.user.get_by_id_like(manifest["outsider_uid"]))
        already_deleted = args.action == "cleanup" and project is None
        isolation_already_deleted = args.action == "cleanup" and isolation_project is None
        if not already_deleted:
            allowed_titles = {title}
            if args.action == "cleanup":
                allowed_titles.add(f"Live project {run_id}")
            if not isinstance(project, Project) or project.title not in allowed_titles:
                raise ValueError("Not this run's synthetic project")
        if (
            "isolation_project_uid" in manifest
            and not isolation_already_deleted
            and (not isinstance(isolation_project, Project) or isolation_project.title != isolation_title)
        ):
            raise ValueError("Not this run's isolation project")
        if not already_deleted:
            expected_card_title = manifest.get("card_title", title)
            if args.action == "cleanup" and isinstance(card, Card) and card.title == f"Concurrent card title {run_id}":
                expected_card_title = card.title
            require_synthetic_card(card, manifest["project_uid"], expected_card_title)
        if args.action == "configure-langflow":
            active_project = require_synthetic_project(project, title)
            if "langflow_bot_uid" in manifest:
                raise ValueError("Synthetic Langflow bot already exists")
            if not args.api_url or not args.api_key:
                raise ValueError("Synthetic Langflow endpoint credentials are required")
            internal_bot = service.internal_bot.create(
                bot_type=InternalBotType.ProjectChat,
                display_name=f"Migration Langflow Chat {run_id}",
                platform=BotPlatform.Langflow,
                platform_running_type=BotPlatformRunningType.Endpoint,
                api_url=args.api_url,
                api_key=args.api_key,
                value="api/v1/run/diagnostic",
            )
            try:
                if not service.project.change_internal_bot(active_project, internal_bot):
                    raise RuntimeError("Could not assign synthetic Langflow bot")
                manifest["langflow_bot_uid"] = internal_bot.get_uid()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                print(json.dumps({"langflow_bot_uid": internal_bot.get_uid()}))
            except Exception:
                service.internal_bot.delete(internal_bot)
                raise
        elif args.action == "configure-editor-ai":
            active_project = require_synthetic_project(project, title)
            if "editor_chat_bot_uid" in manifest or "editor_copilot_bot_uid" in manifest:
                raise ValueError("Synthetic Editor AI bots already exist")
            service.project.get_api_assigned_internal_bot_list_with_setting_map(active_project)
            created_bots: list[InternalBot] = []
            try:
                for bot_type, display_name, api_names in (
                    (InternalBotType.EditorChat, f"Migration Editor Chat {run_id}", ["change_card_details"]),
                    (InternalBotType.EditorCopilot, f"Migration Editor Copilot {run_id}", []),
                ):
                    internal_bot = service.internal_bot.create(
                        bot_type=bot_type,
                        display_name=display_name,
                        platform=BotPlatform.Default,
                        platform_running_type=BotPlatformRunningType.Default,
                        value=json.dumps(
                            {
                                "agent_llm": "diagnostic",
                                "api_names": api_names,
                                "system_prompt": "",
                            }
                        ),
                    )
                    created_bots.append(internal_bot)
                    if not service.project.change_internal_bot(active_project, internal_bot):
                        raise RuntimeError(f"Could not assign synthetic {bot_type.value} bot")

                assignment_deadline = monotonic() + 10
                while monotonic() < assignment_deadline:
                    assigned_chat = service.project.get_assigned_internal_bot_by_type(
                        active_project, InternalBotType.EditorChat
                    )
                    assigned_copilot = service.project.get_assigned_internal_bot_by_type(
                        active_project, InternalBotType.EditorCopilot
                    )
                    if (
                        assigned_chat is not None
                        and assigned_chat[0].id == created_bots[0].id
                        and assigned_copilot is not None
                        and assigned_copilot[0].id == created_bots[1].id
                    ):
                        break
                    sleep(0.1)
                else:
                    raise RuntimeError("Synthetic Editor AI bot assignments are not readable")

                manifest["editor_chat_bot_uid"] = created_bots[0].get_uid()
                manifest["editor_copilot_bot_uid"] = created_bots[1].get_uid()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                print(
                    json.dumps(
                        {
                            "editor_chat_bot_uid": created_bots[0].get_uid(),
                            "editor_copilot_bot_uid": created_bots[1].get_uid(),
                        }
                    )
                )
            except Exception:
                for internal_bot in reversed(created_bots):
                    service.internal_bot.delete(internal_bot)
                raise
        elif args.action == "create-wiki":
            active_project = require_synthetic_project(project, title)
            if "wiki_uid" in manifest:
                raise ValueError("Synthetic wiki already exists")
            result = service.project_wiki.create(owner, active_project, f"Migration wiki {run_id}")
            if not result:
                raise RuntimeError("Could not create synthetic wiki")
            wiki, _response = result
            prepare_peer(active_project, peer, include_wiki=True, card_write=args.peer_card_write)
            manifest["wiki_uid"] = wiki.get_uid()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            print(json.dumps(manifest))
        elif args.action == "create-setting-bot":
            if "setting_bot_uid" in manifest:
                raise ValueError("Synthetic Bot already exists")
            bot = service.bot.create(
                name=f"Migration setting bot {run_id}",
                bot_uname=f"migration-{run_id}",
                platform=BotPlatform.Default,
                platform_running_type=BotPlatformRunningType.Default,
                api_url="",
                api_key="",
                ip_whitelist=[],
            )
            if not bot:
                raise RuntimeError("Could not create synthetic Bot")
            manifest["setting_bot_uid"] = bot.get_uid()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            print(json.dumps({"uid": bot.get_uid(), "name": bot.name}))
        elif args.action == "create-authz-targets":
            active_project = require_synthetic_project(project, title)
            if "authz_card_uid" in manifest or "authz_wiki_uid" in manifest:
                raise ValueError("Synthetic authorization targets already exist")
            active_card = require_synthetic_card(card, manifest["project_uid"], manifest["card_title"])
            column = service.project_column.get_by_id_like(active_card.project_column_id)
            if not column:
                raise RuntimeError("Synthetic Card column is unavailable")
            target_title = f"Migration authorization card {run_id}"
            created_card = service.card.create(owner, active_project, column, target_title)
            created_wiki = service.project_wiki.create(owner, active_project, f"Migration authorization wiki {run_id}")
            if not created_card or not created_wiki:
                raise RuntimeError("Could not create synthetic authorization targets")
            manifest["authz_card_uid"] = created_card[0].get_uid()
            manifest["authz_wiki_uid"] = created_wiki[0].get_uid()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            print(json.dumps({"card_uid": manifest["authz_card_uid"], "wiki_uid": manifest["authz_wiki_uid"]}))
        elif args.action == "delete-authz-targets":
            active_project = require_synthetic_project(project, title)
            target_card = require_synthetic_card(
                service.card.get_by_id_like(manifest["authz_card_uid"]),
                manifest["project_uid"],
                f"Migration authorization card {run_id}",
            )
            target_wiki = service.project_wiki.get_by_id_like(manifest["authz_wiki_uid"])
            if (
                not isinstance(target_wiki, ProjectWiki)
                or target_wiki.project_id != active_project.id
                or target_wiki.title != f"Migration authorization wiki {run_id}"
            ):
                raise ValueError("Not this run's synthetic wiki")
            if not service.card.archive(owner, active_project, target_card):
                raise RuntimeError("Could not archive synthetic authorization Card")
            if not service.card.delete(owner, active_project, target_card):
                raise RuntimeError("Could not delete synthetic authorization Card")
            if not service.project_wiki.delete(owner, active_project, target_wiki):
                raise RuntimeError("Could not delete synthetic authorization wiki")
            print(json.dumps({"deleted": True}))
        elif args.action == "credentials":
            if args.access_ttl is not None:
                if args.access_ttl < 1 or args.access_ttl > 60:
                    raise ValueError("Diagnostic access TTL must be 1-60 seconds")
                Env.update_env("JWT_AT_EXPIRATION", str(args.access_ttl))
            print(
                json.dumps(
                    {
                        **manifest,
                        "refresh_cookie_name": Env.REFRESH_TOKEN_NAME,
                        "users": [
                            {
                                "uid": user.get_uid(),
                                "name": user.get_fullname(),
                                "access_token": AuthSecurity.create_access_token(int(user.id)),
                                "refresh_token": AuthSecurity.create_refresh_token(int(user.id)),
                            }
                            for user in (owner, peer)
                        ],
                        "outsider": {
                            "uid": outsider.get_uid(),
                            "name": outsider.get_fullname(),
                            "access_token": AuthSecurity.create_access_token(int(outsider.id)),
                            "refresh_token": AuthSecurity.create_refresh_token(int(outsider.id)),
                        },
                    }
                )
            )
        elif args.action == "update-peer-name":
            first_name = f"Realtime {run_id[:8]}"
            if not service.user.update(peer, {"firstname": first_name}, from_setting=True):
                raise RuntimeError("Could not update synthetic user")
            print(json.dumps({"firstname": first_name}))
        elif args.action == "notify":
            active_project = require_synthetic_project(project, title)
            active_card = require_synthetic_card(card, manifest["project_uid"], manifest.get("card_title", title))
            if "notification_uids" in manifest:
                raise ValueError("Synthetic notifications already exist")

            notification_uids: dict[str, str] = {}
            deleted_replay_payload: dict[str, object] | None = None
            for key, notifier, recipient in (
                ("owner_read", peer, owner),
                ("owner_bulk", peer, owner),
                ("peer", owner, peer),
            ):
                notification = UserNotification(
                    notifier_type="user",
                    notifier_id=notifier.id,
                    receiver_id=recipient.id,
                    notification_type=NotificationType.AssignedToCard,
                    message_vars={},
                    record_list=service.notification.create_record_list([active_project, active_card]),
                    web_fanout_pending=True,
                )
                service.notification.repo.user_notification.insert(notification)
                api_notification = service.notification.convert_to_api_response(
                    notification,
                    [active_project, active_card],
                    notifier,
                )
                UserPublisher.notified(recipient, api_notification)
                service.notification.repo.user_notification.complete_web_fanout(notification)
                notification_uids[key] = notification.get_uid()
                if key == "owner_read":
                    deleted_replay_payload = json.loads(json.dumps(api_notification, default=str))

            manifest["notification_uids"] = notification_uids
            manifest["deleted_replay_payload"] = deleted_replay_payload
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            print(json.dumps({"notification_uids": notification_uids}))
        elif args.action == "replay-deleted-notify":
            payload = manifest.get("deleted_replay_payload")
            notification_uids = manifest.get("notification_uids")
            if not isinstance(payload, dict) or not isinstance(notification_uids, dict):
                raise ValueError("Synthetic deleted notification payload is unavailable")
            if payload.get("uid") != notification_uids.get("owner_read"):
                raise ValueError("Synthetic deleted notification payload does not match owner")
            UserPublisher.notified(owner, payload)
            print(json.dumps({"notification_uid": payload["uid"]}))
        elif args.action == "replay-notify":
            notification_uids = manifest.get("notification_uids")
            if not isinstance(notification_uids, dict) or set(notification_uids) != {
                "owner_read",
                "owner_bulk",
                "peer",
            }:
                raise ValueError("Synthetic notifications are unavailable")
            uid = args.notification_uid or notification_uids["owner_read"]
            if uid not in {notification_uids["owner_read"], notification_uids["owner_bulk"]}:
                raise ValueError("Notification is outside the synthetic owner scope")
            with DbSession.use(readonly=True) as db:
                notification = db.exec(
                    SqlBuilder.select.table(UserNotification).where(
                        UserNotification.column("id") == SnowflakeID.from_short_code(uid)
                    )
                ).first()
            if not isinstance(notification, UserNotification) or notification.receiver_id != owner.id:
                raise ValueError("Synthetic notification does not belong to owner")
            api_notification = service.notification.convert_to_api_response(notification)
            api_notification["read_at"] = None
            UserPublisher.notified(owner, api_notification)
            print(json.dumps({"notification_uid": uid}))
        elif args.action == "status":
            active_project = require_synthetic_project(project, title)
            active_card = require_synthetic_card(card, manifest["project_uid"], manifest.get("card_title", title))
            wiki = service.project_wiki.get_by_id_like(manifest.get("wiki_uid")) if "wiki_uid" in manifest else None
            print(
                json.dumps(
                    {
                        "description": active_card.description.model_dump(mode="json"),
                        "wiki_content": wiki.content.model_dump(mode="json") if wiki else None,
                        "peer_assigned": service.project.is_assigned(peer, active_project)[0],
                        "peer_roles": service.project.get_user_role_actions_by_project(peer, active_project),
                    }
                )
            )
        elif args.action == "revoke":
            active_project = require_synthetic_project(project, title)
            if not service.project.unassign_assignee(owner, active_project, peer):
                raise RuntimeError("Could not revoke synthetic membership")
            print(json.dumps({"revoked": not service.project.is_assigned(peer, active_project)[0]}))
        elif args.action == "restore":
            active_project = require_synthetic_project(project, title)
            prepare_peer(active_project, peer, include_wiki="wiki_uid" in manifest)
            print(json.dumps({"restored": True}))
        elif args.action == "prepare-ollama-pull":
            if not args.model_name or "ollama_pull_model" in manifest:
                raise ValueError("Unexpected Ollama pull source")
            with DbSession.use(readonly=True) as db:
                existing = db.exec(
                    SqlBuilder.select.table(OllamaModelPull).where(
                        OllamaModelPull.column("model_name") == args.model_name
                    )
                ).first()
            if existing is not None:
                raise ValueError("The Ollama pull source already has a persisted row")
            manifest["ollama_pull_model"] = args.model_name
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            print(json.dumps({"ready": args.model_name}))
        elif args.action == "track-ollama-pull":
            if (
                not args.pull_uid
                or args.model_name != manifest.get("ollama_pull_model")
                or "ollama_pull_uid" in manifest
            ):
                raise ValueError("A new Ollama pull identity is required")
            pull = service.ollama_model_pull.repo.ollama_model_pull.get_by_id(
                SnowflakeID.from_short_code(args.pull_uid)
            )
            if not isinstance(pull, OllamaModelPull) or pull.model_name != args.model_name:
                raise ValueError("Ollama pull identity does not match")
            manifest["ollama_pull_uid"] = args.pull_uid
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            print(json.dumps({"tracked": args.pull_uid}))
        elif args.action == "age-ollama-pull":
            if not manifest.get("ollama_pull_uid") or manifest.get("ollama_pull_model") != args.model_name:
                raise ValueError("Tracked Ollama pull is required")
            with DbSession.use(readonly=False) as db:
                updated = db.exec(
                    SqlBuilder.update.table(OllamaModelPull)
                    .values({OllamaModelPull.column("updated_at"): SafeDateTime.now() - timedelta(days=1)})
                    .where(
                        (OllamaModelPull.column("id") == SnowflakeID.from_short_code(manifest["ollama_pull_uid"]))
                        & (OllamaModelPull.column("model_name") == args.model_name)
                        & (OllamaModelPull.column("status") == OllamaModelPullStatus.Running)
                    )
                )
            if updated != 1:
                raise RuntimeError("Tracked Ollama pull is not running")
            print(json.dumps({"aged": manifest["ollama_pull_uid"]}))
        elif args.action == "cleanup":
            with DbSession.use(readonly=False) as db:
                db.exec(
                    SqlBuilder.delete.table(OllamaModelPull).where(
                        OllamaModelPull.column("model_name").in_(
                            [
                                f"phoenix-browser-pull-{run_id}:latest",
                                f"phoenix-browser-worker-loss-{run_id}:latest",
                            ]
                        )
                    )
                )
                if "ollama_pull_uid" in manifest:
                    db.exec(
                        SqlBuilder.delete.table(OllamaModelPull).where(
                            (OllamaModelPull.column("id") == SnowflakeID.from_short_code(manifest["ollama_pull_uid"]))
                            & (OllamaModelPull.column("model_name") == manifest["ollama_pull_model"])
                        )
                    )
            if isinstance(project, Project) and isinstance(card, Card):
                expected_card_title = manifest.get("card_title", title)
                if card.title == f"Concurrent card title {run_id}":
                    expected_card_title = card.title
                synthetic_card = require_synthetic_card(
                    card, manifest["project_uid"], expected_card_title
                )
                for attachment, _ in service.card_attachment.repo.card_attachment.get_list_by_card(synthetic_card):
                    if not Storage.delete(attachment.file):
                        raise RuntimeError("Could not remove synthetic card attachment file")
            if "setting_bot_uid" in manifest:
                bot = service.bot.get_by_id_like(manifest["setting_bot_uid"])
                if isinstance(bot, Bot):
                    if bot.name not in {
                        f"Migration setting bot {run_id}",
                        f"Live bot {run_id[:8]}",
                    } or not service.bot.delete(bot):
                        raise RuntimeError("Could not remove synthetic Bot")
            for key, bot_type, display_name in (
                ("langflow_bot_uid", InternalBotType.ProjectChat, f"Migration Langflow Chat {run_id}"),
                ("editor_chat_bot_uid", InternalBotType.EditorChat, f"Migration Editor Chat {run_id}"),
                ("editor_copilot_bot_uid", InternalBotType.EditorCopilot, f"Migration Editor Copilot {run_id}"),
            ):
                if key not in manifest:
                    continue
                internal_bot = service.internal_bot.get_by_id_like(manifest[key])
                if not isinstance(internal_bot, InternalBot):
                    continue
                if internal_bot.bot_type != bot_type or internal_bot.display_name != display_name:
                    raise ValueError("Not this run's synthetic Editor AI bot")
                if not service.internal_bot.delete(internal_bot):
                    raise RuntimeError(f"Could not remove synthetic {bot_type.value} bot")
            if isinstance(project, Project) and not service.project.delete(owner, project):
                raise RuntimeError("Could not remove synthetic project")
            if isinstance(isolation_project, Project) and not service.project.delete(owner, isolation_project):
                raise RuntimeError("Could not remove synthetic isolation project")
            if manifest.get("relationship_type_uid"):
                relationship_type = InfraHelper.get_by_id_like(
                    GlobalCardRelationshipType, manifest["relationship_type_uid"]
                )
                if not isinstance(relationship_type, GlobalCardRelationshipType) or (
                    relationship_type.parent_name != f"Migration parent {run_id}"
                ) or not service.app_setting.delete_global_relationship(relationship_type):
                    raise RuntimeError("Could not remove synthetic relationship type")
            service.user.delete(peer)
            service.user.delete(owner)
            service.user.delete(outsider)
            manifest_path.unlink(missing_ok=True)
            print(json.dumps({"deleted": manifest}))
finally:
    service.close()
