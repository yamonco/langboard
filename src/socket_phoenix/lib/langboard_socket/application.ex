defmodule LangboardSocket.Application do
  # See https://elixir.hexdocs.pm/Application.html
  # for more information on OTP Applications
  @moduledoc false

  use Application

  require Logger

  @impl true
  def start(_type, _args) do
    if Application.fetch_env!(:langboard_socket, :editor_sync_enabled) do
      directory = Application.fetch_env!(:langboard_socket, :editor_sync_directory)

      case LangboardSocket.EditorSyncStorage.verify_writable(directory) do
        :ok -> :ok
        {:error, reason} -> raise "Editor document storage is unavailable: #{inspect(reason)}"
      end
    end

    :ok = OpentelemetryPhoenix.setup(adapter: :bandit, liveview: false)
    :ok = OpentelemetryBroadway.setup(span_relationship: :none)

    auth_pool_size = Application.fetch_env!(:langboard_socket, :auth_pool_size)
    auth_timeout = Application.fetch_env!(:langboard_socket, :auth_timeout_ms)
    graph_pool_size = Application.fetch_env!(:langboard_socket, :graph_pool_size)
    graph_timeout = Application.fetch_env!(:langboard_socket, :graph_timeout_ms)
    ollama_pool_size = Application.fetch_env!(:langboard_socket, :ollama_pool_size)
    ollama_timeout = Application.fetch_env!(:langboard_socket, :ollama_timeout_ms)

    max_in_flight_commands =
      Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands)

    children =
      [
        LangboardSocketWeb.Telemetry,
        LangboardSocket.RuntimeStatus,
        {DNSCluster,
         query: Application.get_env(:langboard_socket, :dns_cluster_query) || :ignore},
        {Finch,
         name: LangboardSocket.Finch,
         pools: %{
           default: [
             size: auth_pool_size,
             conn_opts: [transport_opts: [timeout: auth_timeout]]
           ]
         }},
        {Finch,
         name: LangboardSocket.GraphFinch,
         pools: %{
           default: [
             size: graph_pool_size,
             conn_opts: [transport_opts: [timeout: graph_timeout]]
           ]
         }},
        {Finch,
         name: LangboardSocket.OllamaFinch,
         pools: %{
           default: [
             size: ollama_pool_size,
             conn_opts: [transport_opts: [timeout: ollama_timeout]]
           ]
         }},
        {Task.Supervisor,
         name: LangboardSocket.CommandTaskSupervisor, max_children: max_in_flight_commands},
        {Task.Supervisor,
         name: LangboardSocket.BoardChatGraphTaskSupervisor, max_children: max_in_flight_commands},
        {DynamicSupervisor,
         strategy: :one_for_one,
         name: LangboardSocket.BoardChatRunSupervisor,
         max_children: max_in_flight_commands},
        {DynamicSupervisor,
         strategy: :one_for_one,
         name: LangboardSocket.EditorRunSupervisor,
         max_children: max_in_flight_commands},
        {DynamicSupervisor,
         strategy: :one_for_one,
         name: LangboardSocket.EditorDocumentSupervisor,
         max_children: Application.fetch_env!(:langboard_socket, :editor_sync_max_documents)},
        LangboardSocket.EditorHttpLimiter,
        {Phoenix.PubSub, name: LangboardSocket.PubSub}
      ] ++
        board_chat_recovery_children() ++
        editor_recovery_children() ++ kafka_children() ++ [LangboardSocketWeb.Endpoint]

    # See https://elixir.hexdocs.pm/Supervisor.html
    # for other strategies and supported options
    opts = [strategy: :one_for_one, name: LangboardSocket.Supervisor]
    Supervisor.start_link(children, opts)
  end

  # Tell Phoenix to update the endpoint configuration
  # whenever the application is updated.
  @impl true
  def config_change(changed, _new, removed) do
    LangboardSocketWeb.Endpoint.config_change(changed, removed)
    :ok
  end

  @impl true
  def prep_stop(state) do
    :ok = LangboardSocket.RuntimeStatus.begin_drain()

    if LangboardSocket.KafkaIngress.enabled?() and
         is_pid(Process.whereis(LangboardSocket.Supervisor)) do
      case Supervisor.terminate_child(
             LangboardSocket.Supervisor,
             LangboardSocket.KafkaIngress
           ) do
        :ok -> :ok
        {:error, :not_found} -> :ok
      end
    end

    case LangboardSocket.RuntimeStatus.drain_sockets() do
      :ok ->
        :ok

      {:error, {:timeout, count}} ->
        Logger.warning("WebSocket drain timed out: #{count} remaining")
    end

    state
  end

  defp board_chat_recovery_children do
    if Application.fetch_env!(:langboard_socket, :board_chat_send_enabled) and
         Application.fetch_env!(:langboard_socket, :board_chat_recovery_enabled) do
      [LangboardSocket.BoardChatAcceptedRecovery]
    else
      []
    end
  end

  defp editor_recovery_children do
    if Application.fetch_env!(:langboard_socket, :editor_ai_enabled) do
      [LangboardSocket.EditorAcceptedRecovery]
    else
      []
    end
  end

  defp kafka_children do
    if LangboardSocket.KafkaIngress.enabled?() do
      config = Application.fetch_env!(:langboard_socket, :kafka)
      legacy_redis = Keyword.fetch!(config, :legacy_redis)

      legacy_children =
        if Keyword.fetch!(legacy_redis, :enabled),
          do: [{LangboardSocket.LegacyPayloadStore, legacy_redis}],
          else: []

      legacy_children ++
        [
          {LangboardSocket.KafkaDeadLetter, config},
          LangboardSocket.KafkaIngress,
          {LangboardSocket.KafkaLagMonitor,
           config: config,
           poll_interval_ms:
             Application.fetch_env!(:langboard_socket, :kafka_lag_poll_interval_ms)}
        ]
    else
      []
    end
  end
end
