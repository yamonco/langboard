# Seen, recognition and AI requests

## Interaction contract

| Interaction | Meaning | Authoritative record |
| --- | --- | --- |
| Seen | A person opened the card detail. This is a card-view receipt, not proof that every comment was read. | A card-view receipt; a comment count includes receipts at or after its update time. |
| Mark unread | The viewer wants to revisit this card. | An unread marker retained during the current visit and advanced when the detail is reopened. |
| Recognition | A person expresses recognition using an existing emoji reaction. | An emoji reaction; no separate acknowledged state or button. |
| Approval | An authorized person decides a specific request for a specific target version. | An explicit approval request and its decision receipt; never inferred from Seen or an ordinary reaction. |

The Seen count and its small unread icon remain subdued. Recognition adds no new status, counter or control. A reaction can be removed without undoing an approval decision.

## AI badge and automatic guidance

The proposed compact `AI` badge identifies authorship established by server-owned provenance. Its hover/focus description explains the author and origin; mobile tapping provides the same information. Display names, a model name in comment text, client-supplied flags and a generic bot identity are insufficient provenance. Delegated user credentials alone cannot distinguish a person from an AI caller.

For an AI artifact or permission request, the proposed guidance line identifies the designated reaction and its meaning under that request's authorized policy. An AI comment alone is not an approval request. Without a designated policy, no approval reaction is suggested. Without trusted provenance, no AI badge is shown. Human comments and general automation remain unchanged.

A suggested recognition reaction only records recognition. An instruction to approve must refer to an actual authorized, pending approval request. An expired, resolved, inaccessible or outdated request must not invite a new approval. A stale decision fails rather than applying to a newer target.

## Availability

Seen, unread and recognition describe separate interactions. AI provenance badges
and request-specific approval guidance are proposed behavior; this document does
not claim that their projections or a submission approval interface are available.
An ordinary comment reaction does not implicitly resume an execution or grant
permission. Approval requires an explicit authorized request and decision.
