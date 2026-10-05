"""Bounded section replacement deltas; cursors are observations, never permissions."""

import base64
import hashlib
import hmac
import json
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class CardContextDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_uid: str
    current_context_cursor: str | None
    card_change_seq: int
    description_revision: str | None = None
    execution_generation: Any = None
    source_revision: Any = None
    changed_sections: list[str]
    sections: dict[str, Any]
    removed_refs: list[str]
    invalidated_evidence: list[str]
    work_state_changed: bool
    blocker_changed: bool
    permissions_changed: bool
    requires_full_refresh: bool
    reasons: list[str] = Field(default_factory=list)
    cache_policy: str = (
        "Replace returned sections; purge removed_refs. On authorization error purge all cached card context."
    )


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _refs(value, prefix):
    refs = set()
    if isinstance(value, dict):
        uid = value.get("uid") or value.get("wiki_uid")
        if isinstance(uid, str):
            refs.add(f"{prefix}:{uid}")
        for key, child in value.items():
            if key not in {"core", "user", "creator"}:
                refs.update(_refs(child, prefix))
    elif isinstance(value, list):
        for child in value:
            refs.update(_refs(child, prefix))
    return sorted(refs)


def _partial(value):
    if isinstance(value, dict):
        return any(key.endswith("next_cursor") and bool(child) or _partial(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_partial(child) for child in value)
    return False


def _encode(value, key):
    payload = (
        base64.urlsafe_b64encode(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    )
    signature = hmac.new(key.encode(), b"langboard-context-delta-v1:" + payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def _decode(cursor, key, binding):
    if not cursor or len(cursor) > 65536:
        return None
    try:
        payload, signature = cursor.rsplit(".", 1)
        expected = hmac.new(key.encode(), b"langboard-context-delta-v1:" + payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        value = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if value.get("version") != 1 or value.get("binding") != binding:
            return None
        if not isinstance(value.get("hashes"), dict) or not isinstance(value.get("refs"), dict):
            return None
        if any(
            not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs)
            for refs in value["refs"].values()
        ):
            return None
        return value
    except (ValueError, TypeError, AttributeError):
        return None


def card_context_delta(bundle: dict, *, project_uid: str, actor_uid: str, profile: str, cursor: str | None, key: str):
    """Compare only a freshly authorized projection; never replay cursor contents."""
    card_uid = bundle["card_uid"]
    card = bundle["card"]
    core = dict(card["core"])
    sections = {"core": core}
    for name in ("description", "linked_wikis"):
        if name in core:
            sections[name] = core.pop(name)
    for name, value in card.items():
        if name == "core":
            continue
        if name in {"classification", "automation"} and isinstance(value, dict):
            sections.update({f"{name}.{section}": content for section, content in value.items()})
        else:
            sections[name] = value
    state = card.get("work_state") or {}
    verification = state.get("verification") or {}
    execution = state.get("execution_state") or {}
    if not isinstance(execution, dict):
        execution = {}
    binding = [actor_uid, project_uid, card_uid, profile]
    current = {
        "version": 1,
        "binding": binding,
        "card_change_seq": int(core.get("last_change_seq") or 0),
        "hashes": {name: _hash(value) for name, value in sections.items()},
        "refs": {name: _refs(value, name) for name, value in sections.items()},
        "blockers": _hash(state.get("dependency_state")),
        "verification": _hash(verification),
        "verification_state": state.get("verification_state"),
        "evidence_refs": _refs(verification.get("evidence", []), "evidence") or _refs(verification, "verification"),
    }
    old = _decode(cursor, key, binding)
    partial = _partial(card)
    reasons = []
    if old is None:
        reasons.append("initial_context" if not cursor else "invalid_or_mismatched_cursor")
    if old and current["card_change_seq"] < old.get("card_change_seq", 0):
        old = None
        reasons.append("change_sequence_regressed")
    if partial:
        reasons.append("incomplete_projection_follow_bundle_continuations")
    changed = [name for name, digest in current["hashes"].items() if old is None or old["hashes"].get(name) != digest]
    removed = []
    if old is not None and not partial:
        for name, refs in old["refs"].items():
            removed.extend(sorted(set(refs) - set(current["refs"].get(name, []))))
        for name in old["hashes"].keys() - current["hashes"].keys():
            changed.append(name)
            sections[name] = None
    permissions_changed = any(ref.startswith("linked_wikis:") for ref in removed)
    if permissions_changed:
        reasons.append("linked_wiki_removed_or_permission_revoked")
    evidence_changed = old is not None and (
        current["verification"] != old["verification"]
        or current["verification_state"] != old["verification_state"]
        or "linked_wikis" in changed
        or "work_state" in changed
    )
    encoded = _encode(current, key) if not partial else None
    if encoded and len(encoded) > 65536:
        encoded = None
        reasons.append("context_cursor_capacity_exceeded")
    requires_full = old is None or partial or permissions_changed or encoded is None
    if requires_full:
        changed = list(sections)
    return CardContextDelta(
        card_uid=card_uid,
        current_context_cursor=encoded,
        card_change_seq=current["card_change_seq"],
        description_revision=(sections.get("description") or {}).get("revision"),
        execution_generation=execution.get("generation"),
        source_revision=execution.get("source_revision"),
        changed_sections=sorted(changed),
        sections={name: sections[name] for name in sorted(changed)},
        removed_refs=sorted(set(removed)),
        invalidated_evidence=old["evidence_refs"] if evidence_changed else [],
        work_state_changed=old is None or "work_state" in changed,
        blocker_changed=old is None or current["blockers"] != old["blockers"],
        permissions_changed=permissions_changed,
        requires_full_refresh=requires_full,
        reasons=reasons,
    )
