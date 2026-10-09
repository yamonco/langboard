"""External service declarations. Registration never grants execution authority."""

import json
import re
from urllib.parse import urlsplit
from .workflow import WorkflowRequirements


APP_CAPABILITIES = frozenset({"cards.create", "cards.presentation", "resources.read", "events.receive"})


def validate_app_definition(item: dict) -> dict:
    allowed = {"schema_version", "key", "version", "name", "description", "capabilities", "resource_types", "workflow_requirements", "panel"}
    if not isinstance(item, dict) or set(item) - allowed or len(json.dumps(item)) > 16384:
        raise ValueError("Invalid app declaration")
    if type(item.get("schema_version")) is not int or item["schema_version"] != 1:
        raise ValueError("Unsupported app declaration schema")
    if not isinstance(item.get("key"), str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", item["key"]):
        raise ValueError("Invalid app key")
    if not isinstance(item.get("version"), str) or not re.fullmatch(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})", item["version"]):
        raise ValueError("App version must be major.minor.patch")
    for field, maximum in (("name", 80), ("description", 1000)):
        if not isinstance(item.get(field), str) or not item[field].strip() or len(item[field]) > maximum:
            raise ValueError("App needs bounded English fallback text")
    for field in ("capabilities", "resource_types"):
        values = item.get(field)
        if not isinstance(values, list) or len(values) > 16 or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
            raise ValueError("Invalid app capability/resource declaration")
    if set(item["capabilities"]) - APP_CAPABILITIES:
        raise ValueError("Unsupported app capability")
    if any(not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", v) for v in item["resource_types"]):
        raise ValueError("Invalid app resource type")
    workflow = item.get("workflow_requirements")
    if workflow is not None:
        if not isinstance(workflow, dict) or set(workflow) != {"required", "optional"}:
            raise ValueError("Invalid workflow requirements")
        if any(not isinstance(workflow[k], list) for k in ("required", "optional")):
            raise ValueError("Invalid workflow requirements")
        WorkflowRequirements(tuple(workflow["required"]), tuple(workflow["optional"]))
    panel = item.get("panel")
    if panel is not None:
        if not isinstance(panel, dict) or set(panel) != {"url", "name", "icon"}:
            raise ValueError("Invalid app panel declaration")
        for field, maximum in (("url", 2048), ("name", 80), ("icon", 32)):
            if not isinstance(panel[field], str) or not panel[field].strip() or len(panel[field]) > maximum:
                raise ValueError("Invalid app panel text")
        url = urlsplit(panel["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("App panel requires an HTTPS URL without credentials or fragment")
        # Parsing a port also rejects malformed authorities; no network request here.
        _ = url.port
    return json.loads(json.dumps(item))
