# Langboard Phoenix Socket

This is the Phoenix replacement runtime for `src/socket`. The default deployment
still retains Node for the staged migration; the full-owner Compose overlay selects
Phoenix explicitly. Implementation availability is not production cutover approval.

## Current migration slice

- Phoenix/Bandit endpoint with the existing raw JSON WebSocket envelope
- `/health`, `/health/live`, and dependency-aware `/health/ready`
- Access-token validation through the Python `/auth/socket` boundary
- Existing automatic `global:all` and `user_private:<uid>` subscriptions
- Authorized board subscriptions, clustered PubSub, and bounded Kafka fanout ingress
- Board bot status reads with a separate Graph HTTP pool and bounded command workers
- Payload, HTTP pool, timeout, worker, trace queue, and trace attribute limits
- OpenTelemetry spans for HTTP routes and internal Finch requests

## Responsibility ownership

The table identifies implemented replacement paths, not completed rollout gates.
Python `routes/` paths below are relative to `src/api/langboard`; domain service,
repository, and task names resolve under `src/shared/py/langboard_shared`.
Other paths are relative to the repository root. Phoenix module names resolve under
`src/socket_phoenix/lib/langboard_socket`, except web modules under
`src/socket_phoenix/lib/langboard_socket_web`.

| Node responsibility | Replacement execution owner | Durable/domain owner |
| --- | --- | --- |
| JSON connection, subscriptions, command dispatch | `SocketHandler`, `SubscriptionTopic`, Phoenix.PubSub | Python `routes/auth/SocketAuthApi.py` and `SocketAuthorization.py` authorize current access |
| `SocketConsumer` broker projection and fanout | `KafkaIngress`, `BrokerEnvelope`, `SocketEventProjector` | Python publishers emit inline v2 envelopes; `LegacyPayloadStore` is transitional only |
| `NotificationConsumer` creation, unsubscribe checks, email | Python `NotificationService` and notification recovery tasks | Python notification repositories and email outbox; Phoenix does not send email |
| Notification read/delete commands | `NotificationClient` forwards authenticated commands | Python `routes/notification/NotificationApi.py` |
| Board bot status and chat availability | `BotStatusClient`, `ChatAvailabilityClient` | Graph status endpoint and Python socket authorization API |
| Board chat send, cancel, streaming, reconnect recovery | `BoardChatRunWorker`, `BoardChatAcceptedRecovery` | Python `InternalBotRunService` and socket run endpoints persist accepted work and history |
| Board chat approval resume | `BoardChatResumeWorker`, `GraphResumeClient` | Python `GraphApprovalRequestService` and run/approval claim endpoints |
| Editor chat/copilot, abort, status, approval resume | `EditorRunWorker`, `EditorAcceptedRecovery`, `EditorResumeWorker` | Python editor run/approval endpoints, using the same durable run service |
| Graph/Langflow response streaming | `GraphStreamClient`, `LangflowStreamClient` and run workers | Python authorizes and records run transitions; external services perform their own operations |
| Board chat attachment upload | Python `routes/board/BoardChatApi.py` | `BoardChatAttachment`, `LangflowFileClient`, storage and cleanup task; UI uses the API route |
| Ollama copy/delete/pull commands and progress | `OllamaClient` forwards commands; Kafka/PubSub distributes progress | Python socket/Ollama endpoints, `OllamaModelPullService` and recovery task |
| Hocuspocus/Yjs binary sync and awareness | `EditorSyncHandler`, `EditorDocument`, `EditorSyncFrame` | `EditorSyncStorage` preserves binary `.ydoc` files; one document owner |
| Editor active/clear/text/patch HTTP operations | `EditorSyncController`, `EditorHttpLimiter` | Python editor authorization; binary storage and existing rich-patch publication |
| HTTP health, drain, resource lifecycle | `HealthController`, `RuntimeStatus`, OTP supervision | Compose health/readiness and deployment drain sequence |

The legacy entry points are enumerated by `src/socket/scripts/check-runtime-registration.mjs`.
Node files remain for comparison and rollback, not as a required permanent companion
to Phoenix. Full-owner configuration must disable Node consumption and select the
Phoenix editor owner together. Python email outbox and recovery scheduling must be
enabled before removing the legacy side-effect owner.

The legacy `N8NRequest.ts` file is not selected by Node's `createRequest` factory,
and the project-chat API rejects N8N before accepting work. Phoenix preserves that
existing project-chat contract rather than adding a new N8N stream adapter during
this migration. Background Bot tasks remain separate: Python's Bot task request
factory owns their supported N8N execution path.

Before production cutover, complete the migration plan's browser/recovery matrix,
production document manifest and restore proof, staged ownership/rollback rehearsal,
and sustained OTel observation. Only after those gates may the Node runtime and
temporary compatibility paths be removed. Ordinary SMTP has ambiguous failure
windows; the outbox records uncertain delivery rather than promising exactly-once mail.

## Commands

```shell
mix deps.get
mix phx.server
mix format --check-formatted
mix compile --warnings-as-errors
mix test
```

From the repository root, use `make test_socket_phoenix` or `make build_socket_phoenix_image`.
Use `make test_socket_protocol_parity` while the Node owner is running to build an isolated
Phoenix canary and execute the same raw WebSocket suite against both runtimes. The suite
covers bootstrap subscriptions, malformed and missing fields, unknown events and topics,
authorization denial, binary JSON, ordered rapid subscribe/unsubscribe frames, subscription
limits, authentication close codes, and oversized payloads. It removes the canary on success
or failure and does not switch the active owner.

Before selecting Phoenix as the complete Socket owner, run the fail-closed preflight with
the production-derived editor restore manifest and a representative 24-hour OTel soak report:

```shell
make validate_socket_phoenix_cutover_evidence \
  PHOENIX_CUTOVER_EDITOR_MANIFEST=/secure/evidence/editor-sync-manifest.json \
  PHOENIX_CUTOVER_OTEL_SOAK_REPORT=/secure/evidence/phoenix-otel-soak.json
```

The editor evidence must be a verified format-version 2 `EditorSyncManifest` result with
no unmapped files and byte-identical checksums. The OTel evidence must identify itself as
format-version 3 `phoenix_otel_soak`, cover at least 24 hours under representative load,
contain at least 90 percent of the expected metric samples, prove bounded memory, mailboxes,
buffers, Editor authorization behavior, and task registries, and contain no rollback trigger.
A short delivery probe does not pass.
`start_docker`, `rebuild_docker`, and `update_docker` run this preflight automatically when
`SOCKET_OWNER=phoenix`; missing evidence prevents the ownership change. Build-based commands
finish the image build before preflight, and the soak report's exact image digest must match
the image selected for deployment. The service replacement starts only after that comparison.
Production owner preparation also rejects `SOCKET_PHOENIX_INTERNAL_SECRET` values shorter
than 32 characters. The isolated canary target requires the same configured secret and
verifies the authenticated Kafka lag metrics before it returns successfully.
The API and Phoenix services must receive the same internal secret. Phoenix readiness calls
the internal API capability endpoint from the shared realtime contract and opens only when
the API reports the exact supported contract version. A missing route, invalid secret,
malformed response, or mismatched version keeps `/health/ready` closed, so an incompatible
API and Phoenix pair cannot accept new socket traffic during a rolling deployment.
Owner preparation then initializes the new Phoenix Kafka group before checking that the
legacy Node groups are stopped and drained. Phoenix readiness remains closed until the new
group reaches zero lag once, so events published during the handoff are processed before
client ingress opens instead of being skipped or replayed to connected clients.

The Phoenix CI workflow also runs the TypeScript realtime contract, Yjs/Yex
interoperability, and distributed editor recovery probes under `MIX_ENV=test`.
These supplement Elixir formatting, compilation, tests, Credo, and Dialyzer; they
do not replace deployed browser, storage, or soak gates.

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

`EditorSyncStorage` syncs a temporary file before atomically renaming it over the
document, then opens and syncs the parent directory. Deletion also syncs the parent
directory before returning success. The Linux release treats any file or directory
sync failure as a document persistence failure. Native Windows OTP cannot sync an
opened directory and is allowed only as a development-host fallback; the Docker
release uses the strict Linux path.

A release-container probe has verified save, load, delete, and recovery of an
acknowledged write after forced process termination. This does not prove survival
of host power loss or storage-backend failure. Production cutover still requires
the actual storage and mount contract plus a verified backup and restore.

`EditorSyncManifest` verifies named documents through their Node-compatible name
hash. A correctly named 64-character lowercase SHA-256 `.ydoc` that cannot be
recovered from the database is preserved as an opaque document: both copies must
parse as Yjs, match byte-for-byte, and have the same SHA-256 checksum. Any other
file, destination-only file, missing copy, parse failure, or checksum mismatch
keeps `verified` false. This prevents an unknown historical document from being
guessed, deleted, or silently excluded during migration.

### Runtime Settings

The runtime reads `API_INTERNAL_URL`, `DEFAULT_GRAPH_URL`, `PORT`, `PHX_HOST`, `SECRET_KEY_BASE`, `SOCKET_AUTH_POOL_SIZE`, `SOCKET_AUTH_TIMEOUT_MS`, `SOCKET_GRAPH_POOL_SIZE`, `SOCKET_MAX_IN_FLIGHT_COMMANDS`, `AI_REQUEST_TIMEOUT`, `SOCKET_IDLE_TIMEOUT_MS`, `SOCKET_MAX_PAYLOAD_MB`, and `SOCKET_PING_INTERVAL_MS`.

Trace export is disabled by default. Set `OTEL_TRACES_EXPORTER=otlp` and `OTEL_EXPORTER_OTLP_ENDPOINT` at deployment time to export spans. Authorization query values and authorization headers are not recorded as span attributes.

For a local or staging canary, pass `WITH_OTEL=true` to the Make target. This adds the
digest-pinned Collector overlay, enables OTLP trace delivery from Phoenix, scrapes the
protected Phoenix metrics endpoint every 10 seconds, and exposes only the Collector's
Prometheus exporter on loopback port `9464` by default:

```bash
make start_socket_phoenix_canary WITH_OTEL=true
make check_socket_phoenix_otel
make stop_socket_phoenix_canary WITH_OTEL=true
```

The repository Collector deliberately discards trace payloads after proving OTLP delivery;
production must replace the `nop` trace exporter with its approved telemetry backend. The
metrics pipeline is bounded by the Collector memory limiter and batch limits. Collector
pipeline health, including accepted and rejected spans, is exposed on loopback port `8888`
by default. Enabling this overlay does not constitute a successful 24-hour soak or authorize
cutover.

Run a qualifying soak only with operator-supplied thresholds and a load profile derived from
measured production traffic. The threshold JSON must define memory growth and slope, aggregate
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

The recorder writes a format-version 3 report and a checksum-linked JSONL sample file. Cutover
validation re-reads the samples, verifies their checksum and coverage, recomputes every bound,
requires Collector counters and Editor authorization counters to remain monotonic, and rejects a
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
still withdraw readiness through `KafkaIngress`.

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
