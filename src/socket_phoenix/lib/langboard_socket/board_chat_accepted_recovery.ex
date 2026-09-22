defmodule LangboardSocket.BoardChatAcceptedRecovery do
  @moduledoc false
  use GenServer

  alias LangboardSocket.BoardChatRunClient
  alias LangboardSocket.BoardChatRunWorker

  def start_link(options \\ []), do: GenServer.start_link(__MODULE__, options)

  @impl true
  def init(options) do
    state = %{
      run_client: Keyword.get(options, :run_client, BoardChatRunClient),
      run_worker: Keyword.get(options, :run_worker, BoardChatRunWorker),
      supervisor: Keyword.get(options, :supervisor, LangboardSocket.BoardChatRunSupervisor),
      interval_ms:
        Keyword.get(
          options,
          :interval_ms,
          Application.fetch_env!(:langboard_socket, :board_chat_recovery_interval_ms)
        ),
      max_workers: Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands),
      active: %{},
      cursor: nil
    }

    send(self(), :scan)
    {:ok, state}
  end

  @impl true
  def handle_info(:scan, state) do
    capacity =
      max(state.max_workers - DynamicSupervisor.count_children(state.supervisor).active, 0)

    next_state =
      if capacity == 0 do
        state
      else
        case state.run_client.list_accepted(100, after_run_uid: state.cursor) do
          {:ok, []} ->
            %{state | cursor: nil}

          {:ok, runs} ->
            %{
              state
              | active: start_recovered(runs, capacity, state),
                cursor: List.last(runs)["run_uid"]
            }

          {:error, _reason} ->
            state
        end
      end

    Process.send_after(self(), :scan, state.interval_ms)
    {:noreply, next_state}
  end

  def handle_info({:DOWN, reference, :process, _pid, _reason}, state) do
    active = Map.reject(state.active, fn {_run_uid, current} -> current == reference end)
    {:noreply, %{state | active: active}}
  end

  def handle_info(_message, state), do: {:noreply, state}

  defp start_recovered(runs, capacity, state) do
    Enum.reduce_while(runs, {capacity, state.active}, &start_recovered_run(&1, &2, state))
    |> elem(1)
  end

  defp start_recovered_run(_run, {0, active}, _state), do: {:halt, {0, active}}

  defp start_recovered_run(run, {remaining, active}, state) do
    run_uid = run["run_uid"]

    if Map.has_key?(active, run_uid) do
      {:cont, {remaining, active}}
    else
      options = [project_uid: run["project_uid"], recovery_run: run]

      case DynamicSupervisor.start_child(state.supervisor, {state.run_worker, options}) do
        {:ok, pid} ->
          {:cont, {remaining - 1, Map.put(active, run_uid, Process.monitor(pid))}}

        {:error, :max_children} ->
          {:halt, {remaining, active}}

        {:error, _reason} ->
          {:cont, {remaining, active}}
      end
    end
  end
end
