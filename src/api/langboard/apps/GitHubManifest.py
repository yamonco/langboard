"""Native Manifest registration boundary; installation remains separately verified."""

import hashlib
import json
import re
import secrets
import httpx
from langboard_shared.core.caching import Cache
from langboard_shared.core.db import DbSession
from langboard_shared.domain.models import AppConnection, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
from langboard_shared.Env import Env
from pydantic import SecretStr


TTL = 600
COOKIE = "langboard_github_manifest_session"


class GitHubManifestUnavailable(Exception):
    pass


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _board(service: DomainService, actor: User, project_uid: str):
    board = service.workflow_stage._authorized_app_board(actor, project_uid, ProjectRoleAction.Update)
    if board is None:
        raise GitHubManifestUnavailable()
    return board


def begin_manifest(
    service: DomainService, actor: User, project_uid: str, organization: str | None = None
) -> tuple[dict, str]:
    board = _board(service, actor, project_uid)
    if organization is not None and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", organization):
        raise ValueError("Invalid GitHub organization")
    state, session = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    Cache.set(
        "github-manifest:" + _digest(state),
        {
            "actor_id": int(actor.id),
            "project_uid": board.get_uid(),
            "session_hash": _digest(session),
        },
        TTL,
    )
    root = Env.PUBLIC_UI_URL.rstrip("/")
    api = Env.API_URL.rstrip("/")
    target = (
        "https://github.com/settings/apps/new"
        if organization is None
        else f"https://github.com/organizations/{organization}/settings/apps/new"
    )
    return {
        "registration_url": target + "?state=" + state,
        "manifest": {
            "name": "Langboard-" + board.get_uid(),
            "url": root,
            "redirect_url": root + f"/board/{board.get_uid()}/settings?github_app_manifest=1",
            "callback_urls": [root + f"/board/{board.get_uid()}/settings"],
            "setup_url": root + f"/board/{board.get_uid()}/settings",
            # Signals are not enabled before an authenticated receiver exists.
            "hook_attributes": {"url": api + "/apps/github/events", "active": False},
            "public": False,
            "default_permissions": {
                "metadata": "read",
                "pull_requests": "read",
                "checks": "read",
                "statuses": "read",
                "deployments": "read",
            },
            "default_events": [],
        },
        "expires_in": TTL,
    }, session


def complete_manifest(
    service: DomainService, actor: User, project_uid: str, state: str, code: str, session: str | None
) -> dict:
    board = _board(service, actor, project_uid)
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", state)
        or not re.fullmatch(r"[a-fA-F0-9]{20,128}", code)
        or not session
    ):
        raise GitHubManifestUnavailable()
    key = "github-manifest:" + _digest(state)
    context = Cache.get(key)
    if (
        not isinstance(context, dict)
        or context.get("actor_id") != int(actor.id)
        or context.get("project_uid") != board.get_uid()
    ):
        raise GitHubManifestUnavailable()
    if not secrets.compare_digest(context.get("session_hash", ""), _digest(session)):
        raise GitHubManifestUnavailable()
    # Atomic claim protects duplicate callbacks across replicas. An ambiguous
    # exchange failure is never retried automatically; begin a new registration.
    if not Cache.set_if_absent(key + ":claimed", True, TTL):
        raise GitHubManifestUnavailable()
    Cache.delete(key)
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(
                "https://api.github.com/app-manifests/" + code + "/conversions",
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if response.status_code != 201:
                raise GitHubManifestUnavailable()
            data = response.json()
        if not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] <= 0:
            raise GitHubManifestUnavailable()
        if not isinstance(data.get("slug"), str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,100}", data["slug"]):
            raise GitHubManifestUnavailable()
        if any(
            not isinstance(data.get(field), str) or not data[field]
            for field in ("pem", "webhook_secret", "client_id", "client_secret")
        ):
            raise GitHubManifestUnavailable()
        app_id = data["id"]
        # Current authority re-evaluation before storing a returned credential.
        _board(service, actor, project_uid)
        reference = service.secret_reference.create(
            actor,
            "personal",
            "me",
            f"github/app-{app_id}",
            SecretStr(
                json.dumps(
                    {field: data[field] for field in ("id", "pem", "webhook_secret", "client_id", "client_secret")}
                )
            ),
            source=SecretAuditSource("api", "github_manifest"),
        )
        try:
            with DbSession.atomic() as db:
                _board(service, actor, project_uid)
                connection = AppConnection(
                    app_key="github",
                    owner_id=actor.id,
                    instance_url="https://github.com",
                    external_account_id=str(app_id),
                    credential_reference=reference["uri"],
                    state="pending",
                )
                db.insert(connection)
        except Exception:
            service.secret_reference.revoke(
                actor, reference["uri"], reference["revision"], source=SecretAuditSource("api", "github_manifest")
            )
            raise
        return {
            "connection_uid": connection.get_uid(),
            "state": "pending",
            "app_id": app_id,
            "installation_url": f"https://github.com/apps/{data['slug']}/installations/new",
            "installation_verified": False,
        }
    except GitHubManifestUnavailable:
        raise
    except Exception:
        # Do not expose GitHub response bodies, one-time codes or credential data.
        raise GitHubManifestUnavailable() from None
