# External member card creation regression

## Reproduction

A scoped external test account was created in the affected board, with only `read` and `card_update` permissions and no administrator role. The native current audience resolver confirmed `project_member=True` and `internal_member=False`.

The deployed HTTP endpoints reproduced the report using a normal email/password sign-in and the returned access and refresh tokens:

- Email resolution: 200.
- Sign-in: 200.
- Board columns: 200.
- Card creation: 201, visibility INTERNAL.
- Created card detail: 404.
- Board cards: 200, created card absent.

The three reported customer cards also remain stored as INTERNAL, and their current external author cannot read them. No customer card was deleted or reclassified during diagnosis.

## Fix

Resolve the current account and board membership before choosing visibility. On a collaborative board, an external member under the configured SCIM or OIDC classification policy creates SHARED cards. Internal users and bots keep INTERNAL defaults; an active owner of a personal board keeps PRIVATE. Unknown policies and nonmembers do not receive a shared default. Existing card read rules are unchanged.

## Verification and outstanding gates

Creation and private-policy regression tests pass locally (15 tests). Ruff passes. A wider visibility run yielded 399 passed, 22 skipped, and 7 failures caused by older metadata fixtures missing `save_card`/`delete_card`; that wider run is not recorded as successful.

This source fix has not yet been deployed. Creation→detail→body save→board re-entry after deployment remains required. The affected preexisting customer drafts need a narrowly scoped recovery, preserving their authors, content, and history. Actual external browser validation remains outstanding.

Test credentials are kept only in a protected runtime file and are excluded from Git, comments, and PRs.
