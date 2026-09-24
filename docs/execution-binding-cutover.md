# Execution Binding cutover

The Langboard board remains the work-state authority. A board binding is disabled
by default. Enabling it may queue existing cards in its ready column, so inspect
the board and FractalOps project mapping before enabling it.

## Sequence

1. Deploy the native CloudEvents producer contract and the FractalOps consumer
   that verifies `X-Langboard-Webhook-*` headers. Keep the FractalOps consumer
   disabled until its signing secret and board mapping are configured.
2. Apply migrations through `c7e2b4a091dd` with the API and workers stopped,
   then start the API and existing Celery workers. Confirm the API is healthy
   and the recovery cron is registered. There is no dedicated outbox daemon.
3. Configure a signed webhook whose explicit allowlist includes
   `io.langboard.work.ready.v1`. Configure the board's ready and terminal
   columns and prerequisite relationship type, then enable its binding.
4. Move a controlled card from non-ready to ready. Verify one committed
   `execution_outbox` row with a frozen payload and destination, prompt
   after-commit Celery enqueue, one native webhook delivery, and one FractalOps
   Studio Run with key `langboard:{project}:{card}:{generation}`. Retry the
   delivery and verify the same run is acknowledged as duplicate. Move the
   card out and back to ready to verify a new generation.
   The frozen event uses a relative `card_url` path so retries preserve the
   same bytes across UI host changes; consumers resolve it against their bound
   board origin. Before execution, the consumer must fence on the card
   point-read's `execution.{is_ready,generation}` matching the event's
   `data.execution_generation` with `is_ready` true.
   Repeat with a ready-to-blocked transition: the pending generation is
   superseded and cannot run; returning to ready creates a new generation.
5. Only after the live path passes should the FractalOps poller be removed.
   Check for zero idle polling and no duplicate runs before declaring cutover.

## Event payload and point-read truth ownership

A `io.langboard.work.ready.v1` event is a signal that one card generation
became executable, not an immutable task snapshot:

- The outbox row keeps the commit-time payload as provenance evidence. It is
  never replayed as-is into the delivered event.
- The delivered `data` (title, labels, assignees, `source_revision`) is
  projected from one delivery-time point-read of the card, so the payload is
  internally consistent and never mixes commit-time and delivery-time views.
- The hard fence is `point-read is_ready == true AND point-read
  execution_generation == event data.execution_generation`. A READY-preserving
  content edit (title, body, labels, assignees) does not supersede the event
  and does not bump the generation, so the execution still runs exactly once
  with the latest content.
- `data.source_revision` is provenance only: it is the `Card.updated_at` of
  the delivery-time point-read and must not be used as a hard fence.
  `description.revision` is a separate content projection hash.
- Consumers that need authoritative content should use their own point-read
  under their authorization; the event payload is a routing and fence signal.

## Delivery lifecycle and broker hops

Execution delivery runs in one Celery task, `execution_outbox_task(event_id)`:
claim, readiness and binding fence, signed HTTP delivery, terminal mark, with
Celery retries around HTTP failures. Outbox states:

- `pending`: committed, waiting for a claim.
- `delivering`: claimed with a lease and attempt count; a crashed worker's
  lease expires and the cron re-drains the row.
- `delivered`: terminal success, marked in the same task as the HTTP POST.
- `failed`: attempt budget exhausted; operator `reconcile` re-queues it with
  a fresh budget. No state is left permanently in flight.
- `superseded` / `blocked`: readiness revoked or destination invalid.

Broker hops per normal delivery: previously 2 Celery dispatches
(`execution_outbox_task` → `webhook_delivery_task`) plus 1 HTTP POST; now
1 Celery dispatch plus 1 HTTP POST. The recovery cron previously drained into
a second dispatch; it now delivers directly (0 extra dispatches). Logical
delivery is at-least-once: the event id is the outbox row id and is stable
across retries and lease recoveries, so consumers deduplicate by event id and
fence by execution generation.

## Diagnostics and recovery

- `uv run --no-sync python -m langboard_shared.tasks.webhooks.ExecutionOutboxWorker diagnose <project_uid>`
  reports outbox counts by state and error code without payloads or secrets.
- `uv run --no-sync python -m langboard_shared.tasks.webhooks.ExecutionOutboxWorker drain`
  runs the committed queue once. Cron runs this as recovery for failed enqueue
  and for expired delivery leases.
- `uv run --no-sync python -m langboard_shared.tasks.webhooks.ExecutionOutboxWorker reconcile <project_uid>`
  retries recoverable blocked rows and re-queues failed ones with a fresh
  attempt budget; it does not create new readiness events.
  Existing generations remain stable; consumers deduplicate replayed deliveries.

## Rollback

Disable the board binding first. This stops new execution events and rechecks
at delivery. Keep the outbox and recovery cron available for inspection. Restore the
FractalOps poller only if its previous deployment and idempotency state are
confirmed; do not run poller and producer against the same board at once.
The UoW migration has no schema downgrade because reverting to trigger
ownership after application events would risk duplicate generations. Roll
forward with a corrective migration while preserving outbox history.
