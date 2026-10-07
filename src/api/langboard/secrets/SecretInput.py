"""Authenticated one-use browser input; credentials never enter the MCP plane."""

import hashlib
import re
import secrets
from urllib.parse import urlsplit
from langboard_shared.core.caching import Cache
from langboard_shared.domain.services.factory.SecretReferenceService import (
    SecretAuditSource,
    SecretReferenceUnavailable,
    validate_secret_name,
)
from langboard_shared.Env import Env
from pydantic import SecretStr


TTL = 600
COOKIE = "langboard_secret_input"


def _key(uid):
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", uid):
        raise SecretReferenceUnavailable()
    return "secret-input:" + hashlib.sha256(uid.encode()).hexdigest()


def _context(service, actor, uid):
    context = Cache.get(_key(uid))
    if not isinstance(context, dict) or context.get("actor_id") != int(actor.id):
        raise SecretReferenceUnavailable()
    if not service.secret_reference._authorize(actor, context["scope"], context["scope_id"]):
        raise SecretReferenceUnavailable()
    return context


def begin_input(service, actor, scope, scope_uid, name):
    from langboard_shared.helpers import InfraHelper

    name = validate_secret_name(name)
    scope_id = int(actor.id) if scope == "personal" and scope_uid == "me" else InfraHelper.convert_id(scope_uid)
    if not service.secret_reference._authorize(actor, scope, scope_id):
        raise SecretReferenceUnavailable()
    root = Env.PUBLIC_UI_URL.rstrip("/")
    parsed = urlsplit(root)
    if not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise SecretReferenceUnavailable()
    if parsed.scheme != "https" and not (Env.ENVIRONMENT == "development" and parsed.scheme == "http"):
        raise SecretReferenceUnavailable()
    uid = secrets.token_urlsafe(32)
    Cache.set(
        _key(uid),
        {
            "actor_id": int(actor.id),
            "scope": scope,
            "scope_id": scope_id,
            "scope_uid": scope_uid,
            "name": name,
            "state": "pending",
            "operation": "create",
        },
        TTL,
    )
    return {"input_uid": uid, "input_url": root + "/secret-input/" + uid, "expires_in": TTL, "state": "pending"}


def input_status(service, actor, uid):
    context = _context(service, actor, uid)
    result = {"state": context["state"]}
    if context["state"] == "completed":
        # Recheck the resulting reference's current authority, including moves.
        result["secret_ref"] = service.secret_reference.get_metadata(actor, context["secret_ref"])["uri"]
    return result


def open_input(service, actor, uid):
    context = _context(service, actor, uid)
    if context["state"] != "pending" or Cache.has(_key(uid) + ":claimed"):
        raise SecretReferenceUnavailable()
    challenge = secrets.token_urlsafe(32)
    # Separate short-lived browser proof; opening does not extend the input TTL.
    Cache.set(_key(uid) + ":browser", hashlib.sha256(challenge.encode()).hexdigest(), TTL)
    return {"name": context["name"], "scope": context["scope"], "operation": "create"}, challenge


def complete_input(service, actor, uid, value, challenge):
    context = _context(service, actor, uid)
    proof = Cache.get(_key(uid) + ":browser")
    if (
        context["state"] != "pending"
        or not isinstance(proof, str)
        or not isinstance(challenge, str)
        or len(challenge) != 43
        or not secrets.compare_digest(proof, hashlib.sha256(challenge.encode()).hexdigest())
        or not isinstance(value, SecretStr)
        or not 1 <= len(value.get_secret_value()) <= 65536
    ):
        raise SecretReferenceUnavailable()
    if not Cache.set_if_absent(_key(uid) + ":claimed", True, TTL):
        raise SecretReferenceUnavailable()
    Cache.delete(_key(uid) + ":browser")
    try:
        reference = service.secret_reference.create(
            actor,
            context["scope"],
            context["scope_uid"],
            context["name"],
            value,
            source=SecretAuditSource("api", "secret_input"),
        )
    except Exception:
        # Ambiguous storage failures consume the input. Never retry a credential.
        Cache.set(_key(uid), {**context, "state": "failed"}, TTL)
        raise SecretReferenceUnavailable() from None
    Cache.set(_key(uid), {**context, "state": "completed", "secret_ref": reference["uri"]}, TTL)
    return {"state": "completed", "secret_ref": reference["uri"]}


def cancel_input(service, actor, uid):
    context = _context(service, actor, uid)
    if context["state"] != "pending" or not Cache.set_if_absent(_key(uid) + ":claimed", True, TTL):
        raise SecretReferenceUnavailable()
    Cache.delete(_key(uid) + ":browser")
    Cache.set(_key(uid), {**context, "state": "cancelled"}, TTL)
    return {"state": "cancelled"}
