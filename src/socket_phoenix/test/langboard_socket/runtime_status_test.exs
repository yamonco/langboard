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
    assert :ok = RuntimeStatus.drain_sockets(0)
    refute RuntimeStatus.ready?()
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
