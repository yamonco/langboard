# Seen, recognition and AI requests

Tracking: [child planning card](https://langboard.yamon.io/board/2RRwwB5JNm0/lRTKOVhslUt), [Seen card](https://langboard.yamon.io/board/2RRwwB5JNm0/f3vL7IkKbKE).

## Interaction contract

| Interaction | Meaning | Authoritative record |
| --- | --- | --- |
| Seen | A person opened the card detail. This is a card-view receipt, not proof that every comment was read. | Existing `UserCardReadState`; a comment count includes receipts at or after its update time. |
| Mark unread | The viewer wants to revisit this card. | Existing negative read cursor; retained during the current visit and advanced when the detail is reopened. |
| Recognition | A person expresses recognition using an existing emoji reaction. | Existing `CardCommentReaction`; no separate acknowledged state or button. |
| Approval | An authorized person decides a specific request for a specific target version. | An explicit approval request and its decision receipt; never inferred from Seen or an ordinary reaction. |

The Seen count and its small unread icon remain subdued. Recognition adds no new status, counter or control. A reaction can be removed without undoing an approval decision.

## AI badge and automatic guidance

Display one compact `AI` badge beside the author when server-owned provenance establishes AI authorship. The hover/focus description explains the author and origin; mobile tapping provides the same information. Display names, a model name in comment text, client-supplied flags and a generic bot identity are insufficient provenance. Delegated user credentials alone cannot distinguish a person from an AI caller.

For an AI artifact or permission request, generate a short guidance line from the request's authorized policy. It identifies the exact designated reaction and its meaning. Do not hardcode a particular emoji or treat every AI comment as an approval request. Missing policy means no invented reaction instruction. Missing provenance means no AI badge. Human comments and general automation remain unchanged.

A suggested recognition reaction only records recognition. An instruction to approve must refer to an actual authorized, pending approval request. An expired, resolved, inaccessible or outdated request must not invite a new approval. A stale decision fails rather than applying to a newer target.

## Existing boundaries and remaining integration

- `CardCommentService.create` records the authenticated user or bot. Its response currently exposes these authors, not AI provenance or a request-specific reaction policy.
- `DefaultRequest.DEFAULT_API_APPROVAL_POLICY` defines `allow`/`ask` for read/create/edit/delete. It does not select a reaction.
- `GraphApprovalRequest` already has request identity, origin, action, permission, status and resolution fields. Reuse the existing request/decision service where applicable; an ordinary comment reaction must not resume a graph by implication.
- Orchestration uses `task.source=ai_generated`. This alone is not an immutable authorship assertion: it must be traced to a server-owned producer before serving as badge evidence.

Before implementing the badge/guidance projection, connect a trusted producer to the existing comment/request record and resolve its policy under current board authorization. The read and socket projections must return the same safe provenance and guidance. This document specifies the boundary; it does not claim those projections or a future submission approval interface are implemented.

## Acceptance evidence

1. A real trusted AI producer creates a comment/request. Its badge survives reload and appears through the existing socket update.
2. A human or general bot cannot acquire an AI badge by naming itself AI, adding text or supplying an unsupported flag.
3. Two request policies with different designated reactions generate the correct guidance independently; missing policy generates no invented instruction.
4. Seen, unread and recognition remain independent. Only an authorized explicit decision resolves an approval request, bound to its target version.
5. Desktop keyboard/hover and 390px mobile tapping expose the same explanation without clipping or extra prominent controls.
6. An inaccessible request exposes neither private request content nor a usable approval action. Expiry, prior resolution and target edits invalidate stale approval guidance.

Record actual producer, authorization, deployed revision and UI results in the child card before completing the badge, guidance or end-to-end checklist items. Source checks and a healthy deployment do not satisfy these acceptance cases.
