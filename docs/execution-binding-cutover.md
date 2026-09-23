# Execution Binding cutover

The Langboard board remains the work-state authority. A board binding is disabled
by default. Enabling it may queue existing cards in its ready column, so inspect
the board and FractalOps project mapping before enabling it.

## Sequence

1. Deploy the native CloudEvents producer contract and the FractalOps consumer
   that verifies `X-Langboard-Webhook-*` headers. Keep the FractalOps consumer
   disabled until its signing secret and board mapping are configured.
2. Apply migration `71df4c6a9b20` and start `executionoutbox`. Confirm the
   outbox is empty and the process is listening before enabling a binding.
3. Configure a signed webhook whose explicit allowlist includes
   `io.langboard.work.ready.v1`. Configure the board's ready and terminal
   columns and prerequisite relationship type, then enable its binding.
4. Move a controlled card from non-ready to ready. Verify one committed
   `execution_outbox` row with a frozen payload snapshot, one native webhook delivery, and one FractalOps
   Studio Run with key `langboard:{project}:{card}:{generation}`. Retry the
   delivery and verify the same run is acknowledged as duplicate. Move the
   card out and back to ready to verify a new generation.
   `data.source_revision` is the ready transition's `Card.updated_at` and
   must match the point-read `core.updated_at`; `description.revision` is a
   separate content projection hash. The frozen event uses a relative
   `card_url` path so retries preserve the same bytes across UI host changes;
   consumers resolve it against their bound board origin.
5. Only after the live path passes should the FractalOps poller be removed.
   Check for zero idle polling and no duplicate runs before declaring cutover.

## Diagnostics and recovery

- `uv run --no-sync python -m langboard_shared.tasks.webhooks.ExecutionOutboxWorker diagnose <project_uid>`
  reports outbox counts by state and error code without payloads or secrets.
- `uv run --no-sync python -m langboard_shared.tasks.webhooks.ExecutionOutboxWorker drain`
  runs the committed queue once.
- `uv run --no-sync python -m langboard_shared.tasks.webhooks.ExecutionOutboxWorker reconcile <project_uid>`
  re-evaluates one board and retries its blocked rows. Existing generations
  remain stable; FractalOps deduplicates replayed deliveries.

## Rollback

Disable the board binding first. This stops new execution events and rechecks
at delivery. Keep the outbox and worker available for inspection. Restore the
FractalOps poller only if its previous deployment and idempotency state are
confirmed; do not run poller and producer against the same board at once.
Schema downgrade deletes generation and outbox history, so use it only after
exporting and reconciling those rows.
