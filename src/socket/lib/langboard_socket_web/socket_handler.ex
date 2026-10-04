defmodule LangboardSocketWeb.SocketHandler do
  @moduledoc false
  @behaviour WebSock

  import LangboardSocketWeb.SocketHandler.Outbound,
    only: [push_payload: 2, push_frame: 2, push_frames: 2]

  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocketWeb.SocketHandler.BoardChat.Command, as: BoardChatCommand
  alias LangboardSocketWeb.SocketHandler.BoardChat.Result, as: BoardChatResult
  alias LangboardSocketWeb.SocketHandler.BoardQuery
  alias LangboardSocketWeb.SocketHandler.Editor.Command, as: EditorCommand
  alias LangboardSocketWeb.SocketHandler.Editor.Result, as: EditorResult
  alias LangboardSocketWeb.SocketHandler.NotificationCommand
  alias LangboardSocketWeb.SocketHandler.OllamaCommand
  alias LangboardSocketWeb.SocketHandler.State
  alias LangboardSocketWeb.SocketHandler.Subscriptions
  alias LangboardSocketWeb.Telemetry

  @subscribe_event Contract.event!("subscribe")
  @unsubscribe_event Contract.event!("unsubscribe")
  @bot_status_event Contract.event!("board_bot_status_map")
  @chat_available_event Contract.event!("board_chat_available")
  @chat_send_event Contract.event!("board_chat_send")
  @chat_cancel_event Contract.event!("board_chat_cancel")
  @chat_resume_event Contract.event!("board_chat_resume")
  @notification_topic Contract.topic!("none")
  @notification_topic_id Contract.topic_id!("none")
  @ollama_topic Contract.topic!("ollama_manager")
  @ollama_topic_id Contract.topic_id!("global")
  @ollama_actions %{
    Contract.event!("ollama_copy_model") => :copy,
    Contract.event!("ollama_delete_model") => :delete,
    Contract.event!("ollama_pull_model") => :pull
  }
  @notification_actions %{
    Contract.event!("notification_read") => :read,
    Contract.event!("notification_read_all") => :read_all,
    Contract.event!("notification_delete") => :delete,
    Contract.event!("notification_delete_all") => :delete_all
  }

  @impl true
  def init({{:ok, user_uid}, token, max_payload, ping_interval, max_outbound_queue}) do
    bootstrap_subscriptions = [
      {Contract.topic!("global"), Contract.topic_id!("global")},
      {Contract.topic!("user_private"), user_uid}
    ]

    Enum.each(bootstrap_subscriptions, &Subscriptions.subscribe/1)
    schedule_ping(ping_interval)
    Telemetry.emit_connection_change(1)
    Telemetry.emit_subscription_change(length(bootstrap_subscriptions))

    messages =
      Enum.map(bootstrap_subscriptions, fn {topic, topic_id} ->
        Subscriptions.encode_message(Contract.event!("subscribed"), topic, [topic_id])
      end)

    state = %State{
      authorization_client: Application.fetch_env!(:langboard_socket, :authorization_client),
      authorization_token: token,
      max_payload: max_payload,
      max_outbound_queue: max_outbound_queue,
      pending_notifications: %{},
      pending_ollama: %{},
      pending_bot_status: %{},
      pending_chat_availability: %{},
      pending_chat_sends: %{},
      pending_chat_cancels: %{},
      pending_chat_resumes: %{},
      pending_editor_runs: %{},
      pending_editor_cancels: %{},
      pending_editor_statuses: %{},
      pending_editor_resumes: %{},
      ping_interval: ping_interval,
      subscriptions: MapSet.new(bootstrap_subscriptions)
    }

    case LangboardSocket.RuntimeStatus.register_socket() do
      :ok -> push_frames(messages, state)
      {:error, :draining} -> {:stop, :normal, Contract.close_code!("service_restart"), state}
    end
  end

  def init({{:error, :unauthorized}, _token, max_payload, _ping_interval, _max_outbound_queue}) do
    {:stop, :normal, Contract.close_code!("unauthorized"), %{max_payload: max_payload}}
  end

  def init({{:error, :expired_token}, _token, max_payload, _ping_interval, _max_outbound_queue}) do
    {:stop, :normal, Contract.close_code!("expired_token"), %{max_payload: max_payload}}
  end

  def init({{:error, :unavailable}, _token, max_payload, _ping_interval, _max_outbound_queue}) do
    {:stop, :normal, Contract.close_code!("internal_error"), %{max_payload: max_payload}}
  end

  @impl true
  def handle_in({payload, opcode: opcode}, state) when opcode in [:text, :binary] do
    cond do
      byte_size(payload) > state.max_payload ->
        {:stop, :normal, Contract.close_code!("message_too_big"), state}

      payload == "" ->
        push_frame({:text, ""}, state)

      true ->
        handle_payload(Jason.decode(payload), state)
    end
  end

  @impl true
  def handle_info(:socket_drain, state),
    do: {:stop, :normal, Contract.close_code!("service_restart"), state}

  def handle_info({:socket_event, %{"topic" => topic, "topic_id" => topic_id} = payload}, state)
      when is_binary(topic) and is_binary(topic_id) do
    with true <- MapSet.member?(state.subscriptions, {topic, topic_id}),
         {:ok, accepted} <-
           state.authorization_client.authorize_subscriptions(
             state.authorization_token,
             topic,
             [topic_id]
           ) do
      if topic_id in accepted do
        push_payload(payload, state)
      else
        Subscriptions.revoke(topic, topic_id, state)
      end
    else
      false -> {:ok, state}
      {:error, reason} -> {:stop, :normal, Subscriptions.authorization_close_code(reason), state}
    end
  end

  def handle_info({:bot_status_map, topic_id, worker_pid, result}, state) do
    case Map.get(state.pending_bot_status, topic_id) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])

        BoardQuery.bot_status_result(
          topic_id,
          result,
          State.clear_pending_bot_status(state, topic_id)
        )

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:chat_availability, topic_id, worker_pid, result}, state) do
    case Map.get(state.pending_chat_availability, topic_id) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])

        BoardQuery.chat_availability_result(
          topic_id,
          result,
          State.clear_pending_chat_availability(state, topic_id)
        )

      _ ->
        {:ok, state}
    end
  end

  def handle_info(
        {:board_chat_resume_event, _topic_id, _source_uid, event, _data} = message,
        state
      )
      when event in [
             :finished,
             :start,
             :buffer,
             :end,
             :claim_failed,
             :result_unknown,
             :lease_lost
           ],
      do: BoardChatResult.resume_event(message, state)

  def handle_info({:editor_resume_event, _approval_uid, event, _data} = message, state)
      when event in [:completed, :claim_failed, :result_unknown, :lease_lost],
      do: EditorResult.result(message, state)

  def handle_info({:board_chat_run_event, _task_id, event, data} = message, state)
      when event in [
             :accepted,
             :already_started,
             :accept_failed,
             :start,
             :buffer,
             :end,
             :start_failed,
             :lease_lost,
             :result_unknown,
             :cancelled
           ] and is_map(data),
      do: BoardChatResult.run_event(message, state)

  def handle_info({:editor_run_event, _task_id, _event, data} = message, state)
      when is_map(data),
      do: EditorResult.result(message, state)

  def handle_info({:editor_status, _task_id, _worker_pid, _result} = message, state),
    do: EditorResult.result(message, state)

  def handle_info({:editor_cancel, _reference, _worker_pid, _task_id, _result} = message, state),
    do: EditorResult.result(message, state)

  def handle_info({:board_chat_cancel_result, _task_id, _worker_pid, _result} = message, state),
    do: BoardChatResult.cancel_result(message, state)

  def handle_info({:notification_command, reference, worker_pid, result}, state) do
    NotificationCommand.result(reference, worker_pid, result, state)
  end

  def handle_info({:ollama_command, reference, worker_pid, result}, state) do
    OllamaCommand.result(reference, worker_pid, result, state)
  end

  def handle_info({:DOWN, monitor_ref, :process, worker_pid, _reason} = message, state) do
    case BoardChatResult.down(message, state) do
      :unhandled ->
        case EditorResult.down(message, state) do
          :unhandled -> handle_command_down_without_editor_status(monitor_ref, worker_pid, state)
          result -> result
        end

      result ->
        result
    end
  end

  def handle_info(:ping, state) do
    case state.authorization_client.authenticate(state.authorization_token) do
      {:ok, _user_uid} ->
        schedule_ping(state.ping_interval)
        push_frame({:ping, ""}, state)

      {:error, reason} ->
        {:stop, :normal, Subscriptions.authorization_close_code(reason), state}
    end
  end

  def handle_info(_message, state), do: {:ok, state}

  defp handle_command_down_without_editor_status(monitor_ref, worker_pid, state) do
    pending =
      Enum.find_value(
        [
          :pending_bot_status,
          :pending_chat_availability,
          :pending_notifications,
          :pending_ollama
        ],
        fn field ->
          Enum.find_value(Map.fetch!(state, field), fn
            {key, {^worker_pid, ^monitor_ref}} -> {field, key}
            _task -> nil
          end)
        end
      )

    case pending do
      {:pending_bot_status, topic_id} ->
        BoardQuery.bot_status_result(
          topic_id,
          {:error, :unavailable},
          State.clear_pending_bot_status(state, topic_id)
        )

      {:pending_chat_availability, topic_id} ->
        BoardQuery.chat_availability_result(
          topic_id,
          {:error, :unavailable},
          State.clear_pending_chat_availability(state, topic_id)
        )

      {:pending_notifications, reference} ->
        NotificationCommand.failed(reference, state)

      {:pending_ollama, reference} ->
        OllamaCommand.failed(reference, state)

      nil ->
        {:ok, state}
    end
  end

  @impl true
  def terminate(_reason, %State{} = state) do
    Enum.each(state.pending_chat_sends, fn {_task_id,
                                            {_topic_id, _worker_pid, monitor_ref, _outcome}} ->
      Process.demonitor(monitor_ref, [:flush])
    end)

    Enum.each(state.pending_chat_cancels, fn {_task_id, {_topic_id, _worker_pid, monitor_ref}} ->
      Process.demonitor(monitor_ref, [:flush])
    end)

    Enum.each(state.pending_chat_resumes, fn {_uid,
                                              {_topic_id, _worker_pid, monitor_ref, _outcome}} ->
      Process.demonitor(monitor_ref, [:flush])
    end)

    :ok = EditorResult.detach(state)

    Enum.each(state.pending_bot_status, fn {_topic_id, {worker_pid, monitor_ref}} ->
      Process.demonitor(monitor_ref, [:flush])
      Task.Supervisor.terminate_child(LangboardSocket.CommandTaskSupervisor, worker_pid)
    end)

    Enum.each(state.pending_chat_availability, fn {_topic_id, {worker_pid, monitor_ref}} ->
      Process.demonitor(monitor_ref, [:flush])
      Task.Supervisor.terminate_child(LangboardSocket.CommandTaskSupervisor, worker_pid)
    end)

    Telemetry.emit_connection_change(-1)
    Telemetry.emit_subscription_change(-MapSet.size(state.subscriptions))
    :ok
  end

  def terminate(_reason, _state), do: :ok

  defp handle_payload({:ok, %{"event" => event, "topic" => topic} = payload}, state)
       when topic in [@notification_topic, @ollama_topic] and
              event not in [@subscribe_event, @unsubscribe_event] and
              not is_map_key(payload, "topic_id") do
    topic_id = if topic == @notification_topic, do: @notification_topic_id, else: @ollama_topic_id
    handle_payload({:ok, Map.put(payload, "topic_id", topic_id)}, state)
  end

  defp handle_payload({:ok, %{"event" => @subscribe_event} = payload}, state),
    do: Subscriptions.handle_subscribe(payload, state)

  defp handle_payload({:ok, %{"event" => @unsubscribe_event} = payload}, state),
    do: Subscriptions.handle_unsubscribe(payload, state)

  defp handle_payload({:ok, %{"event" => @bot_status_event} = payload}, state),
    do: BoardQuery.handle_bot_status(payload, state)

  defp handle_payload({:ok, %{"event" => @chat_available_event} = payload}, state),
    do: BoardQuery.handle_chat_availability(payload, state)

  defp handle_payload({:ok, %{"event" => event} = payload}, state)
       when event in [@chat_send_event, @chat_cancel_event, @chat_resume_event],
       do: BoardChatCommand.handle(event, payload, state)

  defp handle_payload({:ok, %{"event" => event} = payload}, state)
       when is_map_key(@notification_actions, event),
       do:
         NotificationCommand.handle(
           payload,
           Map.fetch!(@notification_actions, event),
           state,
           State.command_capacity_exhausted?(state)
         )

  defp handle_payload({:ok, %{"event" => event} = payload}, state)
       when is_map_key(@ollama_actions, event),
       do:
         OllamaCommand.handle(
           payload,
           Map.fetch!(@ollama_actions, event),
           state,
           State.command_capacity_exhausted?(state)
         )

  defp handle_payload({:ok, %{"event" => event} = payload}, state),
    do: EditorCommand.handle(event, payload, state, State.command_capacity_exhausted?(state))

  defp handle_payload(_result, state), do: {:ok, state}

  defp schedule_ping(interval), do: Process.send_after(self(), :ping, interval)
end
