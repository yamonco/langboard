import Config

positive_integer = fn name, default ->
  value = System.get_env(name, default)

  case Integer.parse(value) do
    {parsed, ""} when parsed > 0 -> parsed
    _result -> raise ArgumentError, "#{name} must be a positive integer"
  end
end

editor_sync_expected_nodes =
  case System.get_env("SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES") do
    value when value in [nil, ""] -> 1
    _value -> positive_integer.("SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES", "1")
  end

# config/runtime.exs is executed for all environments, including
# during releases. It is executed after compilation and before the
# system starts, so it is typically used to load production configuration
# and secrets from environment variables or elsewhere. Do not define
# any compile-time configuration in here, as it won't be applied.
# The block below contains prod specific runtime configuration.

# ## Using releases
#
# If you use `mix release`, you need to explicitly enable the server
# by passing the PHX_SERVER=true when you start it:
#
#     PHX_SERVER=true bin/langboard_socket start
#
# Alternatively, you can use `mix phx.gen.release` to generate a `bin/server`
# script that automatically sets the env var above.
if System.get_env("PHX_SERVER") do
  config :langboard_socket, LangboardSocketWeb.Endpoint, server: true
end

config :langboard_socket, LangboardSocketWeb.Endpoint,
  http: [port: String.to_integer(System.get_env("PORT", "4000"))]

config :langboard_socket,
  api_internal_url:
    System.get_env("API_INTERNAL_URL", "http://localhost:5381") |> String.trim_trailing("/"),
  internal_api_secret: System.get_env("SOCKET_PHOENIX_INTERNAL_SECRET", ""),
  auth_pool_size: String.to_integer(System.get_env("SOCKET_AUTH_POOL_SIZE", "32")),
  auth_timeout_ms: String.to_integer(System.get_env("SOCKET_AUTH_TIMEOUT_MS", "3000")),
  graph_internal_url:
    System.get_env("DEFAULT_GRAPH_URL", "http://127.0.0.1:5020") |> String.trim_trailing("/"),
  graph_pool_size: positive_integer.("SOCKET_GRAPH_POOL_SIZE", "8"),
  graph_timeout_ms: positive_integer.("AI_REQUEST_TIMEOUT", "120") * 1_000,
  graph_stream_max_chunk_bytes: positive_integer.("AI_STREAM_MAX_BUFFER_MB", "4") * 1024 * 1024,
  ollama_pool_size: positive_integer.("SOCKET_OLLAMA_POOL_SIZE", "4"),
  ollama_timeout_ms: positive_integer.("AI_REQUEST_TIMEOUT", "120") * 1_000 + 10_000,
  cluster_minimum_size: positive_integer.("SOCKET_PHOENIX_CLUSTER_MINIMUM_SIZE", "1"),
  kafka: [
    enabled: System.get_env("SOCKET_PHOENIX_KAFKA_ENABLED", "false") == "true",
    hosts: System.get_env("BROADCAST_URLS", ""),
    source_topic: System.get_env("SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC"),
    group_id: System.get_env("BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP", ""),
    max_bytes: String.to_integer(System.get_env("BROADCAST_MAX_MESSAGE_BYTES", "10485760")),
    processor_concurrency:
      String.to_integer(System.get_env("SOCKET_KAFKA_PROCESSOR_CONCURRENCY", "1")),
    max_demand: String.to_integer(System.get_env("SOCKET_KAFKA_MAX_DEMAND", "10")),
    processing_max_attempts:
      String.to_integer(System.get_env("SOCKET_KAFKA_PROCESSING_MAX_ATTEMPTS", "3")),
    processing_retry_backoff_ms:
      String.to_integer(System.get_env("SOCKET_KAFKA_PROCESSING_RETRY_BACKOFF_MS", "100")),
    legacy_redis: [
      enabled: System.get_env("SOCKET_PHOENIX_LEGACY_REDIS_ENABLED", "true") == "true",
      url: System.get_env("CACHE_URL", ""),
      max_payload_bytes:
        String.to_integer(System.get_env("BROADCAST_MAX_MESSAGE_BYTES", "10485760"))
    ],
    dead_letter_topic: System.get_env("BROADCAST_PHOENIX_DEAD_LETTER_TOPIC"),
    dead_letter_max_payload_bytes:
      String.to_integer(System.get_env("SOCKET_KAFKA_DEAD_LETTER_MAX_PAYLOAD_BYTES", "65536")),
    dead_letter_publish_timeout_ms:
      String.to_integer(System.get_env("SOCKET_KAFKA_DEAD_LETTER_TIMEOUT_MS", "3000"))
  ],
  kafka_lag_poll_interval_ms:
    positive_integer.("SOCKET_PHOENIX_KAFKA_LAG_POLL_INTERVAL_MS", "1000"),
  socket_idle_timeout_ms: String.to_integer(System.get_env("SOCKET_IDLE_TIMEOUT_MS", "60000")),
  socket_ping_interval_ms: String.to_integer(System.get_env("SOCKET_PING_INTERVAL_MS", "30000")),
  socket_max_in_flight_commands: positive_integer.("SOCKET_MAX_IN_FLIGHT_COMMANDS", "32"),
  socket_max_outbound_queue_messages: positive_integer.("SOCKET_MAX_IN_FLIGHT_MESSAGES", "32"),
  board_chat_resume_enabled:
    System.get_env("SOCKET_PHOENIX_BOARD_CHAT_RESUME_ENABLED", "false") == "true",
  board_chat_send_enabled:
    System.get_env("SOCKET_PHOENIX_BOARD_CHAT_SEND_ENABLED", "false") == "true",
  board_chat_recovery_enabled:
    System.get_env("SOCKET_PHOENIX_BOARD_CHAT_RECOVERY_ENABLED", "false") == "true",
  editor_ai_enabled: System.get_env("SOCKET_PHOENIX_EDITOR_AI_ENABLED", "false") == "true",
  board_chat_recovery_interval_ms:
    positive_integer.("SOCKET_PHOENIX_BOARD_CHAT_RECOVERY_INTERVAL_MS", "5000"),
  editor_sync_enabled: System.get_env("SOCKET_PHOENIX_EDITOR_SYNC_ENABLED", "false") == "true",
  editor_sync_directory: System.get_env("SOCKET_PHOENIX_EDITOR_SYNC_STORAGE_DIR", ""),
  editor_sync_expected_nodes: editor_sync_expected_nodes,
  editor_sync_max_documents_per_connection:
    positive_integer.("SOCKET_EDITOR_SYNC_MAX_DOCUMENTS_PER_CONNECTION", "16"),
  editor_sync_max_documents: positive_integer.("SOCKET_EDITOR_SYNC_MAX_DOCUMENTS", "256"),
  editor_sync_max_clients_per_document:
    positive_integer.("SOCKET_EDITOR_SYNC_MAX_CLIENTS_PER_DOCUMENT", "32"),
  editor_sync_awareness_timeout_ms:
    positive_integer.("SOCKET_EDITOR_SYNC_AWARENESS_TIMEOUT_MS", "30000"),
  editor_sync_rich_patch_timeout_ms:
    positive_integer.("SOCKET_EDITOR_SYNC_RICH_PATCH_TIMEOUT_MS", "8000"),
  editor_sync_http_max_concurrency: positive_integer.("EDITOR_SYNC_MAX_CONCURRENCY", "8"),
  editor_sync_max_document_bytes:
    positive_integer.("SOCKET_EDITOR_SYNC_MAX_DOCUMENT_MB", "16") * 1024 * 1024,
  socket_max_payload_bytes:
    String.to_integer(System.get_env("SOCKET_MAX_PAYLOAD_MB", "8")) * 1024 * 1024

if config_env() == :prod do
  if System.get_env("SOCKET_PHOENIX_EDITOR_SYNC_ENABLED") == "true" and
       System.get_env("SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES") in [nil, ""] do
    raise "SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES is required when editor sync is enabled"
  end

  # The secret key base is used to sign/encrypt cookies and other secrets.
  # A default value is used in config/dev.exs and config/test.exs but you
  # want to use a different value for prod and you most likely don't want
  # to check this value into version control, so we use an environment
  # variable instead.
  secret_key_base =
    System.get_env("SECRET_KEY_BASE") ||
      raise """
      environment variable SECRET_KEY_BASE is missing.
      You can generate one by calling: mix phx.gen.secret
      """

  host = System.get_env("PHX_HOST", "localhost")

  config :langboard_socket,
         :dns_cluster_query,
         System.get_env("SOCKET_PHOENIX_CLUSTER_DNS_QUERY")

  config :langboard_socket, LangboardSocketWeb.Endpoint,
    url: [host: host, port: 443, scheme: "https"],
    http: [
      # Enable IPv6 and bind on all interfaces.
      # Set it to  {0, 0, 0, 0, 0, 0, 0, 1} for local network only access.
      # See the documentation on https://bandit.hexdocs.pm/Bandit.html#t:options/0
      # for details about using IPv6 vs IPv4 and loopback vs public addresses.
      ip: {0, 0, 0, 0, 0, 0, 0, 0}
    ],
    secret_key_base: secret_key_base

  # ## SSL Support
  #
  # To get SSL working, you will need to add the `https` key
  # to your endpoint configuration:
  #
  #     config :langboard_socket, LangboardSocketWeb.Endpoint,
  #       https: [
  #         ...,
  #         port: 443,
  #         cipher_suite: :strong,
  #         keyfile: System.get_env("SOME_APP_SSL_KEY_PATH"),
  #         certfile: System.get_env("SOME_APP_SSL_CERT_PATH")
  #       ]
  #
  # The `cipher_suite` is set to `:strong` to support only the
  # latest and more secure SSL ciphers. This means old browsers
  # and clients may not be supported. You can set it to
  # `:compatible` for wider support.
  #
  # `:keyfile` and `:certfile` expect an absolute path to the key
  # and cert in disk or a relative path inside priv, for example
  # "priv/ssl/server.key". For all supported SSL configuration
  # options, see https://plug.hexdocs.pm/Plug.SSL.html#configure/1
  #
  # We also recommend setting `force_ssl` in your config/prod.exs,
  # ensuring no data is ever sent via http, always redirecting to https:
  #
  #     config :langboard_socket, LangboardSocketWeb.Endpoint,
  #       force_ssl: [hsts: true]
  #
  # Check `Plug.SSL` for all available options in `force_ssl`.
end
