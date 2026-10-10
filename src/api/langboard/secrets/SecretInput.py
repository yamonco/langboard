"""Authenticated one-use browser input; credentials never enter the MCP plane."""

import hashlib
import re
import secrets
from time import time
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
REASONS = {
    "create": ("user_input", "integration_setup"),
    "rotate": ("user_input", "routine_rotation", "credential_expired", "security_response"),
}


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
    return _begin(
        actor,
        {
            "scope": scope,
            "scope_id": scope_id,
            "scope_uid": scope_uid,
            "name": name,
            "operation": "create",
        },
    )


def begin_rotation(service, actor, uri, expected_revision):
    from langboard_shared.helpers import InfraHelper

    reference = service.secret_reference.get_metadata(actor, uri)
    if (
        reference["state"] != "active"
        or type(expected_revision) is not int
        or expected_revision < 0
        or reference["revision"] != expected_revision
    ):
        raise SecretReferenceUnavailable()
    return _begin(
        actor,
        {
            "scope": reference["scope"],
            "scope_id": InfraHelper.convert_id(reference["scope_uid"]),
            "scope_uid": reference["scope_uid"],
            "name": reference["name"],
            "operation": "rotate",
            "secret_ref": reference["uri"],
            "expected_revision": expected_revision,
        },
    )


def _begin(actor, target):
    root = Env.PUBLIC_UI_URL.rstrip("/")
    parsed = urlsplit(root)
    if not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise SecretReferenceUnavailable()
    if parsed.scheme != "https" and not (Env.ENVIRONMENT == "development" and parsed.scheme == "http"):
        raise SecretReferenceUnavailable()
    uid = secrets.token_urlsafe(32)
    context = {**target, "actor_id": int(actor.id), "state": "pending", "expires_at": time() + TTL}
    # Retain a bounded tombstone after expiry, without extending input validity.
    Cache.set(_key(uid), context, TTL * 2)
    return {"input_uid": uid, "input_url": root + "/secret-input/" + uid, "expires_in": TTL, "state": "pending"}


def _pending(service, actor, uid):
    context = _context(service, actor, uid)
    if context["state"] != "pending" or time() >= context["expires_at"]:
        raise SecretReferenceUnavailable()
    if context["operation"] == "rotate":
        reference = service.secret_reference.get_metadata(actor, context["secret_ref"])
        if reference["state"] != "active" or reference["revision"] != context["expected_revision"]:
            raise SecretReferenceUnavailable()
    return context


def _claim(uid, context):
    if not Cache.set_if_absent(_key(uid) + ":claimed", True, TTL):
        raise SecretReferenceUnavailable()
    # Authority/cache access can wait long enough to cross the deadline.
    # Consume the nonce but never submit material after its input expiry.
    if time() >= context["expires_at"]:
        raise SecretReferenceUnavailable()
    Cache.delete(_key(uid) + ":browser")


def _save(uid, context):
    Cache.set(_key(uid), context, max(1, int(context["expires_at"] + TTL - time())))


def input_status(service, actor, uid):
    context = _context(service, actor, uid)
    result = {
        "state": "expired" if context["state"] == "pending" and time() >= context["expires_at"] else context["state"]
    }
    if context["state"] == "completed":
        # Recheck the resulting reference's current authority, including moves.
        result["secret_ref"] = service.secret_reference.get_metadata(actor, context["secret_ref"])["uri"]
    return result


def open_input(service, actor, uid):
    context = _pending(service, actor, uid)
    if context["state"] != "pending" or Cache.has(_key(uid) + ":claimed"):
        raise SecretReferenceUnavailable()
    challenge = secrets.token_urlsafe(32)
    # Separate short-lived browser proof; opening does not extend the input TTL.
    Cache.set(_key(uid) + ":browser", hashlib.sha256(challenge.encode()).hexdigest(), TTL)
    return {
        "name": context["name"],
        "scope": context["scope"],
        "operation": context["operation"],
        "reason_codes": list(REASONS[context["operation"]]),
    }, challenge


def complete_input(service, actor, uid, value, challenge, reason_code="user_input"):
    context = _pending(service, actor, uid)
    if not isinstance(reason_code, str) or reason_code not in REASONS[context["operation"]]:
        raise SecretReferenceUnavailable()
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
    _claim(uid, context)
    try:
        # The input UID is a bearer URL nonce, not a public audit identifier.
        source = SecretAuditSource(
            "api", "secret_input", request_id=hashlib.sha256(uid.encode()).hexdigest(), reason_code=reason_code
        )
        if context["operation"] == "rotate":
            reference = service.secret_reference.rotate(
                actor,
                context["secret_ref"],
                value,
                context["expected_revision"],
                source=source,
            )
        else:
            reference = service.secret_reference.create(
                actor,
                context["scope"],
                context["scope_uid"],
                context["name"],
                value,
                source=source,
            )
    except Exception:
        # Ambiguous storage failures consume the input. Never retry a credential.
        _save(uid, {**context, "state": "failed"})
        raise SecretReferenceUnavailable() from None
    _save(uid, {**context, "state": "completed", "secret_ref": reference["uri"]})
    return {"state": "completed", "secret_ref": reference["uri"]}


def cancel_input(service, actor, uid):
    context = _pending(service, actor, uid)
    _claim(uid, context)
    _save(uid, {**context, "state": "cancelled"})
    return {"state": "cancelled"}
