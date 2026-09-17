# Work events

Langboard can publish compact action-required `work_event` envelopes through its existing signed webhook transport. The event is a reference-only integration boundary: external consumers re-read content under the recipient's own authorization instead of receiving copied card or wiki bodies.

## Enable an endpoint

Add `work_event` to a webhook's explicit event allowlist. A legacy webhook with no allowlist does not receive work events, so upgrading does not add employee-directed traffic to existing integrations.

## Delivery contract

Each event contains:

- a deterministic `event_id`, reused by every retry;
- the occurrence time and action-required notification type;
- opaque Langboard actor and recipient principals;
- project/card/wiki/checklist scope identifiers when present;
- the durable source notification identifier;
- a SHA-256 hash of the complete internal notification payload;
- a correlation identifier that is stable for the event.

The payload deliberately excludes email addresses, names, message excerpts, card bodies, and wiki bodies. The consumer should authenticate as the recipient (or use an equivalent delegated authorization) before retrieving details.

## Idempotency and ownership

Langboard persists the source notification before an event can be scheduled. A bounded backlog retries undispatched sources with the same `event_id` and marks a source only after endpoint deliveries have been scheduled. The consumer owns durable downstream delivery and must deduplicate by `event_id`.

Web subscription preferences affect only in-app visibility. An unsubscribed source remains durable for the integration event but is excluded from notification lists, unread counts, and realtime Web delivery. Email and other notification channels retain their own subscription policies.

Low-value reaction events are excluded. Assignment, mention, checklist notification, project invitation, and scheduled-rule/deadline notifications are eligible by default.
