defmodule LangboardSocket.BoardChatResumeWorker do
  @moduledoc false
  use GenServer

  alias LangboardSocket.BoardChatRunClient
  alias LangboardSocket.GraphResumeClient

  def child_spec(options) do
    %{
      id: {__MODULE__, Keyword.fetch!(options, :command)["message_uid"]},
      start: {__MODULE__, :start_link, [options]},
      restart: :temporary
    }
  end

  def start_link(options) when is_list(options), do: GenServer.start_link(__MODULE__, options)

  @impl true
  def init(options) do
    graph_timeout = Application.fetch_env!(:langboard_socket, :graph_timeout_ms)

    state = %{
      token: Keyword.fetch!(options, :token),
      project_uid: Keyword.fetch!(options, :project_uid),
      command: Keyword.fetch!(options, :command),
      receiver: Keyword.fetch!(options, :receiver),
      run_client: Keyword.get(options, :run_client, BoardChatRunClient),
      graph_client: Keyword.get(options, :graph_client, GraphResumeClient),
      graph_supervisor:
        Keyword.get(options, :graph_supervisor, LangboardSocket.BoardChatGraphTaskSupervisor),
      lease_interval: max(div(graph_timeout, 4), 1_000),
      claim: nil,
      graph_task: nil
    }

    {:ok, state, {:continue, :claim}}
  end

  @impl true
  def handle_continue(:claim, state) do
    case state.run_client.claim_resume(state.token, state.project_uid, state.command) do
      {:ok, claim} ->
        start_graph_resume(%{state | claim: claim})

      {:error, reason} ->
        receiver_event(state, :claim_failed, %{reason: reason})
        {:stop, :normal, state}
    end
  end

  defp start_graph_resume(%{claim: claim} = state) do
    owner = self()

    case Task.Supervisor.start_child(state.graph_supervisor, fn ->
           result = state.graph_client.resume(claim.thread_id, claim.session_id, claim.resume)
           send(owner, {:graph_result, self(), result})
         end) do
      {:ok, pid} ->
        monitor = Process.monitor(pid)
        Process.send_after(self(), :renew_lease, state.lease_interval)
        {:noreply, %{state | graph_task: %{pid: pid, monitor: monitor}}}

      {:error, _reason} ->
        receiver_event(state, :result_unknown, %{reason: :capacity})
        {:stop, :normal, state}
    end
  end

  @impl true
  def handle_info({:graph_result, task_pid, {:ok, graph_result}}, state) do
    if current_task?(state, task_pid) do
      Process.demonitor(state.graph_task.monitor, [:flush])
      claim = state.claim

      case state.run_client.complete_resume(
             state.project_uid,
             claim.run_uid,
             claim.attempt,
             claim.thread_id,
             claim.session_id,
             graph_result
           ) do
        {:ok, persisted} ->
          publish_persisted_result(state, persisted)
          receiver_event(state, :finished, %{})
          {:stop, :normal, state}

        {:error, reason} ->
          receiver_event(state, :result_unknown, %{reason: reason})
          {:stop, :normal, state}
      end
    else
      {:noreply, state}
    end
  end

  def handle_info({:graph_result, task_pid, {:error, reason}}, state) do
    if current_task?(state, task_pid) do
      Process.demonitor(state.graph_task.monitor, [:flush])
      receiver_event(state, :result_unknown, %{reason: reason})
      {:stop, :normal, state}
    else
      {:noreply, state}
    end
  end

  def handle_info(
        {:DOWN, reference, :process, _pid, _reason},
        %{graph_task: %{monitor: reference}} = state
      ) do
    receiver_event(state, :result_unknown, %{reason: :graph_crash})
    {:stop, :normal, state}
  end

  def handle_info(:renew_lease, %{claim: %{run_uid: run_uid, attempt: attempt}} = state) do
    case state.run_client.renew_resume_lease(state.project_uid, run_uid, attempt) do
      :ok ->
        Process.send_after(self(), :renew_lease, state.lease_interval)
        {:noreply, state}

      {:error, :conflict} ->
        receiver_event(state, :lease_lost, %{})
        {:stop, :normal, state}

      {:error, reason} when reason in [:forbidden, :unauthorized, :expired_token] ->
        receiver_event(state, :result_unknown, %{reason: reason})
        {:stop, :normal, state}

      {:error, _reason} ->
        Process.send_after(self(), :renew_lease, max(div(state.lease_interval, 6), 1_000))
        {:noreply, state}
    end
  end

  def handle_info(_message, state), do: {:noreply, state}

  @impl true
  def terminate(_reason, %{graph_task: %{pid: pid}, graph_supervisor: supervisor}) do
    Task.Supervisor.terminate_child(supervisor, pid)
    :ok
  end

  def terminate(_reason, _state), do: :ok

  defp publish_persisted_result(state, persisted) do
    original = persisted.original_message
    receiver_event(state, :buffer, %{uid: original["uid"], message: original["message"]})
    receiver_event(state, :end, %{uid: original["uid"], status: :success})

    if resumed = persisted.resumed_message do
      receiver_event(state, :start, %{ai_message: resumed})
      receiver_event(state, :buffer, %{uid: resumed["uid"], message: resumed["message"]})
      receiver_event(state, :end, %{uid: resumed["uid"], status: :success})
    end
  end

  defp current_task?(%{graph_task: %{pid: pid}}, pid), do: true
  defp current_task?(_state, _pid), do: false

  defp receiver_event(state, event, data) do
    send(
      state.receiver,
      {:board_chat_resume_event, state.project_uid, state.command["message_uid"], event, data}
    )
  end
end
