"""Session-bound GitHub user authorization discovers accessible installations."""

import base64
import hashlib
import json
import re
import secrets
from urllib.parse import urlencode
import httpx
from langboard_shared.core.caching import Cache
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection
from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
from langboard_shared.Env import Env
from langboard_shared.helpers import InfraHelper
from .GitHubInstallation import API, HEADERS, connection_revision
from .GitHubManifest import TTL, GitHubManifestUnavailable, _board, _digest


COOKIE = "langboard_github_authorization_session"
PROOF_TTL = 300


def _issue_installation_proof(actor, project_uid, connection, installations):
    proof = secrets.token_urlsafe(32)
    Cache.set(
        "github-installation-proof:" + _digest(proof),
        {
            "actor": int(actor.id),
            "board": project_uid,
            "connection": connection.get_uid(),
            "revision": connection_revision(connection),
            "installations": {
                str(item["id"]): item["account"]["id"] for item in installations if not item["suspended"]
            },
        },
        PROOF_TTL,
    )
    return proof


def require_installation_proof(actor, project_uid, connection_uid, installation_id, account_id, proof, revision=None):
    if not isinstance(proof, str) or not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", proof):
        raise GitHubManifestUnavailable()
    context = Cache.get("github-installation-proof:" + _digest(proof))
    if (
        not isinstance(context, dict)
        or context.get("actor") != int(actor.id)
        or context.get("board") != project_uid
        or context.get("connection") != connection_uid
        or context.get("installations", {}).get(str(installation_id)) != account_id
        or revision is not None
        and context.get("revision") != revision
    ):
        raise GitHubManifestUnavailable()


def _credential(service, actor, project_uid, connection_uid):
    _board(service, actor, project_uid)
    with DbSession.use(readonly=False) as db:
        connection = db.exec(
            SqlBuilder.select.table(AppConnection).where(
                AppConnection.id == InfraHelper.convert_id(connection_uid),
                AppConnection.owner_id == actor.id,
                AppConnection.app_key == "github",
            )
        ).first()
    if connection is None or connection.state not in {"pending", "connected"} or not connection.credential_reference:
        raise GitHubManifestUnavailable()
    data = json.loads(
        service.secret_reference.resolve_for_runtime(
            actor, connection.credential_reference, source=SecretAuditSource("app_connection", connection_uid)
        ).get_secret_value()
    )
    if (
        type(data.get("id")) is not int
        or str(data["id"]) != connection.external_account_id
        or any(not isinstance(data.get(field), str) or not data[field] for field in ("client_id", "client_secret"))
    ):
        raise GitHubManifestUnavailable()
    return connection, data


def _callback(project_uid):
    return Env.PUBLIC_UI_URL.rstrip("/") + f"/board/{project_uid}"


def begin_authorization(service, actor, project_uid, connection_uid):
    try:
        connection, credential = _credential(service, actor, project_uid, connection_uid)
        state, session, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        Cache.set(
            "github-authorization:" + _digest(state),
            {
                "actor": int(actor.id),
                "board": project_uid,
                "connection": connection_uid,
                "revision": connection_revision(connection),
                "session": _digest(session),
                "verifier": verifier,
            },
            TTL,
        )
        return {
            "authorization_url": "https://github.com/login/oauth/authorize?"
            + urlencode(
                {
                    "client_id": credential["client_id"],
                    "redirect_uri": _callback(project_uid),
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            ),
            "expires_in": TTL,
        }, session
    except Exception:
        raise GitHubManifestUnavailable() from None


def complete_authorization(service, actor, project_uid, state, code, session):
    try:
        _board(service, actor, project_uid)
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", state)
            or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", code)
            or not session
        ):
            raise GitHubManifestUnavailable()
        key = "github-authorization:" + _digest(state)
        context = Cache.get(key)
        if (
            not isinstance(context, dict)
            or context.get("actor") != int(actor.id)
            or context.get("board") != project_uid
        ):
            raise GitHubManifestUnavailable()
        if not secrets.compare_digest(context.get("session", ""), _digest(session)):
            raise GitHubManifestUnavailable()
        connection, credential = _credential(service, actor, project_uid, context["connection"])
        if connection_revision(connection) != context["revision"]:
            raise GitHubManifestUnavailable()
        if not Cache.set_if_absent(key + ":claimed", True, TTL):
            raise GitHubManifestUnavailable()
        Cache.delete(key)
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": credential["client_id"],
                    "client_secret": credential["client_secret"],
                    "code": code,
                    "redirect_uri": _callback(project_uid),
                    "code_verifier": context["verifier"],
                },
            )
            if response.status_code != 200:
                raise GitHubManifestUnavailable()
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise GitHubManifestUnavailable()
            try:
                headers = {**HEADERS, "Authorization": "Bearer " + token}
                identity = client.get(API + "/user", headers=headers)
                if identity.status_code != 200:
                    raise GitHubManifestUnavailable()
                user = identity.json()
                if type(user.get("id")) is not int or user["id"] <= 0 or not isinstance(user.get("login"), str):
                    raise GitHubManifestUnavailable()
                # Bounded discovery, explicit pagination; never infer absence beyond this page.
                response = client.get(API + "/user/installations", headers=headers, params={"per_page": 100, "page": 1})
                if response.status_code != 200:
                    raise GitHubManifestUnavailable()
                data = response.json()
                rows, count = data.get("installations"), data.get("total_count")
                if not isinstance(rows, list) or len(rows) > 100 or type(count) is not int or count < len(rows):
                    raise GitHubManifestUnavailable()
                installations = []
                for row in rows:
                    account = row.get("account", {})
                    if (
                        row.get("app_id") != int(connection.external_account_id)
                        or type(row.get("id")) is not int
                        or row["id"] <= 0
                    ):
                        raise GitHubManifestUnavailable()
                    if (
                        type(account.get("id")) is not int
                        or account["id"] <= 0
                        or account.get("type") not in {"User", "Organization"}
                        or not isinstance(account.get("login"), str)
                    ):
                        raise GitHubManifestUnavailable()
                    installations.append(
                        {
                            "id": row["id"],
                            "account": {field: account[field] for field in ("id", "login", "type")},
                            "suspended": bool(row.get("suspended_at")),
                        }
                    )
            finally:
                revoked = client.request(
                    "DELETE",
                    API + f"/applications/{credential['client_id']}/token",
                    headers=HEADERS,
                    auth=(credential["client_id"], credential["client_secret"]),
                    json={"access_token": token},
                )
                if revoked.status_code != 204:
                    raise GitHubManifestUnavailable()
        current, _ = _credential(service, actor, project_uid, context["connection"])
        if connection_revision(current) != context["revision"]:
            raise GitHubManifestUnavailable()
        if len({item["id"] for item in installations}) != len(installations):
            raise GitHubManifestUnavailable()
        return {
            "connection_uid": context["connection"],
            "github_user": {"id": user["id"], "login": user["login"]},
            "installations": installations,
            "total_count": count,
            "has_more": count > len(rows),
            "binding_created": False,
            "installation_proof": _issue_installation_proof(actor, project_uid, current, installations),
            "proof_expires_in": PROOF_TTL,
        }
    except Exception:
        raise GitHubManifestUnavailable() from None
