defmodule LangboardSocket.RuntimeStatus do
  @moduledoc false

  use GenServer

  def start_link(_opts), do: GenServer.start_link(__MODULE__, false, name: __MODULE__)

  def ready? do
    authorization_client = Application.fetch_env!(:langboard_socket, :authorization_client)

    GenServer.call(__MODULE__, :ready?) and
      LangboardSocket.ClusterStatus.ready?() and
      (not Application.fetch_env!(:langboard_socket, :editor_sync_enabled) or
         LangboardSocket.EditorDocument.cluster_ready?()) and
      is_pid(Process.whereis(LangboardSocket.PubSub)) and
      authorization_client.ready?() and
      LangboardSocket.KafkaIngress.ready?() and
      LangboardSocket.KafkaLagMonitor.ready?()
  catch
    :exit, _reason -> false
  end

  def begin_drain, do: GenServer.call(__MODULE__, :begin_drain)

  def register_socket, do: GenServer.call(__MODULE__, :register_socket)

  def emit_measurement, do: GenServer.cast(__MODULE__, :emit_measurement)

  def drain_sockets(timeout_ms \\ 5_000) do
    monitors =
      GenServer.call(__MODULE__, :drain_sockets)
      |> Map.new(fn pid ->
        reference = Process.monitor(pid)
        send(pid, :socket_drain)
        {reference, pid}
      end)

    await_sockets(monitors, System.monotonic_time(:millisecond) + timeout_ms)
  end

  @doc false
  def reset, do: GenServer.call(__MODULE__, :reset)

  @impl true
  def init(draining?), do: {:ok, %{draining?: draining?, sockets: %{}}}

  @impl true
  def handle_call(:ready?, _from, state), do: {:reply, not state.draining?, state}
  def handle_call(:begin_drain, _from, state), do: {:reply, :ok, %{state | draining?: true}}
  def handle_call(:reset, _from, state), do: {:reply, :ok, %{state | draining?: false}}

  def handle_call(:register_socket, _from, %{draining?: true} = state),
    do: {:reply, {:error, :draining}, state}

  def handle_call(:register_socket, {pid, _tag}, state) do
    sockets = Map.put_new_lazy(state.sockets, pid, fn -> Process.monitor(pid) end)
    {:reply, :ok, %{state | sockets: sockets}}
  end

  def handle_call(:drain_sockets, _from, state),
    do: {:reply, Map.keys(state.sockets), %{state | draining?: true}}

  @impl true
  def handle_cast(:emit_measurement, state) do
    :telemetry.execute(
      [:langboard_socket, :runtime, :sockets],
      %{count: map_size(state.sockets)},
      %{}
    )

    {:noreply, state}
  end

  @impl true
  def handle_info({:DOWN, reference, :process, pid, _reason}, state) do
    if Map.get(state.sockets, pid) == reference,
      do: {:noreply, %{state | sockets: Map.delete(state.sockets, pid)}},
      else: {:noreply, state}
  end

  defp await_sockets(monitors, _deadline) when map_size(monitors) == 0, do: :ok

  defp await_sockets(monitors, deadline) do
    timeout = max(deadline - System.monotonic_time(:millisecond), 0)

    # Terminate callbacks run before Bandit sends the close frame; wait for process exit.
    receive do
      {:DOWN, reference, :process, _pid, _reason} when is_map_key(monitors, reference) ->
        await_sockets(Map.delete(monitors, reference), deadline)
    after
      timeout ->
        Enum.each(monitors, fn {reference, _pid} -> Process.demonitor(reference, [:flush]) end)
        {:error, {:timeout, map_size(monitors)}}
    end
  end
end
