defmodule LangboardSocket.BoardChatRunWorker do
  @moduledoc false
  use GenServer

  alias LangboardSocket.BoardChatActiveDocuments
  alias LangboardSocket.BoardChatRunClient
  alias LangboardSocket.GraphStreamClient
  alias LangboardSocket.LangflowStreamClient

  def cancel_topic(run_uid) when is_binary(run_uid), do: "board_chat_run:#{run_uid}"

  def child_spec(options) do
    run_uid =
      case Keyword.get(options, :recovery_run) do
        nil -> options |> Keyword.fetch!(:command) |> Map.fetch!("task_id")
        recovery_run -> Map.fetch!(recovery_run, "run_uid")
      end

    %{
      id: {__MODULE__, run_uid},
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
      token: Keyword.get(options, :token),
      project_uid: Keyword.fetch!(options, :project_uid),
      command: Keyword.get(options, :command),
      recovery_run: recovery_run,
      run_uid: if(recovery_run, do: recovery_run["run_uid"], else: nil),
      active_documents_client:
        Keyword.get(options, :active_documents_client, BoardChatActiveDocuments),
      receiver: Keyword.get(options, :receiver),
      run_client: Keyword.get(options, :run_client, BoardChatRunClient),
      graph_client: Keyword.get(options, :graph_client, GraphStreamClient),
      langflow_client: Keyword.get(options, :langflow_client, LangflowStreamClient),
      graph_supervisor:
        Keyword.get(options, :graph_supervisor, LangboardSocket.BoardChatGraphTaskSupervisor),
      max_queue: Application.fetch_env!(:langboard_socket, :socket_max_outbound_queue_messages),
      lease_interval: max(div(graph_timeout, 4), 1_000),
      attempt: nil,
      ai_message_uid: nil,
      graph_task: nil,
      content: "",
      interrupt: nil,
      stream_label: "Graph",
      ended: false
    }

    {:ok, state, {:continue, if(recovery_run, do: :recover, else: :accept)}}
  end

  def handle_continue(:recover, state) do
    :ok = Phoenix.PubSub.subscribe(LangboardSocket.PubSub, cancel_topic(state.run_uid))
    {:noreply, state, {:continue, :start}}
  end

  @impl true
  def handle_continue(:accept, state) do
    case state.run_client.accept(state.token, state.project_uid, state.command) do
      {:ok, %{"run_uid" => run_uid, "status" => "accepted"} = accepted} ->
        :ok = Phoenix.PubSub.subscribe(LangboardSocket.PubSub, cancel_topic(run_uid))

        receiver_event(state, :accepted, %{
          run_uid: run_uid,
          session: accepted["session"],
          user_message: accepted["user_message"],
          accepted: accepted["accepted"]
        })

        {:noreply, %{state | run_uid: run_uid}, {:continue, :start}}

      {:ok, %{"run_uid" => run_uid, "status" => status} = accepted} ->
        receiver_event(state, :already_started, %{
          run_uid: run_uid,
          status: status,
          session: accepted["session"],
          user_message: accepted["user_message"]
        })

        {:stop, :normal, state}

      {:error, reason} ->
        receiver_event(state, :accept_failed, %{reason: reason})
        {:stop, :normal, state}
    end
  end

  def handle_continue(:start, state) do
    scope = state.recovery_run || state.command

    case state.active_documents_client.collect(
           state.project_uid,
           Map.get(scope, "scope_table", "project"),
           Map.get(scope, "scope_uid")
         ) do
      {:ok, active_documents} ->
        start_run(state, active_documents)

      {:error, reason} ->
        receiver_event(state, :start_failed, %{reason: reason})
        {:stop, :normal, state}
    end
  end

  defp start_run(state, active_documents) do
    start_result =
      if state.recovery_run do
        state.run_client.recover_start(state.project_uid, state.run_uid, active_documents)
      else
        state.run_client.start(state.token, state.project_uid, state.run_uid, active_documents)
      end

    case start_result do
      {:ok, %{attempt: attempt, graph_request: request, ai_message: ai_message}} ->
        start_stream(state, attempt, request, ai_message, state.graph_client, "Graph")

      {:ok, %{attempt: attempt, langflow_request: request, ai_message: ai_message}} ->
        start_stream(state, attempt, request, ai_message, state.langflow_client, "Langflow")

      {:error, :conflict} when not is_nil(state.recovery_run) ->
        {:stop, :normal, state}

      {:error, reason} ->
        receiver_event(state, :start_failed, %{reason: reason})
        {:stop, :normal, state}
    end
  end

  defp start_stream(state, attempt, request, ai_message, client, label) do
    receiver_event(state, :start, %{ai_message: ai_message})
    owner = self()
    receiver = state.receiver
    max_queue = state.max_queue

    started = %{
      state
      | attempt: attempt,
        ai_message_uid: ai_message["uid"],
        stream_label: label
    }

    case Task.Supervisor.start_child(state.graph_supervisor, fn ->
           result =
             client.stream(
               request["session_id"],
               request,
               &forward_stream_event(owner, receiver, max_queue, &1)
             )

           send(owner, {:graph_result, self(), result})
         end) do
      {:ok, pid} ->
        monitor = Process.monitor(pid)
        Process.send_after(self(), :renew_lease, state.lease_interval)
        {:noreply, %{started | graph_task: %{pid: pid, monitor: monitor}}}

      {:error, _reason} ->
        finish(started, "failed", "", "#{label} worker capacity is unavailable", :failed)
    end
  end

  defp forward_stream_event(owner, receiver, max_queue, event) do
    receiver_queue =
      if is_pid(receiver),
        do: Process.info(receiver, :message_queue_len),
        else: {:message_queue_len, 0}

    case {Process.info(owner, :message_queue_len), receiver_queue} do
      {{:message_queue_len, owner_count}, {:message_queue_len, receiver_count}}
      when owner_count < max_queue and receiver_count < max_queue ->
        send(owner, {:graph_event, self(), event})
        :ok

      {{:message_queue_len, owner_count}, nil} when owner_count < max_queue ->
        send(owner, {:graph_event, self(), event})
        :ok

      _ ->
        {:error, :backpressure}
    end
  end

  @impl true
  def handle_info({:board_chat_run_cancelled, run_uid}, %{run_uid: run_uid} = state) do
    receiver_event(state, :cancelled, %{})
    {:stop, :normal, state}
  end

  def handle_info({:graph_event, task_pid, {:token, content}}, state)
      when is_binary(content) do
    if current_task?(state, task_pid) do
      receiver_event(state, :buffer, %{uid: state.ai_message_uid, message: %{content: content}})
      {:noreply, %{state | content: content}}
    else
      {:noreply, state}
    end
  end

  def handle_info({:graph_event, task_pid, {:interrupt, interrupt}}, state)
      when is_map(interrupt) do
    if current_task?(state, task_pid) do
      if state.interrupt == nil do
        {:noreply, %{state | interrupt: interrupt}}
      else
        {:noreply, %{state | ended: :multiple_interrupts}}
      end
    else
      {:noreply, state}
    end
  end

  def handle_info({:graph_event, task_pid, {:error, _reason}}, state) do
    if current_task?(state, task_pid) do
      {:noreply, %{state | ended: :graph_error}}
    else
      {:noreply, state}
    end
  end

  def handle_info({:graph_event, task_pid, :end}, state) do
    if current_task?(state, task_pid) do
      ended = if state.ended in [:multiple_interrupts, :graph_error], do: state.ended, else: true
      {:noreply, %{state | ended: ended}}
    else
      {:noreply, state}
    end
  end

  def handle_info({:graph_result, task_pid, result}, state) do
    if current_task?(state, task_pid) do
      Process.demonitor(state.graph_task.monitor, [:flush])

      case {result, state.ended, state.interrupt} do
        {:ok, true, interrupt} when is_map(interrupt) ->
          pause(state, interrupt)

        {:ok, true, nil} when state.content != "" ->
          finish(state, "completed", state.content, nil, :success)

        {_result, _ended, _interrupt} ->
          finish(state, "failed", "", "#{state.stream_label} streaming failed", :failed)
      end
    else
      {:noreply, state}
    end
  end

  def handle_info(
        {:DOWN, reference, :process, _pid, _reason},
        %{graph_task: %{monitor: reference}} = state
      ) do
    finish(state, "failed", "", "#{state.stream_label} worker exited before completion", :failed)
  end

  def handle_info(:renew_lease, %{attempt: attempt} = state) when is_integer(attempt) do
    case state.run_client.renew_lease(state.project_uid, state.run_uid, attempt) do
      :ok ->
        Process.send_after(self(), :renew_lease, state.lease_interval)
        {:noreply, state}

      {:error, :conflict} ->
        receiver_event(state, :lease_lost, %{})
        {:stop, :normal, state}

      {:error, reason} when reason in [:forbidden, :unauthorized, :expired_token] ->
        finish(state, "failed", "", "Board chat access was revoked", :failed)

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

  defp finish(state, status, content, error, event_status) do
    result =
      state.run_client.finish(
        state.project_uid,
        state.run_uid,
        state.attempt,
        status,
        content,
        error
      )

    case result do
      :ok ->
        receiver_event(state, :end, %{uid: state.ai_message_uid, status: event_status})

      {:error, :conflict} ->
        receiver_event(state, :lease_lost, %{})

      {:error, _reason} ->
        receiver_event(state, :result_unknown, %{})
    end

    {:stop, :normal, state}
  end

  defp pause(state, interrupt) do
    case state.run_client.pause(
           state.project_uid,
           state.run_uid,
           state.attempt,
           state.content,
           interrupt
         ) do
      {:ok, persisted_interrupt} ->
        receiver_event(state, :buffer, %{
          uid: state.ai_message_uid,
          interrupt: persisted_interrupt
        })

        receiver_event(state, :end, %{uid: state.ai_message_uid, status: :success})
        {:stop, :normal, state}

      {:error, :conflict} ->
        receiver_event(state, :lease_lost, %{})
        {:stop, :normal, state}

      {:error, _reason} ->
        finish_result =
          state.run_client.finish(
            state.project_uid,
            state.run_uid,
            state.attempt,
            "failed",
            "",
            "Graph interruption could not be persisted"
          )

        case finish_result do
          :ok -> receiver_event(state, :end, %{uid: state.ai_message_uid, status: :failed})
          {:error, :conflict} -> receiver_event(state, :lease_lost, %{})
          {:error, _reason} -> receiver_event(state, :result_unknown, %{})
        end

        {:stop, :normal, state}
    end
  end

  defp current_task?(%{graph_task: %{pid: pid}}, pid), do: true
  defp current_task?(_state, _pid), do: false

  defp receiver_event(%{receiver: nil}, _event, _data), do: :ok

  defp receiver_event(%{receiver: receiver, command: command}, event, data) do
    send(receiver, {:board_chat_run_event, command["task_id"], event, data})
  end
end
