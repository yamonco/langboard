defmodule LangboardSocket.RuntimeStatusTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.RuntimeStatus

  setup do
    on_exit(fn -> RuntimeStatus.reset() end)
    :ok
  end

  test "drain waits for socket exit and rejects new registrations" do
    owner = self()

    socket =
      spawn_link(fn ->
        :ok = RuntimeStatus.register_socket()
        send(owner, :registered)

        receive do
          :socket_drain -> send(owner, :draining)
        end

        receive do
          :finish -> :ok
        end
      end)

    on_exit(fn -> Process.exit(socket, :kill) end)
    assert_receive :registered
    drain = Task.async(fn -> RuntimeStatus.drain_sockets() end)
    assert_receive :draining
    assert {:error, :draining} = RuntimeStatus.register_socket()
    refute Task.yield(drain, 0)
    send(socket, :finish)
    assert :ok = Task.await(drain)
  end

  test "a drain timeout releases its monitors without killing the socket" do
    owner = self()

    socket =
      spawn_link(fn ->
        :ok = RuntimeStatus.register_socket()
        send(owner, :registered)

        receive do
          :socket_drain -> send(owner, :draining)
        end

        receive do
          :finish -> :ok
        end
      end)

    on_exit(fn -> Process.exit(socket, :kill) end)
    assert_receive :registered
    monitors = Process.info(self(), :monitors)
    assert {:error, {:timeout, 1}} = RuntimeStatus.drain_sockets(0)
    assert_receive :draining
    assert Process.alive?(socket)
    assert Process.info(self(), :monitors) == monitors
    send(socket, :finish)
  end

  test "registrations are deduplicated and removed on socket exit" do
    {:ok, state} = RuntimeStatus.init(false)
    from = {self(), make_ref()}
    assert {:reply, :ok, registered} = RuntimeStatus.handle_call(:register_socket, from, state)
    assert map_size(registered.sockets) == 1

    assert {:reply, :ok, ^registered} =
             RuntimeStatus.handle_call(:register_socket, from, registered)

    reference = Map.fetch!(registered.sockets, self())
    Process.demonitor(reference, [:flush])

    assert {:noreply, ^state} =
             RuntimeStatus.handle_info({:DOWN, reference, :process, self(), :normal}, registered)
  end

  test "an empty drain completes immediately" do
    handler = "runtime-readiness-#{System.unique_integer([:positive])}"

    :ok =
      :telemetry.attach(
        handler,
        [:langboard_socket, :runtime, :readiness_failure],
        fn _event, measurements, metadata, owner ->
          send(owner, {:readiness_failure, measurements, metadata})
        end,
        self()
      )

    on_exit(fn -> :telemetry.detach(handler) end)
    assert :ok = RuntimeStatus.drain_sockets(0)
    refute RuntimeStatus.ready?()
    assert_receive {:readiness_failure, %{count: 1}, %{reason: :draining}}
    refute RuntimeStatus.editor_ready?()
  end

  test "editor readiness remains independent of Kafka fanout" do
    previous_kafka = Application.fetch_env!(:langboard_socket, :kafka)
    previous_directory = Application.fetch_env!(:langboard_socket, :editor_sync_directory)
    directory = Path.join(System.tmp_dir!(), "editor-ready-#{System.unique_integer([:positive])}")
    File.mkdir_p!(directory)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :kafka, previous_kafka)
      Application.put_env(:langboard_socket, :editor_sync_directory, previous_directory)
      File.rm_rf!(directory)
    end)

    Application.put_env(:langboard_socket, :editor_sync_directory, directory)
    Application.put_env(:langboard_socket, :kafka, Keyword.put(previous_kafka, :enabled, true))

    assert RuntimeStatus.editor_ready?()
    refute RuntimeStatus.ready?()

    File.rm_rf!(directory)
    refute RuntimeStatus.editor_ready?()
  end

  test "socket snapshots recover after the metric reporter restarts" do
    reporter = :runtime_snapshot_reporter

    specification =
      {TelemetryMetricsPrometheus.Core,
       name: reporter,
       start_async: false,
       metrics: [Telemetry.Metrics.last_value("langboard_socket.runtime.sockets.count")]}

    start_supervised!(specification)
    baseline = map_size(:sys.get_state(RuntimeStatus).sockets)
    :ok = RuntimeStatus.register_socket()

    for attempt <- 1..2 do
      if attempt == 2 do
        stop_supervised!(reporter)
        start_supervised!(specification)
      end

      RuntimeStatus.emit_measurement()
      :sys.get_state(RuntimeStatus)

      assert TelemetryMetricsPrometheus.Core.scrape(reporter) =~
               "langboard_socket_runtime_sockets_count #{baseline + 1}"
    end
  end
end
