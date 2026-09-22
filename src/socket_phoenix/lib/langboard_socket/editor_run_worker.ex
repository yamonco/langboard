defmodule LangboardSocket.EditorRunWorker do
  @moduledoc false
  use GenServer

  alias LangboardSocket.EditorRunClient
  alias LangboardSocket.GraphStreamClient

  def child_spec(options) do
    task_id = options |> Keyword.fetch!(:command) |> Map.fetch!("task_id")

    %{
      id: {__MODULE__, task_id},
      start: {__MODULE__, :start_link, [options]},
      restart: :temporary
    }
  end

  def start_link(options) when is_list(options), do: GenServer.start_link(__MODULE__, options)

  @impl true
  def init(options) do
    graph_timeout = Application.fetch_env!(:langboard_socket, :graph_timeout_ms)
    recovery_run = Keyword.get(options, :recovery_run)

    state = %{
      token: Keyword.fetch!(options, :token),
      command: Keyword.fetch!(options, :command),
      receiver: Keyword.fetch!(options, :receiver),
      run_client: Keyword.get(options, :run_client, EditorRunClient),
      graph_client: Keyword.get(options, :graph_client, GraphStreamClient),
      graph_supervisor:
        Keyword.get(options, :graph_supervisor, LangboardSocket.BoardChatGraphTaskSupervisor),
      max_queue: Application.fetch_env!(:langboard_socket, :socket_max_outbound_queue_messages),
      max_output: Application.fetch_env!(:langboard_socket, :graph_stream_max_chunk_bytes),
      lease_interval: max(div(graph_timeout, 4), 1_000),
      run_uid: if(recovery_run, do: recovery_run["run_uid"], else: nil),
      attempt: nil,
      graph_task: nil,
      content: "",
      ended: false,
      interrupt: nil,
      aborted: false
    }

    {:ok, state, {:continue, if(recovery_run, do: :recover, else: :accept)}}
  end

  @impl true
  def handle_continue(:recover, state) do
    send(self(), :start)
    {:noreply, state}
  end

  def handle_continue(:accept, state) do
    case state.run_client.accept(state.token, state.command) do
      {:ok, %{"run_uid" => run_uid, "status" => "accepted"}} ->
        send(self(), :start)
        {:noreply, %{state | run_uid: run_uid}}

      {:ok, _already_started} ->
        receiver_event(state, :failed, %{reason: :already_started})
        {:stop, :normal, state}

      {:error, reason} ->
        receiver_event(state, :failed, %{reason: reason})
        {:stop, :normal, state}
    end
  end

  @impl true
  def handle_info({:editor_abort_requested, task_id}, %{command: %{"task_id" => task_id}} = state) do
    case state.run_uid do
      nil ->
        {:noreply, %{state | aborted: true}}

      _run_uid ->
        cancel_run(state)
    end
  end

  def handle_info(:start, %{aborted: true} = state), do: cancel_run(state)

  def handle_info(:start, state) do
    case state.run_client.start(state.run_uid) do
      {:ok, %{attempt: attempt, graph_request: request}} ->
        owner = self()
        started = %{state | attempt: attempt}

        stream = fn -> stream_graph(state, request, owner) end

        case Task.Supervisor.start_child(state.graph_supervisor, stream) do
          {:ok, pid} ->
            monitor = Process.monitor(pid)
            receiver_event(started, :start, %{})
            Process.send_after(self(), :renew_lease, state.lease_interval)
            {:noreply, %{started | graph_task: %{pid: pid, monitor: monitor}}}

          {:error, _reason} ->
            finish_run(started, "failed", "", "Graph worker capacity is unavailable")
        end

      {:error, reason} ->
        receiver_event(state, :failed, %{reason: reason})
        {:stop, :normal, state}
    end
  end

  def handle_info(
        {:graph_event, task_pid, {:token, chunk}},
        %{graph_task: %{pid: task_pid}} = state
      )
      when is_binary(chunk) do
    {content, delta} = merge_chunk(state.content, chunk)

    if byte_size(content) > state.max_output do
      finish_run(state, "failed", "", "Editor AI output exceeded the configured limit")
    else
      if delta != "" and state.command["kind"] == "editor_chat" do
        receiver_event(state, :buffer, %{message: delta})
      end

      {:noreply, %{state | content: content}}
    end
  end

  def handle_info(
        {:graph_event, task_pid, {:interrupt, interrupt}},
        %{graph_task: %{pid: task_pid}} = state
      ) do
    if is_map(interrupt) and state.interrupt == nil do
      {:noreply, %{state | interrupt: interrupt}}
    else
      {:noreply, %{state | ended: :invalid_interrupt}}
    end
  end

  def handle_info(
        {:graph_event, task_pid, {:error, _reason}},
        %{graph_task: %{pid: task_pid}} = state
      ) do
    {:noreply, %{state | ended: :graph_error}}
  end

  def handle_info({:graph_event, task_pid, :end}, %{graph_task: %{pid: task_pid}} = state) do
    ended = if state.ended in [:graph_error, :invalid_interrupt], do: state.ended, else: true
    {:noreply, %{state | ended: ended}}
  end

  def handle_info({:graph_result, task_pid, result}, %{graph_task: %{pid: task_pid}} = state) do
    Process.demonitor(state.graph_task.monitor, [:flush])

    case {result, state.ended, state.interrupt} do
      {:ok, true, nil} ->
        finish_run(state, "completed", state.content, nil)

      {:ok, true, interrupt} when is_map(interrupt) ->
        pause_run(state, interrupt)

      _ ->
        finish_run(state, "failed", "", "Graph streaming failed")
    end
  end

  def handle_info(
        {:DOWN, reference, :process, _pid, _reason},
        %{graph_task: %{monitor: reference}} = state
      ) do
    finish_run(state, "failed", "", "Graph worker exited before completion")
  end

  def handle_info(:renew_lease, %{attempt: attempt} = state) when is_integer(attempt) do
    case state.run_client.renew_lease(state.run_uid, attempt) do
      :ok ->
        Process.send_after(self(), :renew_lease, state.lease_interval)
        {:noreply, state}

      {:error, :conflict} ->
        receiver_event(state, :failed, %{reason: :lease_lost})
        {:stop, :normal, state}

      {:error, :forbidden} ->
        finish_run(state, "failed", "", "Editor AI scope access was revoked")

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

  defp stream_graph(state, request, owner) do
    result =
      state.graph_client.stream(request["session_id"], request, fn event ->
        receiver_queue =
          if is_pid(state.receiver),
            do: Process.info(state.receiver, :message_queue_len),
            else: nil

        case {Process.info(owner, :message_queue_len), receiver_queue} do
          {{:message_queue_len, owner_count}, {:message_queue_len, receiver_count}}
          when owner_count < state.max_queue and receiver_count < state.max_queue ->
            send(owner, {:graph_event, self(), event})
            :ok

          {{:message_queue_len, owner_count}, nil} when owner_count < state.max_queue ->
            send(owner, {:graph_event, self(), event})
            :ok

          _ ->
            {:error, :backpressure}
        end
      end)

    send(owner, {:graph_result, self(), result})
  end

  defp cancel_run(state) do
    case state.run_client.cancel(
           state.token,
           state.command["project_uid"],
           state.command["kind"],
           state.command["task_id"]
         ) do
      {:ok, _run_uid} -> receiver_event(state, :cancelled, %{})
      {:error, reason} -> receiver_event(state, :failed, %{reason: reason})
    end

    {:stop, :normal, state}
  end

  defp finish_run(state, status, content, error) do
    result = state.run_client.finish(state.run_uid, state.attempt, status, content, error)

    case result do
      :ok -> receiver_event(state, :end, %{status: status, message: content})
      {:error, reason} -> receiver_event(state, :failed, %{reason: reason})
    end

    {:stop, :normal, state}
  end

  defp pause_run(state, interrupt) do
    case state.run_client.pause(state.run_uid, state.attempt, state.content, interrupt) do
      {:ok, _saved_interrupt} ->
        receiver_event(state, :end, %{status: "awaiting_approval", message: state.content})
        {:stop, :normal, state}

      {:error, :conflict} ->
        receiver_event(state, :failed, %{reason: :lease_lost})
        {:stop, :normal, state}

      {:error, _reason} ->
        finish_run(state, "failed", "", "Graph interruption could not be persisted")
    end
  end

  defp merge_chunk(previous, chunk) do
    if String.starts_with?(chunk, previous) do
      {chunk, binary_part(chunk, byte_size(previous), byte_size(chunk) - byte_size(previous))}
    else
      {previous <> chunk, chunk}
    end
  end

  defp receiver_event(state, event, data) do
    if is_pid(state.receiver) do
      send(state.receiver, {:editor_run_event, state.command["task_id"], event, data})
    end
  end
end
