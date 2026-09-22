defmodule LangboardSocket.EditorHttpLimiter do
  @moduledoc false
  use GenServer

  def start_link(_options), do: GenServer.start_link(__MODULE__, :ok, name: __MODULE__)
  def acquire, do: GenServer.call(__MODULE__, {:acquire, self()})
  def release, do: GenServer.call(__MODULE__, {:release, self()})

  @impl true
  def init(:ok) do
    {:ok,
     %{
       max: Application.fetch_env!(:langboard_socket, :editor_sync_http_max_concurrency),
       holders: %{}
     }}
  end

  @impl true
  def handle_call({:acquire, owner}, _from, state) do
    cond do
      Map.has_key?(state.holders, owner) ->
        {:reply, :ok, state}

      map_size(state.holders) >= state.max ->
        {:reply, {:error, :overloaded}, state}

      true ->
        monitor = Process.monitor(owner)
        {:reply, :ok, %{state | holders: Map.put(state.holders, owner, monitor)}}
    end
  end

  def handle_call({:release, owner}, _from, state) do
    {:reply, :ok, release_owner(owner, state)}
  end

  @impl true
  def handle_info({:DOWN, monitor, :process, owner, _reason}, state) do
    if Map.get(state.holders, owner) == monitor do
      {:noreply, release_owner(owner, state)}
    else
      {:noreply, state}
    end
  end

  defp release_owner(owner, state) do
    case Map.pop(state.holders, owner) do
      {nil, _holders} ->
        state

      {monitor, holders} ->
        Process.demonitor(monitor, [:flush])
        %{state | holders: holders}
    end
  end
end
