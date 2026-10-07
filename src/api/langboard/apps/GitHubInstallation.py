"""Re-read installation and repository authority from GitHub before binding."""

import json
import time
import httpx
import jwt
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import AppConnection, User
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.factory.SecretReferenceService import SecretAuditSource
from langboard_shared.helpers import InfraHelper
from .GitHubManifest import GitHubManifestUnavailable, _board


API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}


def inspect_installation(
    service: DomainService,
    actor: User,
    project_uid: str,
    connection_uid: str,
    installation_id: int,
    account_id: int,
    page: int = 1,
) -> dict:
    if type(installation_id) is not int or installation_id <= 0 or type(account_id) is not int or account_id <= 0:
        raise GitHubManifestUnavailable()
    if type(page) is not int or not 1 <= page <= 10000:
        raise GitHubManifestUnavailable()
    _board(service, actor, project_uid)
    with DbSession.use(readonly=False) as db:
        connection = db.exec(
            SqlBuilder.select.table(AppConnection).where(
                AppConnection.id == InfraHelper.convert_id(connection_uid),
                AppConnection.app_key == "github",
                AppConnection.owner_id == actor.id,
            )
        ).first()
    if connection is None or connection.state not in {"pending", "connected"} or not connection.credential_reference:
        raise GitHubManifestUnavailable()
    try:
        credential = json.loads(
            service.secret_reference.resolve_for_runtime(
                actor,
                connection.credential_reference,
                source=SecretAuditSource("app_connection", connection.get_uid()),
            ).get_secret_value()
        )
        if type(credential.get("id")) is not int or str(credential["id"]) != connection.external_account_id:
            raise GitHubManifestUnavailable()
        now = int(time.time())
        app_token = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": str(credential["id"])}, credential["pem"], algorithm="RS256"
        )
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(
                f"{API}/app/installations/{installation_id}",
                headers={**HEADERS, "Authorization": "Bearer " + app_token},
            )
            if response.status_code != 200:
                raise GitHubManifestUnavailable()
            installation = response.json()
            account = installation.get("account", {})
            if installation.get("id") != installation_id or installation.get("app_id") != credential["id"]:
                raise GitHubManifestUnavailable()
            if (
                installation.get("suspended_at")
                or account.get("id") != account_id
                or account.get("type") not in {"User", "Organization"}
            ):
                raise GitHubManifestUnavailable()
            if not isinstance(account.get("login"), str) or not account["login"]:
                raise GitHubManifestUnavailable()
            response = client.post(
                f"{API}/app/installations/{installation_id}/access_tokens",
                headers={**HEADERS, "Authorization": "Bearer " + app_token},
                json={"permissions": {"metadata": "read"}},
            )
            if response.status_code != 201:
                raise GitHubManifestUnavailable()
            token = response.json().get("token")
            if not isinstance(token, str) or not token:
                raise GitHubManifestUnavailable()
            token_headers = {**HEADERS, "Authorization": "Bearer " + token}
            try:
                response = client.get(
                    API + "/installation/repositories", headers=token_headers, params={"page": page, "per_page": 100}
                )
                if response.status_code != 200:
                    raise GitHubManifestUnavailable()
                data = response.json()
                repositories = data.get("repositories")
                count = data.get("total_count")
                if type(count) is not int or count < 0 or not isinstance(repositories, list) or len(repositories) > 100:
                    raise GitHubManifestUnavailable()
                items = []
                for repository in repositories:
                    if type(repository.get("id")) is not int or repository["id"] <= 0:
                        raise GitHubManifestUnavailable()
                    if not isinstance(repository.get("full_name"), str) or not repository["full_name"]:
                        raise GitHubManifestUnavailable()
                    if repository.get("owner", {}).get("id") != account_id:
                        raise GitHubManifestUnavailable()
                    items.append(
                        {
                            "id": repository["id"],
                            "name": repository["full_name"],
                            "private": repository.get("private") is True,
                            "archived": repository.get("archived") is True,
                        }
                    )
            finally:
                # Ephemeral access token is never persisted or returned. Failure
                # to revoke prevents successful inspection; no leaked token errors.
                revoked = client.delete(API + "/installation/token", headers=token_headers)
                if revoked.status_code != 204:
                    raise GitHubManifestUnavailable()
        _board(service, actor, project_uid)
        # Re-check current connection revocation after external IO.
        with DbSession.use(readonly=False) as db:
            current = db.exec(SqlBuilder.select.table(AppConnection).where(AppConnection.id == connection.id)).first()
            if current is None or current.owner_id != actor.id or current.state not in {"pending", "connected"}:
                raise GitHubManifestUnavailable()
            if current.credential_reference != connection.credential_reference:
                raise GitHubManifestUnavailable()
        return {
            "connection_uid": connection.get_uid(),
            "installation_id": installation_id,
            "account": {"id": account_id, "login": account["login"], "type": account["type"]},
            "repositories": items,
            "total_count": count,
            "next_page": page + 1 if page * 100 < count else None,
            "binding_created": False,
        }
    except GitHubManifestUnavailable:
        raise
    except Exception:
        raise GitHubManifestUnavailable() from None
