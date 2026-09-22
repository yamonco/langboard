defmodule LangboardSocket.EditorResumeWorker do
  @moduledoc false
  use GenServer

  alias LangboardSocket.EditorRunClient
  alias LangboardSocket.GraphResumeClient

  def child_spec(options) do
    %{
      id: {__MODULE__, Keyword.fetch!(options, :approval_uid)},
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
      approval_uid: Keyword.fetch!(options, :approval_uid),
      decision: Keyword.fetch!(options, :decision),
      receiver: Keyword.fetch!(options, :receiver),
      run_client: Keyword.get(options, :run_client, EditorRunClient),
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
    case state.run_client.claim_resume(
           state.token,
           state.project_uid,
           state.approval_uid,
           state.decision
         ) do
      {:ok, claim} ->
        start_graph_resume(%{state | claim: claim})

      {:error, reason} ->
        receiver_event(state, :claim_failed, reason)
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
        receiver_event(state, :result_unknown, :capacity)
        {:stop, :normal, state}
    end
  end

  @impl true
  def handle_info({:graph_result, task_pid, {:ok, graph_result}}, state) do
    if current_task?(state, task_pid) do
      Process.demonitor(state.graph_task.monitor, [:flush])
      claim = state.claim

      case state.run_client.complete_resume(
             claim.run_uid,
             claim.attempt,
             claim.thread_id,
             claim.session_id,
             graph_result
           ) do
        {:ok, persisted} ->
          receiver_event(state, :completed, persisted)
          {:stop, :normal, state}

        {:error, reason} ->
          receiver_event(state, :result_unknown, reason)
          {:stop, :normal, state}
      end
    else
      {:noreply, state}
    end
  end

  def handle_info({:graph_result, task_pid, {:error, reason}}, state) do
    if current_task?(state, task_pid) do
      Process.demonitor(state.graph_task.monitor, [:flush])
      receiver_event(state, :result_unknown, reason)
      {:stop, :normal, state}
    else
      {:noreply, state}
    end
  end

  def handle_info(
        {:DOWN, reference, :process, _pid, _reason},
        %{graph_task: %{monitor: reference}} = state
      ) do
    receiver_event(state, :result_unknown, :graph_crash)
    {:stop, :normal, state}
  end

  def handle_info(:renew_lease, %{claim: %{run_uid: run_uid, attempt: attempt}} = state) do
    case state.run_client.renew_resume_lease(run_uid, attempt) do
      :ok ->
        Process.send_after(self(), :renew_lease, state.lease_interval)
        {:noreply, state}

      {:error, :conflict} ->
        receiver_event(state, :lease_lost, :conflict)
        {:stop, :normal, state}

      {:error, :forbidden} ->
        fail_revoked_resume(state)

      {:error, reason} when reason in [:unauthorized, :expired_token] ->
        receiver_event(state, :result_unknown, reason)
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

  defp current_task?(%{graph_task: %{pid: pid}}, pid), do: true
  defp current_task?(_state, _pid), do: false

  defp fail_revoked_resume(%{claim: claim} = state) do
    case state.run_client.finish(
           claim.run_uid,
           claim.attempt,
           "failed",
           "",
           "Editor AI scope access was revoked"
         ) do
      :ok -> receiver_event(state, :result_unknown, :forbidden)
      {:error, :conflict} -> receiver_event(state, :lease_lost, :conflict)
      {:error, reason} -> receiver_event(state, :result_unknown, reason)
    end

    {:stop, :normal, state}
  end

  defp receiver_event(state, event, data) do
    if is_pid(state.receiver) do
      send(state.receiver, {:editor_resume_event, state.approval_uid, event, data})
    end
  end
end
