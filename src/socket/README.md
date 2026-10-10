# Langboard Phoenix Socket

This is the Phoenix Socket runtime at `src/socket`. The default Compose service
uses Phoenix. Production cutover approval is separate from local development.

## Runtime

- Phoenix/Bandit endpoint with the existing raw JSON WebSocket envelope
- `/health`, `/health/live`, and dependency-aware `/health/ready`
- Access-token validation through the Python `/auth/socket` boundary
- Existing automatic `global:all` and `user_private:<uid>` subscriptions
- Authorized board subscriptions, clustered PubSub, and bounded Kafka fanout ingress
- Board bot status reads with a separate Graph HTTP pool and bounded command workers
- Payload, HTTP pool, timeout, worker, trace queue, and trace attribute limits
- OpenTelemetry spans for HTTP routes and internal Finch requests

## Responsibility ownership

Runtime modules and tests use matching paths:

- `LangboardSocket.BoardChat` (`board_chat/`): accepted runs, streaming, resume and recovery.
- `LangboardSocket.Editor` (`editor/`): AI runs, collaborative documents, sync storage and manifests.
- `LangboardSocket.Api` (`api/`): Python API authorization, bot status, notification, and Ollama command clients.
- `LangboardSocket.Graph` (`graph/`): Graph/Langflow streaming and approval-resume clients.
- `LangboardSocket.Broker` (`broker/`): Kafka ingress, acknowledgements, dead letters, lag, and transitional Redis payload storage.
- `LangboardSocketWeb`: HTTP/WebSocket adapters, controllers and command dispatch.

Editor document registration and lifecycle lock keys retain their original identity
across the namespace change. This reorganization does not authorize a rolling
deployment or change document ownership, persistence paths or wire events.
The module rename requires a complete Socket runtime restart, not a
rolling code upgrade from the previous module names.

The table identifies the Phoenix execution paths.
Python `routes/` paths below are relative to `src/api/langboard`; domain service,
repository, and task names resolve under `src/shared/py/langboard_shared`.
Other paths are relative to the repository root. Phoenix module names resolve under
`src/socket/lib/langboard_socket`, except web modules under
`src/socket/lib/langboard_socket_web`.

| Responsibility | Execution owner | Durable/domain owner |
| --- | --- | --- |
| JSON connection, subscriptions, command dispatch | `SocketHandler`, `SubscriptionTopic`, `Phoenix.PubSub` | Python `routes/auth/SocketAuthApi.py` and `SocketAuthorization.py` authorize current access |
| `SocketConsumer` broker projection and fanout | `Broker.Kafka.Ingress`, `Broker.Envelope`, `Broker.EventProjector` | Python publishers emit inline v2 envelopes; `Broker.LegacyPayloadStore` is transitional only |
| `NotificationConsumer` creation, unsubscribe checks, email | Python `NotificationService` and notification recovery tasks | Python notification repositories and email outbox; Phoenix does not send email |
| Notification read/delete commands | `NotificationClient` forwards authenticated commands | Python `routes/notification/NotificationApi.py` |
| Board bot status and chat availability | `BotStatusClient`, `ChatAvailabilityClient` | Graph status endpoint and Python socket authorization API |
| Board chat send, cancel, streaming, reconnect recovery | `BoardChat.RunWorker`, `BoardChat.AcceptedRecovery` | Python `InternalBotRunService` and socket run endpoints persist accepted work and history |
| Board chat approval resume | `BoardChat.ResumeWorker`, `Graph.ResumeClient` | Python `GraphApprovalRequestService` and run/approval claim endpoints |
| Editor chat/copilot, abort, status, approval resume | `Editor.RunWorker`, `Editor.AcceptedRecovery`, `Editor.ResumeWorker` | Python editor run/approval endpoints, using the same durable run service |
| Graph/Langflow response streaming | `Graph.StreamClient`, `Graph.LangflowClient` and run workers | Python authorizes and records run transitions; external services perform their own operations |
| Board chat attachment upload | Python `routes/board/BoardChatApi.py` | `BoardChatAttachment`, `LangflowFileClient`, storage and cleanup task; UI uses the API route |
| Ollama copy/delete/pull commands and progress | `OllamaClient` forwards commands; Kafka/PubSub distributes progress | Python socket/Ollama endpoints, `OllamaModelPullService` and recovery task |
| Hocuspocus/Yjs binary sync and awareness | `EditorSyncHandler`, `Editor.Document`, `Editor.SyncFrame` | `Editor.SyncStorage` preserves binary `.ydoc` files; one document owner |
| Editor active/clear/text/patch HTTP operations | `EditorSyncController`, `Editor.HttpLimiter` | Python editor authorization; binary storage and existing rich-patch publication |
| HTTP health, drain, resource lifecycle | `HealthController`, `RuntimeStatus`, OTP supervision | Compose health/readiness and deployment drain sequence |

Phoenix owns JSON and editor traffic together; Python email outbox and recovery
scheduling remain enabled.

The project-chat API rejects N8N before accepting work. Background Bot tasks
remain separate: Python's Bot task request
factory owns their supported N8N execution path.

Before production deployment, complete the browser/recovery matrix and
production document manifest and restore proof. Run the sustained 24-hour OTel
observation after the initial release.
Ordinary SMTP has ambiguous failure
windows; the outbox records uncertain delivery rather than promising exactly-once mail.
The notification owner preflight uses the configured SMTP TLS and login settings
from the API runtime without sending a message. It does not prove message
acceptance or delivery. Review failed and uncertain outbox rows with
`langboard notification:email:review --action list` before handoff.
For an older failed `reacted_to_comment` row missing `card_name`, retry requires
`--use-current-card-title` and an operator ticket. This renders the Card's current title,
which may differ from its title when the notification was accepted. Do not retry these
rows in bulk or assume a reachable SMTP port proves delivery.

## Commands

Use `make test_socket_phoenix_browser_cluster` to exercise authenticated chat,
reconnect, and recovery against two temporary Phoenix nodes without changing the
running ingress.

```shell
mix deps.get
mix phx.server
mix format --check-formatted
mix compile --warnings-as-errors
mix test
```

From the repository root, use `make test_socket_phoenix` or `make build_socket_phoenix_image`.
Use `make test_socket_phoenix_local` for a short check of the running local ingress and raw WebSocket suite. It does not build images or run production cutover checks. The suite
covers bootstrap subscriptions, malformed and missing fields, unknown events and topics,
authorization denial, binary JSON, ordered rapid subscribe/unsubscribe frames, subscription
limits, authentication close codes, and oversized payloads.

Before selecting Phoenix as the complete Socket owner, run the fail-closed preflight.
It checks SMTP, notification recovery, and Kafka, then validates the production-derived
editor restore manifest. The representative 24-hour OTel soak follows release:

First, quiesce editor writes and take a database snapshot with the editor-sync volume backup
at the same point in time. Run the inventory in an API environment connected to the restored
database, with `/secure` mounted at the same paths used below. Then audit an independent
restored copy of the document files from the repository root:

In the API environment connected to the restored database:

```shell
uv run python -m langboard.commands.EditorSyncNameInventoryCommand \
  /secure/editor-source /secure/evidence/editor-names.json
```

From the repository root, with the source, restore, and inventory paths accessible:

```shell
cd src/socket
elixir -S mix run scripts/editor_sync_manifest.exs -- \
  /secure/editor-source /secure/editor-restore \
  /secure/evidence/editor-names.json /secure/evidence/editor-sync-manifest.json
cd ../..
```

The inventory reports unmatched 64-character hash-named `.ydoc` files as
`opaque_source_files`; preserve them in both copies. Other unmapped files make the
inventory fail. The manifest must also parse and checksum every named and opaque
document, and reject extra files. Do not delete an unexpected file merely to make
the audit pass. Complete the short browser, recovery, and restore gates before
selecting the Phoenix owner. Run the 24-hour OTel soak after the initial release;
do not delay the release solely to wait for that long-running test.

Verify the restored Editor files before release:

```shell
make check_socket_phoenix_editor_restore \
  PHOENIX_CUTOVER_EDITOR_MANIFEST=/secure/evidence/editor-sync-manifest.json \
  PHOENIX_CUTOVER_EDITOR_SOURCE_DIR=/secure/editor-source \
  PHOENIX_CUTOVER_EDITOR_RESTORE_DIR=/secure/editor-restore
```

This check does not by itself authorize production cutover. The Kafka, notification,
worker, SMTP, and Editor restore preflights remain required.
Failed or uncertain email deliveries are not claimed by the automatic `Pending`
delivery workers. The preflight reports these quarantined records for operator
review without retrying or closing them; a working SMTP connection is still
required. Do not point `MAIL_SERVER` at `127.0.0.1` inside a container unless
the SMTP server runs in that same container. Use a reachable, approved mail
service and review uncertain outcomes before any manual retry.

After release, run the representative 24-hour OTel soak and validate its evidence:

```shell
make validate_socket_phoenix_cutover_evidence \
  PHOENIX_CUTOVER_EDITOR_MANIFEST=/secure/evidence/editor-sync-manifest.json \
  PHOENIX_CUTOVER_OTEL_SOAK_REPORT=/secure/evidence/phoenix-otel-soak.json \
  PHOENIX_CUTOVER_EDITOR_SOURCE_DIR=/secure/editor-source \
  PHOENIX_CUTOVER_EDITOR_RESTORE_DIR=/secure/editor-restore
```

The editor evidence must be a verified format-version 2 `Editor.SyncManifest` result with
no unmapped files and byte-identical checksums. The OTel evidence must identify itself as
format-version 5 `phoenix_otel_soak`, cover at least 24 hours after warm-up under representative load,
contain at least 90 percent of the expected metric samples, prove bounded memory, mailboxes,
buffers, Editor authorization behavior, and task registries, and contain no rollback trigger.
A short delivery probe does not pass.
The preflight rereads every source and restored `.ydoc` file and rejects changed checksums,
missing or extra files, and linked copies. Provide both host paths when the manifest was
generated inside a container; omit both only when its recorded paths are accessible locally.
`start_docker`, `rebuild_docker`, and `update_docker` run the short production
preflights before pulling the optional OTel image or building application images;
missing Editor restore evidence prevents deployment. They do not wait for a 24-hour
soak or require an OTel trace sink. The post-release soak report's exact image digest must match
the deployed image when this evidence validator runs.
Production owner preparation also rejects `SOCKET_PHOENIX_INTERNAL_SECRET` values shorter
than 32 characters and verifies Kafka group readiness.
The API and Phoenix services must receive the same internal secret. Phoenix readiness calls
the internal API capability endpoint from the shared realtime contract and opens only when
the API reports the exact supported contract version. A missing route, invalid secret,
malformed response, or mismatched version keeps `/health/ready` closed, so an incompatible
API and Phoenix pair cannot accept new socket traffic during a rolling deployment.
Owner preparation requires an existing Phoenix Kafka group with retained offsets for every
source partition. It does not initialize a new group at the current end of the topic.
Phoenix readiness stays closed until its
group reaches zero lag, and closes again if Kafka offset inspection becomes unavailable
or the committed offset leaves the retained source range.

The Phoenix CI workflow also runs the TypeScript realtime contract, Yjs/Yex
interoperability, and distributed editor recovery probes under `MIX_ENV=test`.
These supplement Elixir formatting, compilation, tests, Credo, and Dialyzer; they
do not replace deployed browser, storage, or soak gates.

After Compose starts or replaces services, the Makefile checks the host-published
Socket `/health/ready` route for HTTP 204 and Phoenix runtime/version headers.
A failed check makes the deployment command fail, but
does not roll back containers already started. Inspect both the Nginx container's
internal route and the host-published port before retrying a failed deployment.

For Docker cluster recovery checks, use `make test_socket_phoenix_cluster`. The harness
creates an isolated three-partition Kafka source topic, starts two Phoenix nodes, and
checks delivery from every partition before and after reconnect. Before ingress checks
and after cluster restoration, it requires a stable Kafka group with two consumers,
each owning source partitions, and exactly one owner per partition. It removes the test
containers and topics on exit without changing the application's source topic.

Use `PHOENIX_CLUSTER_FAILURE_MODE=kill make test_socket_phoenix_cluster` in a POSIX
shell to exercise abrupt node termination instead of the default graceful stop.
In PowerShell, set `$env:PHOENIX_CLUSTER_FAILURE_MODE='kill'` before running the target
and remove that environment override afterward. Set the mode to `partition` to
follow the initial reconnect check with a Docker network disconnect/reconnect of
one live node. Both sides must withdraw readiness but retain liveness, and the
isolated node must recover on the same address without restarting. Kafka ownership
and delivery are checked after recovery. This is whole-node network isolation, not
a selective or one-way partition. These probes do not replace browser,
accepted-work recovery, or sustained-memory tests.

Use `make test_socket_phoenix_browser_cluster` for the desktop/mobile Board chat
failover path. The target builds the current UI source into a unique ignored directory,
creates disposable users and project data, runs the tracked Playwright probe, and removes
the runtime configuration and build on exit. The probe requires both assigned users to
receive `board:chat:available`, rejects a forged nonmember subscription and command,
removes a connected member through the real API, and requires immediate access revocation,
navigation away, denied resubscription, and unaffected owner connectivity. It restores the
member before requiring Board subscriptions plus a new availability response after
reconnect. Set
`PHOENIX_BROWSER_FAILOVER_STAGE=resume`
to kill the owning Phoenix node after the approved external edit is persisted but before
the Graph response is released. `BOARD_CHAT_UI_BUILD` may point to an existing build when
repeating an identical bundle, but the default always tests current source. Reports remain
under `local/socket-migration`; executable fixtures do not.

Use `make test_socket_phoenix_editor_cluster` for distributed editor ownership and
binary persistence checks. It runs both explicit Erlang `halt` and graceful peer
shutdown, verifies that incomplete clusters reject document admission, and restores
the same document bytes after a replacement node joins. It covers acknowledged
client updates as well as server text changes and concurrent owner/clear races.
This local BEAM probe does not establish browser reconnection or production-volume
durability across host/storage failure.

## Configuration

### Editor Storage Durability

`Editor.SyncStorage` syncs a temporary file before atomically renaming it over the
document, then opens and syncs the parent directory. Deletion also syncs the parent
directory before returning success. The Linux release treats any file or directory
sync failure as a document persistence failure. Native Windows OTP cannot sync an
opened directory and is allowed only as a development-host fallback; the Docker
release uses the strict Linux path.

A release-container probe has verified save, load, delete, and recovery of an
acknowledged write after forced process termination. This does not prove survival
of host power loss or storage-backend failure. Production cutover still requires
the actual storage and mount contract plus a verified backup and restore.

`Editor.SyncManifest` verifies named documents through their Node-compatible name
hash. A correctly named 64-character lowercase SHA-256 `.ydoc` that cannot be
recovered from the database is preserved as an opaque document: both copies must
parse as Yjs, match byte-for-byte, and have the same SHA-256 checksum. Any other
file, destination-only file, missing copy, parse failure, checksum mismatch,
symbolic-link directory, or linked document keeps `verified` false. Source and
restore directories must also refer to distinct physical directories. This prevents
an unknown historical document from being
guessed, deleted, or silently excluded during migration.

### Runtime Settings

The runtime reads `API_INTERNAL_URL`, `DEFAULT_GRAPH_URL`, `PORT`, `PHX_HOST`, `SECRET_KEY_BASE`, `SOCKET_AUTH_POOL_SIZE`, `SOCKET_AUTH_TIMEOUT_MS`, `SOCKET_GRAPH_POOL_SIZE`, `SOCKET_MAX_IN_FLIGHT_COMMANDS`, `AI_REQUEST_TIMEOUT`, `SOCKET_IDLE_TIMEOUT_MS`, `SOCKET_MAX_PAYLOAD_MB`, and `SOCKET_PING_INTERVAL_MS`.

Trace export is disabled by default. Set `OTEL_TRACES_EXPORTER=otlp` and `OTEL_EXPORTER_OTLP_ENDPOINT` at deployment time to export spans. Authorization query values and authorization headers are not recorded as span attributes.

The optional Collector overlay scrapes Phoenix metrics and is not required for local
development. By default it discards trace payloads after proving OTLP receipt.
Set `SOCKET_PHOENIX_OTEL_TRACES_ENDPOINT` to an approved OTLP/HTTP `/v1/traces`
endpoint before a cutover soak; the traces overlay then replaces `nop` with
`otlp_http/traces` for the soak. Verify backend receipt before recording soak evidence. The
metrics pipeline is bounded by the Collector memory limiter and batch limits. Collector
pipeline health, including accepted and rejected spans, is exposed on loopback port `8888`
by default. Enabling this overlay does not constitute a successful 24-hour soak or authorize
cutover.

Run a qualifying soak only with operator-supplied thresholds and a load profile derived from
measured production traffic. The threshold JSON must define peak memory, growth and slope, aggregate
and maximum mailbox bounds, outbound and slow-client queue bounds, and per-kind worker/task
limits. It must also define the maximum Editor authorization backend/transport error ratio and
average authorization latency in microseconds. The load-profile JSON must identify its measurement
source, target socket count, minimum Editor authorization request count, and the worker/task kinds
that the workload must exercise. The repository does not invent defaults for these production
acceptance values:

```bash
make record_socket_phoenix_otel_soak \
  PHOENIX_OTEL_SOAK_THRESHOLDS=local/socket-migration/soak-thresholds.json \
  PHOENIX_OTEL_SOAK_LOAD_PROFILE=local/socket-migration/soak-load-profile.json \
  PHOENIX_OTEL_SOAK_REPORT=local/socket-migration/phoenix-otel-soak.json
```

The recorder writes a format-version 5 report and a checksum-linked JSONL sample file. Cutover
validation re-reads the samples, verifies their checksum and coverage, recomputes every bound,
requires Collector receiver and trace exporter counters plus Editor authorization counters to remain monotonic, and rejects a
Phoenix uptime reset. A short run can exercise the recorder but cannot pass the 24-hour cutover
minimum.

The slow-client queue series is event-driven. If no slow-client event has occurred during the
runtime lifetime, the recorder treats the absent series as zero. The outbound queue series remains
required. JSON bootstrap and direct protocol replies, asynchronous JSON payloads, heartbeats, and
editor-sync binary frames all contribute to the outbound series. A qualifying workload must still
exercise representative application and editor traffic rather than pass on bootstrap delivery alone.
The Editor authorization request and cumulative-duration metrics use only the fixed API route and
bounded result class as labels; they never include tokens, users, document names, or document IDs.

Metrics are exposed in Prometheus text format at `GET /internal/metrics`, independently
of trace export. Scrapes require exactly one `X-Socket-Internal-Secret` header matching
`SOCKET_PHOENIX_INTERNAL_SECRET` (at least 32 bytes); missing configuration fails closed.
Keep this route on the internal network. Configure the OTel collector's Prometheus
receiver to scrape each Phoenix instance, supplying the credential from deployment
secrets rather than committing it in collector configuration.

`langboard_socket_kafka_lag_count` and `langboard_socket_kafka_lag_available`
report the startup catch-up observation. A Kafka-enabled release does not become ready until
the configured consumer group has reached zero lag once. Later lag remains observable without
flapping established ingress readiness; ordinary Kafka assignment and dependency failures
still withdraw readiness through `Kafka.Ingress`.

VM memory values (`vm_memory_total`, `vm_memory_binary`, `vm_memory_processes`) are
bytes. Runtime process count and aggregate mailbox total/maximum are sampled every
10 seconds without PID, user, document, or request labels. Mailbox samples are not an
atomic snapshot and can miss shorter spikes. Connection/subscription changes use
gauges so decrements are preserved; reporter restarts reset these aggregates. Compare
only the same reporter/runtime lifetime when judging a memory plateau. The sampled
`langboard_socket_runtime_uptime_seconds` gauge lets the soak recorder reject a runtime
restart that would otherwise reset memory and queue measurements. The separate
`langboard_socket_runtime_sockets_count` gauge samples the existing monitored socket
registry (JSON and editor connections) and recovers on the next poll after reporter
restart without waiting for clients to reconnect.

The sampled worker gauge `langboard_socket_runtime_workers_active`
reports supervised Board chat runs, editor AI runs, and editor documents using only
the fixed `kind` labels `board_chat`, `editor_ai`, and `editor_document`. These are
local live processes, not counts of durable pending or completed database records.
Only use a count when `langboard_socket_runtime_workers_available` is 1; a missing
or restarting supervisor reports availability 0 without fabricating an empty count.
The next successful poll restores the count, including after reporter restart.
The `langboard_socket_runtime_tasks_active` and
`langboard_socket_runtime_tasks_available` gauges apply the same availability rule to
the bounded command and Graph-stream task supervisors, with fixed `command` and
`graph_stream` kind labels. A soak report must observe these series from the exact
runtime image being evaluated rather than infer task-registry bounds from configuration.
HTTP durations
are latest-value gauges in milliseconds, not percentiles: this avoids retaining raw
histogram observations while the collector is unavailable. End-to-end collector delivery and
long-running workload reconciliation still require deployment-level verification.

The shared wire values live in `src/shared/realtime/contract.json`; `yarn test` in `src/shared/ts` verifies the TypeScript enums against it.
