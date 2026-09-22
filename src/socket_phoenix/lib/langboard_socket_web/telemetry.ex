defmodule LangboardSocketWeb.Telemetry do
  use Supervisor
  import Telemetry.Metrics

  def start_link(arg) do
    Supervisor.start_link(__MODULE__, arg, name: __MODULE__)
  end

  @impl true
  def init(_arg) do
    children = [
      {TelemetryMetricsPrometheus.Core, metrics: metrics(), start_async: false},
      {:telemetry_poller, measurements: periodic_measurements(), period: 10_000}
    ]

    Supervisor.init(children, strategy: :one_for_one)
  end

  def metrics do
    [
      # Phoenix Metrics
      last_value("phoenix.endpoint.start.system_time",
        unit: {:native, :millisecond}
      ),
      last_value("phoenix.endpoint.stop.duration",
        unit: {:native, :millisecond}
      ),
      last_value("phoenix.router_dispatch.start.system_time",
        tags: [:route],
        unit: {:native, :millisecond}
      ),
      last_value("phoenix.router_dispatch.exception.duration",
        tags: [:route],
        unit: {:native, :millisecond}
      ),
      last_value("phoenix.router_dispatch.stop.duration",
        tags: [:route],
        unit: {:native, :millisecond}
      ),
      last_value("phoenix.socket_connected.duration",
        unit: {:native, :millisecond}
      ),
      sum("phoenix.socket_drain.count"),
      last_value("phoenix.channel_joined.duration",
        unit: {:native, :millisecond}
      ),
      last_value("phoenix.channel_handled_in.duration",
        tags: [:event],
        unit: {:native, :millisecond}
      ),
      counter("langboard_socket.kafka.message.count", tags: [:result, :topic]),
      counter("langboard_socket.kafka.legacy_fallback.count", tags: [:result]),
      counter("langboard_socket.kafka.processing_retry.count", tags: [:operation]),
      counter("langboard_socket.kafka.dead_letter.count", tags: [:result, :reason]),
      last_value("langboard_socket.kafka.lag.count"),
      last_value("langboard_socket.kafka.lag.available"),
      counter("langboard_socket.authorization.request.count", tags: [:route, :result]),
      sum("langboard_socket.authorization.request.duration_microseconds",
        event_name: [:langboard_socket, :authorization, :request],
        measurement: :duration_microseconds,
        tags: [:route, :result]
      ),
      sum("langboard_socket.websocket.connection_change.count",
        reporter_options: [prometheus_type: :gauge]
      ),
      sum("langboard_socket.websocket.subscription_change.count",
        reporter_options: [prometheus_type: :gauge]
      ),
      counter("langboard_socket.websocket.outbound.count"),
      sum("langboard_socket.websocket.outbound.bytes"),
      last_value("langboard_socket.websocket.outbound.queue_length"),
      counter("langboard_socket.websocket.slow_client.count"),
      last_value("langboard_socket.websocket.slow_client.queue_length"),
      last_value("langboard_socket.cluster.members.count", tags: [:ready]),

      # VM Metrics
      last_value("vm.memory.total", unit: :byte),
      last_value("vm.memory.binary", unit: :byte),
      last_value("vm.memory.processes", unit: :byte),
      last_value("vm.total_run_queue_lengths.total"),
      last_value("vm.total_run_queue_lengths.cpu"),
      last_value("vm.total_run_queue_lengths.io"),
      last_value("langboard_socket.runtime.uptime_seconds"),
      last_value("langboard_socket.runtime.process_count"),
      last_value("langboard_socket.runtime.sockets.count"),
      last_value("langboard_socket.runtime.workers.active", tags: [:kind]),
      last_value("langboard_socket.runtime.workers.available", tags: [:kind]),
      last_value("langboard_socket.runtime.tasks.active", tags: [:kind]),
      last_value("langboard_socket.runtime.tasks.available", tags: [:kind]),
      last_value("langboard_socket.runtime.mailbox_total"),
      last_value("langboard_socket.runtime.mailbox_max")
    ]
  end

  def emit_connection_change(count) do
    :telemetry.execute(
      [:langboard_socket, :websocket, :connection_change],
      %{count: count},
      %{}
    )
  end

  def emit_subscription_change(count) do
    :telemetry.execute(
      [:langboard_socket, :websocket, :subscription_change],
      %{count: count},
      %{}
    )
  end

  def emit_outbound(bytes, queue_length) do
    :telemetry.execute(
      [:langboard_socket, :websocket, :outbound],
      %{count: 1, bytes: bytes, queue_length: queue_length},
      %{}
    )
  end

  def emit_slow_client(queue_length) do
    :telemetry.execute(
      [:langboard_socket, :websocket, :slow_client],
      %{count: 1, queue_length: queue_length},
      %{}
    )
  end

  def emit_runtime_measurements do
    processes = Process.list()
    {uptime_milliseconds, _} = :erlang.statistics(:wall_clock)

    {total, maximum} =
      Enum.reduce(processes, {0, 0}, fn pid, {total, maximum} ->
        case Process.info(pid, :message_queue_len) do
          {:message_queue_len, count} -> {total + count, max(maximum, count)}
          nil -> {total, maximum}
        end
      end)

    :telemetry.execute(
      [:langboard_socket, :runtime],
      %{
        uptime_seconds: uptime_milliseconds / 1_000,
        process_count: length(processes),
        mailbox_total: total,
        mailbox_max: maximum
      },
      %{}
    )
  end

  defp periodic_measurements do
    [
      {LangboardSocket.ClusterStatus, :emit_measurement, []},
      {LangboardSocket.RuntimeStatus, :emit_measurement, []},
      {__MODULE__, :emit_worker_measurements, []},
      {__MODULE__, :emit_task_measurements, []},
      {__MODULE__, :emit_runtime_measurements, []}
    ]
  end

  def emit_worker_measurements do
    for {supervisor, kind} <- [
          {LangboardSocket.BoardChatRunSupervisor, :board_chat},
          {LangboardSocket.EditorRunSupervisor, :editor_ai},
          {LangboardSocket.EditorDocumentSupervisor, :editor_document}
        ] do
      :telemetry.execute(
        [:langboard_socket, :runtime, :workers],
        worker_measurement(supervisor),
        %{kind: kind}
      )
    end
  end

  def emit_task_measurements do
    for {supervisor, kind} <- [
          {LangboardSocket.CommandTaskSupervisor, :command},
          {LangboardSocket.BoardChatGraphTaskSupervisor, :graph_stream}
        ] do
      :telemetry.execute(
        [:langboard_socket, :runtime, :tasks],
        task_measurement(supervisor),
        %{kind: kind}
      )
    end
  end

  defp worker_measurement(supervisor) do
    %{active: active} = DynamicSupervisor.count_children(supervisor)
    %{active: active, available: 1}
  catch
    # Keep polling through supervisor restarts without reporting a false zero count.
    :exit, _reason -> %{available: 0}
  end

  defp task_measurement(supervisor) do
    %{active: supervisor |> Task.Supervisor.children() |> length(), available: 1}
  catch
    :exit, _reason -> %{available: 0}
  end
end
