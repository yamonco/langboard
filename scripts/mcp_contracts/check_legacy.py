"""Reject legacy MCP surface drift before a canary transition or rollback."""

import argparse
import hashlib
import json
from pathlib import Path


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def check_legacy(expected, current, *, check_groups=True):
    """Allow additive tools; preserve every legacy schema, annotation, owner and group grant."""
    problems = []
    for label, snapshot in (("baseline", expected), ("candidate", current)):
        contract = snapshot["contract"]
        digest = hashlib.sha256(canonical_bytes(contract)).hexdigest()
        if digest != snapshot["contract_sha256"]:
            problems.append(f"{label}: contract digest does not match")
        names = [tool["name"] for tool in contract["tools"]]
        if len(set(names)) != len(names):
            problems.append(f"{label}: duplicate tool names")
        if contract["registered_runtime_mismatches"]:
            problems.append(f"{label}: registry/runtime tool mismatch")
        keys = [group["key"] for group in contract["tool_groups"]]
        if len(set(keys)) != len(keys):
            problems.append(f"{label}: duplicate tool group keys")
    old = {tool["name"]: tool for tool in expected["contract"]["tools"]}
    new = {tool["name"]: tool for tool in current["contract"]["tools"]}
    for name, tool in old.items():
        if name not in new:
            problems.append(f"removed legacy tool: {name}")
            continue
        for field in ("input_schema", "output_schema", "annotations"):
            if new[name][field] != tool[field]:
                problems.append(f"changed legacy {field}: {name}")
    # Stable hashed identities preserve ownership comparison without storing user IDs.
    # New profiles may add groups; existing groups cannot silently gain or lose grants.
    groups = {group["key"]: group for group in current["contract"]["tool_groups"]}
    for group in expected["contract"]["tool_groups"] if check_groups else []:
        if groups.get(group["key"]) != group:
            problems.append(f"changed legacy tool group: {group['key']}")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--catalog-only", action="store_true", help="Skip deployed ToolGroup comparison for isolated CI."
    )
    args = parser.parse_args()
    problems = check_legacy(
        json.loads(args.baseline.read_text()),
        json.loads(args.candidate.read_text()),
        check_groups=not args.catalog_only,
    )
    for problem in problems:
        print(problem)
    if problems:
        raise SystemExit(1)
    print(
        "Legacy catalog preserved." if args.catalog_only else "Legacy catalog and captured tool-group grants preserved."
    )


if __name__ == "__main__":
    main()
