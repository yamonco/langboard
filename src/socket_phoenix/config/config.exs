# This file is responsible for configuring your application
# and its dependencies with the aid of the Config module.
#
# This configuration file is loaded before any dependency and
# is restricted to this project.

# General application configuration
import Config

config :langboard_socket,
  generators: [timestamp_type: :utc_datetime],
  api_internal_url: "http://localhost:5381",
  auth_pool_size: 32,
  auth_timeout_ms: 3_000,
  authorization_client: LangboardSocket.AuthClient,
  bot_status_client: LangboardSocket.BotStatusClient,
  chat_availability_client: LangboardSocket.ChatAvailabilityClient,
  notification_client: LangboardSocket.NotificationClient,
  ollama_client: LangboardSocket.OllamaClient,
  ollama_pool_size: 4,
  ollama_timeout_ms: 130_000,
  graph_internal_url: "http://127.0.0.1:5020",
  graph_pool_size: 8,
  graph_timeout_ms: 120_000,
  cluster_minimum_size: 1,
  dead_letter_publisher: LangboardSocket.KafkaDeadLetter,
  legacy_payload_store: LangboardSocket.LegacyPayloadStore,
  kafka: [
    enabled: false,
    hosts: "",
    group_id: "",
    max_bytes: 10 * 1024 * 1024,
    processor_concurrency: 1,
    max_demand: 10,
    processing_max_attempts: 3,
    processing_retry_backoff_ms: 100,
    legacy_redis: [enabled: false, url: "", max_payload_bytes: 10 * 1024 * 1024],
    dead_letter_topic: nil,
    dead_letter_max_payload_bytes: 64 * 1024,
    dead_letter_publish_timeout_ms: 3_000
  ],
  kafka_lag_poll_interval_ms: 1_000,
  socket_idle_timeout_ms: 60_000,
  socket_ping_interval_ms: 30_000,
  socket_max_in_flight_commands: 32,
  board_chat_recovery_interval_ms: 5_000,
  editor_sync_rich_patch_timeout_ms: 8_000,
  socket_max_outbound_queue_messages: 32,
  socket_max_payload_bytes: 8 * 1024 * 1024

# Configure the endpoint
config :langboard_socket, LangboardSocketWeb.Endpoint,
  url: [host: "localhost"],
  adapter: Bandit.PhoenixAdapter,
  render_errors: [
    formats: [json: LangboardSocketWeb.ErrorJSON],
    layout: false
  ],
  pubsub_server: LangboardSocket.PubSub

# Configure Elixir's Logger
config :logger, :default_formatter,
  format: "$time $metadata[$level] $message\n",
  metadata: [:request_id, :topic, :partition, :offset, :reason]

# Use Jason for JSON parsing in Phoenix
config :phoenix, :json_library, Jason

config :opentelemetry,
  span_processor: :batch,
  traces_exporter: :none,
  bsp_max_queue_size: 1_024,
  attribute_count_limit: 64,
  attribute_value_length_limit: 1_024,
  event_count_limit: 64,
  link_count_limit: 64

# Import environment specific config. This must remain at the bottom
# of this file so it overrides the configuration defined above.
import_config "#{config_env()}.exs"
