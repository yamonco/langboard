import argparse
import json
from pathlib import Path
from secrets import token_urlsafe
from time import monotonic, sleep
from uuid import UUID
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import Card, InternalBot, Project, User, UserNotification
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.models.UserNotification import NotificationType
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.publishers import UserPublisher


parser = argparse.ArgumentParser()
parser.add_argument(
    "action",
    choices=[
        "create",
        "configure-langflow",
        "configure-editor-ai",
        "create-wiki",
        "credentials",
        "notify",
        "status",
        "revoke",
        "restore",
        "cleanup",
    ],
)
parser.add_argument("run_id", type=UUID)
parser.add_argument("--access-ttl", type=int)
parser.add_argument("--api-url")
parser.add_argument("--api-key")
args = parser.parse_args()
run_id = str(args.run_id)
manifest_path = Path("/app/local/socket-migration") / f"editor-access-{run_id}.json"
title = f"Migration editor access probe {run_id}"
isolation_title = f"Migration isolation probe {run_id}"
service = DomainService()


def prepare_peer(project: Project, peer: User, *, include_wiki: bool = False) -> None:
    service.project.repo.project_assigned_user.ensure_assigned(project, peer)
    actions = [ProjectRoleAction.Read.value, ProjectRoleAction.CardUpdate.value]
    if include_wiki:
        actions.append(ProjectRoleAction.Update.value)
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
                    "is_admin": False,
                    "preferred_lang": "en-US",
                    "industry": "Software",
                    "purpose": "Migration verification",
                }
            )
            users.append(user)
        owner, peer, outsider = users
        project = service.project.create(owner, title)
        isolation_project = service.project.create(owner, isolation_title)
        prepare_peer(project, peer)
        column = service.project_column.create(owner, project, "Editor verification")
        card_title = f"Migration card {run_id}"
        result = service.card.create(owner, project, column, card_title)
        if not result:
            raise RuntimeError("Could not create the synthetic Card")
        card, _response = result
        manifest = {
            "project_uid": project.get_uid(),
            "isolation_project_uid": isolation_project.get_uid(),
            "card_uid": card.get_uid(),
            "card_title": card_title,
            "owner_uid": owner.get_uid(),
            "peer_uid": peer.get_uid(),
            "outsider_uid": outsider.get_uid(),
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
            require_synthetic_project(project, title)
        if (
            "isolation_project_uid" in manifest
            and not isolation_already_deleted
            and (not isinstance(isolation_project, Project) or isolation_project.title != isolation_title)
        ):
            raise ValueError("Not this run's isolation project")
        if not already_deleted:
            require_synthetic_card(card, manifest["project_uid"], manifest.get("card_title", title))
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
            prepare_peer(active_project, peer, include_wiki=True)
            manifest["wiki_uid"] = wiki.get_uid()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            print(json.dumps(manifest))
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
        elif args.action == "notify":
            active_project = require_synthetic_project(project, title)
            active_card = require_synthetic_card(card, manifest["project_uid"], manifest.get("card_title", title))
            if "notification_uids" in manifest:
                raise ValueError("Synthetic notifications already exist")

            notification_uids: dict[str, str] = {}
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

            manifest["notification_uids"] = notification_uids
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            print(json.dumps({"notification_uids": notification_uids}))
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
        elif args.action == "cleanup":
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
            service.user.delete(peer)
            service.user.delete(owner)
            service.user.delete(outsider)
            manifest_path.unlink(missing_ok=True)
            print(json.dumps({"deleted": manifest}))
finally:
    service.close()
