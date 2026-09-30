"""Detect Korean prose in GitHub collaboration event data, without executing it."""

import json
import os
import re
from pathlib import Path


HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff]")


def prose_lines(text: str):
    """Exempt explicit examples, code, and quoted external/user content."""
    fence = None
    localized_example = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip() == "<!-- langboard:localized-example:start -->":
            localized_example = True
            continue
        if line.strip() == "<!-- langboard:localized-example:end -->":
            localized_example = False
            continue
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence or localized_example or line.lstrip().startswith(">"):
            continue
        yield number, re.sub(r"(`+).*?\1", "", line)


def event_fields(event_name: str, event: dict):
    if event_name == "pull_request_target":
        pr = event["pull_request"]
        return [("PR title", pr["title"], False), ("PR body", pr.get("body") or "", True)]
    if event_name == "issue_comment" and "pull_request" in event.get("issue", {}):
        return [("PR comment", event["comment"].get("body") or "", True)]
    if event_name == "pull_request_review":
        return [("PR review", event["review"].get("body") or "", True)]
    if event_name == "pull_request_review_comment":
        return [("PR review comment", event["comment"].get("body") or "", True)]
    return []


def violations(event_name: str, event: dict):
    result = []
    for field, text, markdown in event_fields(event_name, event):
        lines = prose_lines(text) if markdown else enumerate(text.splitlines(), 1)
        result.extend((field, number) for number, line in lines if HANGUL.search(line))
    return result


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    found = violations(os.environ["GITHUB_EVENT_NAME"], event)
    for field, line in found:
        # Never echo user content into workflow commands.
        print(f"::error::{field} line {line}: use English prose; quote localized examples as documented in CONTRIBUTING.md.")
    if found:
        raise SystemExit(1)
    print("GitHub collaboration language check passed.")


if __name__ == "__main__":
    main()
