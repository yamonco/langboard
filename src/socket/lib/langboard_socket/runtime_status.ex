defmodule LangboardSocket.RuntimeStatus do
  @moduledoc false

  use GenServer

  alias LangboardSocket.Broker.Kafka.{Ingress, LagMonitor}
  alias LangboardSocket.Editor.Document

  def start_link(_opts), do: GenServer.start_link(__MODULE__, false, name: __MODULE__)

  def ready? do
    case readiness_failure() do
      nil ->
        true

      reason ->
        emit_readiness_failure(reason)
        false
    end
  catch
    :exit, _reason ->
      emit_readiness_failure(:runtime_unavailable)
      false
  end

  defp readiness_failure do
    case base_readiness_failure() do
      nil -> service_readiness_failure()
      reason -> reason
    end
  end

  defp base_readiness_failure do
    authorization_client = Application.fetch_env!(:langboard_socket, :authorization_client)

    cond do
      not GenServer.call(__MODULE__, :ready?) ->
        :draining

      not LangboardSocket.ClusterStatus.ready?() ->
        :cluster_unavailable

      not is_pid(Process.whereis(LangboardSocket.PubSub)) ->
        :pubsub_unavailable

      not authorization_client.ready?() ->
        :api_unavailable

      true ->
        nil
    end
  end

  defp service_readiness_failure do
    cond do
      Application.fetch_env!(:langboard_socket, :editor_sync_enabled) and
          not editor_storage_ready?() ->
        :editor_unavailable

      not Ingress.ready?() ->
        :kafka_ingress_unavailable

      not LagMonitor.ready?() ->
        :kafka_lag_unavailable

      true ->
        nil
    end
  end

  defp emit_readiness_failure(reason) do
    :telemetry.execute(
      [:langboard_socket, :runtime, :readiness_failure],
      %{count: 1},
      %{reason: reason}
    )
  end

  def editor_ready? do
    base_ready?() and editor_storage_ready?()
  catch
    :exit, _reason -> false
  end

  defp base_ready? do
    authorization_client = Application.fetch_env!(:langboard_socket, :authorization_client)

    GenServer.call(__MODULE__, :ready?) and
      LangboardSocket.ClusterStatus.ready?() and
      is_pid(Process.whereis(LangboardSocket.PubSub)) and
      authorization_client.ready?()
  end

  defp editor_storage_ready? do
    Document.cluster_ready?() and
      File.dir?(Application.fetch_env!(:langboard_socket, :editor_sync_directory))
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
