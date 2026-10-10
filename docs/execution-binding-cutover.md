# Execution Binding integration

An Execution Binding connects a Langboard project to an external executor.
Bindings are disabled by default. Enabling one may make existing cards in the
configured ready column executable; review the project and destination before
enabling it. The signed webhook must explicitly allow
`io.langboard.work.ready.v1`.

## Ready event

A `io.langboard.work.ready.v1` event signals that one card generation became
executable. It is not an immutable task snapshot. The delivered title, labels,
assignees and `source_revision` come from one delivery-time card read.

The event uses a relative `card_url` path. Resolve it against the project origin
configured for the integration. Retrieve authoritative content with the
consumer's own credentials and current project authorization.

Before execution, compare the card point-read with the event:

- `execution.is_ready` must be `true`.
- `execution.generation` must equal `data.execution_generation`.

Reject a revoked or superseded generation. Moving a card out of readiness and
back creates a new generation. A content edit that preserves readiness does not
increase the generation, so the consumer uses current authorized content rather
than executing a second task for the same generation.

`data.source_revision` is the delivery-time card update timestamp, provided for
provenance. It is not an execution fence. `description.revision` is a separate
content revision and must not be compared as though it were the same value.

## Authentication and duplicate delivery

Verify the signed `X-Langboard-Webhook-*` headers before accepting an event.
Delivery is at-least-once: `event_id` remains stable across retries. Maintain
durable duplicate detection and fence by execution generation so a retried
delivery cannot create a duplicate execution. A suitable execution key includes
project, card and generation, such as `langboard:{project}:{card}:{generation}`.

Disabling a binding stops new execution events and invalidates delivery for the
disabled binding. Avoid having a second polling integration execute the same
cards independently of this event and generation contract.
