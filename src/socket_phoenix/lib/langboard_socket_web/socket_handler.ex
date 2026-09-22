defmodule LangboardSocketWeb.SocketHandler do
  @moduledoc false
  @behaviour WebSock

  alias LangboardSocket.BoardChatResumeWorker
  alias LangboardSocket.BoardChatRunClient
  alias LangboardSocket.BoardChatRunWorker
  alias LangboardSocket.EditorResumeWorker
  alias LangboardSocket.EditorRunClient
  alias LangboardSocket.EditorRunWorker
  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocket.SubscriptionTopic
  alias LangboardSocketWeb.Telemetry

  @board_topic Contract.topic!("board")
  @subscribe_event Contract.event!("subscribe")
  @unsubscribe_event Contract.event!("unsubscribe")
  @bot_status_event Contract.event!("board_bot_status_map")
  @chat_available_event Contract.event!("board_chat_available")
  @chat_send_event Contract.event!("board_chat_send")
  @chat_session_event Contract.event!("board_chat_session")
  @chat_sent_event Contract.event!("board_chat_sent")
  @chat_send_failed_event Contract.event!("board_chat_send_failed")
  @chat_cancel_event Contract.event!("board_chat_cancel")
  @task_aborted_event Contract.event!("task_aborted")
  @chat_resume_event Contract.event!("board_chat_resume")
  @chat_stream_event Contract.event!("board_chat_stream")
  @editor_status_event Contract.event!("editor_ai_status")
  @editor_status_result_event Contract.event!("editor_ai_status_result")
  @editor_approval_resume_event Contract.event!("editor_approval_resume")
  @editor_approval_resume_result_event Contract.event!("editor_approval_resume_result")
  @notification_topic Contract.topic!("none")
  @notification_topic_id Contract.topic_id!("none")
  @ollama_topic Contract.topic!("ollama_manager")
  @ollama_topic_id Contract.topic_id!("global")
  @ollama_actions %{
    Contract.event!("ollama_copy_model") => :copy,
    Contract.event!("ollama_delete_model") => :delete,
    Contract.event!("ollama_pull_model") => :pull
  }
  @short_uid_length Contract.short_uid_length!()
  @max_topic_ids Contract.protocol_limit!("max_topic_ids")
  @max_topic_id_bytes Contract.protocol_limit!("max_topic_id_bytes")
  @task_id_pattern ~r/\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\z/
  @editor_send_commands %{
    Contract.event!("editor_card_chat_send") => %{
      kind: "editor_chat",
      scope_field: "card_uid",
      document_type: "card",
      output: Contract.event!("editor_card_chat_stream")
    },
    Contract.event!("editor_card_copilot_send") => %{
      kind: "editor_copilot",
      scope_field: "card_uid",
      document_type: "card",
      output: Contract.event!("editor_card_copilot_receive")
    },
    Contract.event!("editor_wiki_chat_send") => %{
      kind: "editor_chat",
      scope_field: "wiki_uid",
      document_type: "wiki",
      output: Contract.event!("editor_wiki_chat_stream")
    },
    Contract.event!("editor_wiki_copilot_send") => %{
      kind: "editor_copilot",
      scope_field: "wiki_uid",
      document_type: "wiki",
      output: Contract.event!("editor_wiki_copilot_receive")
    }
  }
  @editor_abort_commands %{
    Contract.event!("editor_card_chat_abort") => Contract.event!("editor_card_chat_send"),
    Contract.event!("editor_card_copilot_abort") => Contract.event!("editor_card_copilot_send"),
    Contract.event!("editor_wiki_chat_abort") => Contract.event!("editor_wiki_chat_send"),
    Contract.event!("editor_wiki_copilot_abort") => Contract.event!("editor_wiki_copilot_send")
  }
  @editor_events [@editor_status_event, @editor_approval_resume_event] ++
                   Map.keys(@editor_send_commands) ++ Map.keys(@editor_abort_commands)
  @notification_actions %{
    Contract.event!("notification_read") => :read,
    Contract.event!("notification_read_all") => :read_all,
    Contract.event!("notification_delete") => :delete,
    Contract.event!("notification_delete_all") => :delete_all
  }

  defmodule State do
    @moduledoc false

    @derive {Inspect,
             only: [
               :max_payload,
               :max_outbound_queue,
               :ping_interval,
               :subscriptions,
               :authorization_client
             ]}
    @enforce_keys [
      :authorization_client,
      :authorization_token,
      :max_payload,
      :max_outbound_queue,
      :pending_notifications,
      :pending_ollama,
      :pending_bot_status,
      :pending_chat_availability,
      :pending_chat_sends,
      :pending_chat_cancels,
      :pending_chat_resumes,
      :pending_editor_runs,
      :pending_editor_cancels,
      :pending_editor_statuses,
      :pending_editor_resumes,
      :ping_interval,
      :subscriptions
    ]
    defstruct @enforce_keys
  end

  @impl true
  def init({{:ok, user_uid}, token, max_payload, ping_interval, max_outbound_queue}) do
    bootstrap_subscriptions = [
      {Contract.topic!("global"), Contract.topic_id!("global")},
      {Contract.topic!("user_private"), user_uid}
    ]

    Enum.each(bootstrap_subscriptions, &subscribe/1)
    schedule_ping(ping_interval)
    Telemetry.emit_connection_change(1)
    Telemetry.emit_subscription_change(length(bootstrap_subscriptions))

    messages =
      Enum.map(bootstrap_subscriptions, fn {topic, topic_id} ->
        encode_message(Contract.event!("subscribed"), topic, [topic_id])
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
        revoke_subscription(topic, topic_id, state)
      end
    else
      false -> {:ok, state}
      {:error, reason} -> {:stop, :normal, authorization_close_code(reason), state}
    end
  end

  def handle_info({:bot_status_map, topic_id, worker_pid, result}, state) do
    case Map.get(state.pending_bot_status, topic_id) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])
        finish_bot_status_map(topic_id, result, clear_pending_bot_status(state, topic_id))

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:chat_availability, topic_id, worker_pid, result}, state) do
    case Map.get(state.pending_chat_availability, topic_id) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])

        finish_chat_availability(
          topic_id,
          result,
          clear_pending_chat_availability(state, topic_id)
        )

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:board_chat_resume_event, topic_id, source_uid, :finished, _data}, state) do
    case Map.get(state.pending_chat_resumes, source_uid) do
      {^topic_id, worker_pid, monitor_ref, _outcome_received} ->
        {:ok,
         %{
           state
           | pending_chat_resumes:
               Map.put(state.pending_chat_resumes, source_uid, {
                 topic_id,
                 worker_pid,
                 monitor_ref,
                 true
               })
         }}

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:board_chat_resume_event, topic_id, source_uid, event, data}, state)
      when event in [:start, :buffer, :end, :claim_failed, :result_unknown, :lease_lost] do
    with true <-
           match?(
             {^topic_id, _worker_pid, _monitor_ref, _outcome_received},
             Map.get(state.pending_chat_resumes, source_uid)
           ) and
             MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         :ok <- authorize_board_command(topic_id, state) do
      next_state = mark_resume_outcome(state, source_uid, event)

      {stream_event, stream_data} =
        case event do
          event when event in [:start, :buffer, :end] ->
            {event, data}

          _ ->
            {:buffer, %{uid: source_uid, resume_error_code: resume_error_code(data)}}
        end

      push_payload(
        %{
          event: "#{@chat_stream_event}:#{stream_event}",
          topic: @board_topic,
          topic_id: topic_id,
          data: stream_data
        },
        next_state
      )
    else
      false -> {:ok, state}
      {:error, close_code} -> {:stop, :normal, close_code, state}
    end
  end

  def handle_info({:editor_resume_event, approval_uid, event, data}, state)
      when event in [:completed, :claim_failed, :result_unknown, :lease_lost] do
    case Map.get(state.pending_editor_resumes, approval_uid) do
      %{outcome: false} = pending ->
        next_state = %{
          state
          | pending_editor_resumes:
              Map.put(state.pending_editor_resumes, approval_uid, %{pending | outcome: true})
        }

        payload =
          case event do
            :completed ->
              %{approval_uid: approval_uid, status: data.status, output_text: data.output_text}

            _ ->
              %{
                approval_uid: approval_uid,
                status: Atom.to_string(event),
                error_code: editor_resume_error_code(data)
              }
          end

        push_payload(
          %{
            event: @editor_approval_resume_result_event,
            topic: @notification_topic,
            topic_id: @notification_topic_id,
            data: payload
          },
          next_state
        )

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:board_chat_run_event, task_id, event, data}, state)
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
           ] and is_map(data) do
    case Map.get(state.pending_chat_sends, task_id) do
      {_topic_id, _worker_pid, _monitor_ref, true} when event != :accepted ->
        {:ok, state}

      {topic_id, _worker_pid, _monitor_ref, _outcome_received} ->
        with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
             :ok <- authorize_board_command(topic_id, state) do
          next_state = mark_send_outcome(state, task_id, event)
          forward_chat_send_event(topic_id, task_id, event, data, next_state)
        else
          false -> {:ok, state}
          {:error, close_code} -> {:stop, :normal, close_code, state}
        end

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:editor_run_event, task_id, event, data}, state) when is_map(data) do
    case Map.get(state.pending_editor_runs, task_id) do
      %{outcome: false} = pending ->
        terminal = event in [:end, :failed, :cancelled]
        next_pending = if terminal, do: %{pending | outcome: true}, else: pending

        next_state = %{
          state
          | pending_editor_runs: Map.put(state.pending_editor_runs, task_id, next_pending)
        }

        forward_editor_run_event(task_id, event, data, pending, next_state)

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:editor_status, task_id, worker_pid, result}, state) do
    case Map.get(state.pending_editor_statuses, task_id) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])

        finish_editor_status(
          task_id,
          result,
          %{state | pending_editor_statuses: Map.delete(state.pending_editor_statuses, task_id)}
        )

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:editor_cancel, reference, worker_pid, task_id, result}, state) do
    case Map.get(state.pending_editor_cancels, reference) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])

        finish_editor_cancel(
          task_id,
          result,
          %{state | pending_editor_cancels: Map.delete(state.pending_editor_cancels, reference)}
        )

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:board_chat_cancel_result, task_id, worker_pid, result}, state) do
    case Map.get(state.pending_chat_cancels, task_id) do
      {topic_id, ^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])

        next_state = %{
          state
          | pending_chat_cancels: Map.delete(state.pending_chat_cancels, task_id)
        }

        finish_chat_cancel(topic_id, task_id, result, next_state)

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:notification_command, reference, worker_pid, result}, state) do
    case Map.get(state.pending_notifications, reference) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])
        finish_notification_command(result, clear_pending_notification(state, reference))

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:ollama_command, reference, worker_pid, result}, state) do
    case Map.get(state.pending_ollama, reference) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])
        finish_ollama_command(result, clear_pending_ollama(state, reference))

      _ ->
        {:ok, state}
    end
  end

  def handle_info({:DOWN, monitor_ref, :process, worker_pid, _reason} = message, state) do
    case Enum.find(state.pending_chat_sends, fn {_task_id, {_topic_id, pid, reference, _outcome}} ->
           pid == worker_pid and reference == monitor_ref
         end) do
      {task_id, {topic_id, _worker_pid, _monitor_ref, outcome_received}} ->
        next_state = %{state | pending_chat_sends: Map.delete(state.pending_chat_sends, task_id)}

        if outcome_received,
          do: {:ok, next_state},
          else: chat_send_failure(topic_id, task_id, false, next_state)

      nil ->
        handle_chat_cancel_down(message, state)
    end
  end

  def handle_info(:ping, state) do
    case state.authorization_client.authenticate(state.authorization_token) do
      {:ok, _user_uid} ->
        schedule_ping(state.ping_interval)
        push_frame({:ping, ""}, state)

      {:error, reason} ->
        {:stop, :normal, authorization_close_code(reason), state}
    end
  end

  def handle_info(_message, state), do: {:ok, state}

  defp handle_chat_cancel_down(
         {:DOWN, monitor_ref, :process, worker_pid, _reason} = message,
         state
       ) do
    case Enum.find(state.pending_chat_cancels, fn {_task_id, {_topic_id, pid, reference}} ->
           pid == worker_pid and reference == monitor_ref
         end) do
      {task_id, {topic_id, _pid, _reference}} ->
        next_state = %{
          state
          | pending_chat_cancels: Map.delete(state.pending_chat_cancels, task_id)
        }

        chat_send_failure(topic_id, task_id, false, next_state)

      nil ->
        handle_resume_down(message, state)
    end
  end

  defp handle_resume_down({:DOWN, monitor_ref, :process, worker_pid, _reason} = message, state) do
    case Enum.find(state.pending_chat_resumes, fn {_uid, {_topic_id, pid, reference, _outcome}} ->
           pid == worker_pid and reference == monitor_ref
         end) do
      {source_uid, {topic_id, _worker_pid, _monitor_ref, outcome_received}} ->
        next_state = %{
          state
          | pending_chat_resumes: Map.delete(state.pending_chat_resumes, source_uid)
        }

        if outcome_received do
          {:ok, next_state}
        else
          resume_result_unknown(topic_id, source_uid, next_state)
        end

      nil ->
        handle_editor_down(message, state)
    end
  end

  defp handle_editor_down({:DOWN, monitor_ref, :process, worker_pid, _reason} = message, state) do
    case Enum.find(state.pending_editor_runs, fn {_task_id, pending} ->
           pending.pid == worker_pid and pending.monitor == monitor_ref
         end) do
      {task_id, pending} ->
        next_state = %{
          state
          | pending_editor_runs: Map.delete(state.pending_editor_runs, task_id)
        }

        if pending.outcome do
          {:ok, next_state}
        else
          forward_editor_run_event(task_id, :failed, %{}, pending, next_state)
        end

      nil ->
        handle_editor_resume_down(message, state)
    end
  end

  defp handle_editor_resume_down(
         {:DOWN, monitor_ref, :process, worker_pid, _reason} = message,
         state
       ) do
    case Enum.find(state.pending_editor_resumes, fn {_uid, pending} ->
           pending.pid == worker_pid and pending.monitor == monitor_ref
         end) do
      {approval_uid, pending} ->
        next_state = %{
          state
          | pending_editor_resumes: Map.delete(state.pending_editor_resumes, approval_uid)
        }

        if pending.outcome do
          {:ok, next_state}
        else
          push_payload(
            %{
              event: @editor_approval_resume_result_event,
              topic: @notification_topic,
              topic_id: @notification_topic_id,
              data: %{
                approval_uid: approval_uid,
                status: "result_unknown",
                error_code: "unavailable"
              }
            },
            next_state
          )
        end

      nil ->
        handle_command_down(message, state)
    end
  end

  defp handle_command_down({:DOWN, monitor_ref, :process, worker_pid, _reason}, state) do
    case Enum.find(state.pending_editor_statuses, fn {_task_id, task} ->
           task == {worker_pid, monitor_ref}
         end) do
      {task_id, _task} ->
        finish_editor_status(
          task_id,
          {:error, :unavailable},
          %{state | pending_editor_statuses: Map.delete(state.pending_editor_statuses, task_id)}
        )

      nil ->
        handle_command_down_without_editor_status(monitor_ref, worker_pid, state)
    end
  end

  defp handle_command_down_without_editor_status(monitor_ref, worker_pid, state) do
    pending =
      Enum.find_value(
        [
          :pending_editor_cancels,
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
      {:pending_editor_cancels, reference} ->
        {:ok,
         %{state | pending_editor_cancels: Map.delete(state.pending_editor_cancels, reference)}}

      {:pending_bot_status, topic_id} ->
        finish_bot_status_map(
          topic_id,
          {:error, :unavailable},
          clear_pending_bot_status(state, topic_id)
        )

      {:pending_chat_availability, topic_id} ->
        finish_chat_availability(
          topic_id,
          {:error, :unavailable},
          clear_pending_chat_availability(state, topic_id)
        )

      {:pending_notifications, reference} ->
        finish_notification_command(
          {:error, :unavailable},
          clear_pending_notification(state, reference)
        )

      {:pending_ollama, reference} ->
        finish_ollama_command(
          {:error, :unavailable},
          clear_pending_ollama(state, reference)
        )

      nil ->
        {:ok, state}
    end
  end

  defp push_payload(payload, state) do
    queue_length = message_queue_length()

    if queue_length >= state.max_outbound_queue do
      Telemetry.emit_slow_client(queue_length)
      {:stop, :normal, Contract.close_code!("try_again_later"), state}
    else
      encoded = Jason.encode!(payload)
      Telemetry.emit_outbound(byte_size(encoded), queue_length)
      {:push, {:text, encoded}, state}
    end
  end

  defp push_payloads(payloads, state) do
    queue_length = message_queue_length()

    if queue_length + length(payloads) > state.max_outbound_queue do
      Telemetry.emit_slow_client(queue_length)
      {:stop, :normal, Contract.close_code!("try_again_later"), state}
    else
      messages =
        Enum.map(payloads, fn payload ->
          encoded = Jason.encode!(payload)
          Telemetry.emit_outbound(byte_size(encoded), queue_length)
          {:text, encoded}
        end)

      {:push, messages, state}
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

    Enum.each(state.pending_editor_runs, fn {_task_id, %{monitor: monitor_ref}} ->
      Process.demonitor(monitor_ref, [:flush])
    end)

    Enum.each(state.pending_editor_cancels, fn {_reference, {_worker_pid, monitor_ref}} ->
      Process.demonitor(monitor_ref, [:flush])
    end)

    Enum.each(state.pending_editor_statuses, fn {_task_id, {_worker_pid, monitor_ref}} ->
      Process.demonitor(monitor_ref, [:flush])
    end)

    Enum.each(state.pending_editor_resumes, fn {_approval_uid, %{monitor: monitor_ref}} ->
      Process.demonitor(monitor_ref, [:flush])
    end)

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
    do: handle_subscribe(payload, state)

  defp handle_payload({:ok, %{"event" => @unsubscribe_event} = payload}, state),
    do: handle_unsubscribe(payload, state)

  defp handle_payload({:ok, %{"event" => @bot_status_event} = payload}, state),
    do: handle_bot_status_map(payload, state)

  defp handle_payload({:ok, %{"event" => @chat_available_event} = payload}, state),
    do: handle_chat_availability(payload, state)

  defp handle_payload({:ok, %{"event" => event} = payload}, state)
       when event in [@chat_send_event, @chat_cancel_event, @chat_resume_event],
       do: handle_chat_payload(event, payload, state)

  defp handle_payload({:ok, %{"event" => event} = payload}, state)
       when event in @editor_events,
       do: handle_editor_payload(event, payload, state)

  defp handle_payload({:ok, %{"event" => event} = payload}, state)
       when is_map_key(@notification_actions, event),
       do: handle_notification_command(payload, state)

  defp handle_payload({:ok, %{"event" => event} = payload}, state)
       when is_map_key(@ollama_actions, event),
       do: handle_ollama_command(payload, state)

  defp handle_payload(_result, state), do: {:ok, state}

  defp handle_chat_payload(event, payload, state) do
    cond do
      event == @chat_send_event and
          Application.get_env(:langboard_socket, :board_chat_send_enabled, false) ->
        handle_chat_send(payload, state)

      event == @chat_cancel_event and
          Application.get_env(:langboard_socket, :board_chat_send_enabled, false) ->
        handle_chat_cancel(payload, state)

      event == @chat_resume_event and
          Application.get_env(:langboard_socket, :board_chat_resume_enabled, false) ->
        handle_chat_resume(payload, state)

      true ->
        {:ok, state}
    end
  end

  defp handle_editor_payload(event, payload, state) do
    if Application.get_env(:langboard_socket, :editor_ai_enabled, false) do
      cond do
        event == @editor_status_event ->
          handle_editor_status(payload, state)

        Map.has_key?(@editor_send_commands, event) ->
          handle_editor_send(payload, Map.fetch!(@editor_send_commands, event), state)

        Map.has_key?(@editor_abort_commands, event) ->
          handle_editor_abort(payload, Map.fetch!(@editor_abort_commands, event), state)

        event == @editor_approval_resume_event ->
          handle_editor_approval_resume(payload, state)
      end
    else
      {:ok, state}
    end
  end

  defp handle_editor_send(
         %{
           "event" => event,
           "topic" => @notification_topic,
           "topic_id" => @notification_topic_id,
           "data" => data
         },
         route,
         state
       )
       when is_map(data) do
    task_id = data["task_id"]

    cond do
      not valid_editor_send?(data, route) ->
        {:stop, :normal, Contract.close_code!("invalid_data"), state}

      Map.has_key?(state.pending_editor_runs, task_id) ->
        {:ok, state}

      pending_command_count(state) >=
          Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands) ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}

      true ->
        command = editor_command(data, route)
        worker = Application.get_env(:langboard_socket, :editor_run_worker, EditorRunWorker)
        options = [token: state.authorization_token, command: command, receiver: self()]

        case DynamicSupervisor.start_child(
               LangboardSocket.EditorRunSupervisor,
               {worker, options}
             ) do
          {:ok, worker_pid} ->
            monitor_ref = Process.monitor(worker_pid)

            pending = %{
              pid: worker_pid,
              monitor: monitor_ref,
              project_uid: command["project_uid"],
              event: event,
              kind: route.kind,
              output: route.output,
              outcome: false
            }

            {:ok,
             %{
               state
               | pending_editor_runs: Map.put(state.pending_editor_runs, task_id, pending)
             }}

          {:error, _reason} ->
            {:stop, :normal, Contract.close_code!("try_again_later"), state}
        end
    end
  end

  defp handle_editor_send(_payload, _route, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp handle_editor_abort(
         %{
           "topic" => @notification_topic,
           "topic_id" => @notification_topic_id,
           "data" => %{"task_id" => task_id, "project_uid" => project_uid}
         },
         send_event,
         state
       )
       when is_binary(task_id) and is_binary(project_uid) do
    if String.match?(task_id, @task_id_pattern) and valid_short_uid?(project_uid) do
      route = Map.fetch!(@editor_send_commands, send_event)

      case Map.get(state.pending_editor_runs, task_id) do
        %{event: ^send_event, project_uid: ^project_uid, pid: worker_pid} ->
          send(worker_pid, {:editor_abort_requested, task_id})
          {:ok, state}

        nil ->
          start_editor_cancel(project_uid, route.kind, task_id, state)

        _other ->
          {:stop, :normal, Contract.close_code!("invalid_data"), state}
      end
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_editor_abort(_payload, _send_event, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp start_editor_cancel(project_uid, kind, task_id, state) do
    owner = self()
    reference = make_ref()
    token = state.authorization_token
    client = Application.get_env(:langboard_socket, :editor_run_client, EditorRunClient)

    with false <- command_capacity_exhausted?(state),
         {:ok, worker_pid} <-
           Task.Supervisor.start_child(LangboardSocket.CommandTaskSupervisor, fn ->
             result = client.cancel(token, project_uid, kind, task_id)
             send(owner, {:editor_cancel, reference, self(), task_id, result})
           end) do
      monitor_ref = Process.monitor(worker_pid)

      {:ok,
       %{
         state
         | pending_editor_cancels:
             Map.put(state.pending_editor_cancels, reference, {worker_pid, monitor_ref})
       }}
    else
      _result -> {:stop, :normal, Contract.close_code!("try_again_later"), state}
    end
  end

  defp finish_editor_cancel(task_id, {:ok, run_uid}, state) do
    finish_editor_status(task_id, {:ok, %{"run_uid" => run_uid, "status" => "cancelled"}}, state)
  end

  defp finish_editor_cancel(task_id, {:error, _reason} = error, state),
    do: finish_editor_status(task_id, error, state)

  defp handle_editor_status(
         %{
           "topic" => @notification_topic,
           "topic_id" => @notification_topic_id,
           "data" => %{
             "task_id" => task_id,
             "project_uid" => project_uid,
             "kind" => kind
           }
         },
         state
       )
       when is_binary(task_id) and is_binary(project_uid) and is_binary(kind) do
    if valid_editor_status?(task_id, project_uid, kind) do
      start_editor_status(task_id, project_uid, kind, state)
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_editor_status(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp valid_editor_status?(task_id, project_uid, kind) do
    String.match?(task_id, @task_id_pattern) and valid_short_uid?(project_uid) and
      kind in ["editor_chat", "editor_copilot"]
  end

  defp start_editor_status(task_id, project_uid, kind, state) do
    cond do
      Map.has_key?(state.pending_editor_statuses, task_id) ->
        {:ok, state}

      pending_command_count(state) >=
          Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands) ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}

      true ->
        owner = self()
        token = state.authorization_token
        client = Application.get_env(:langboard_socket, :editor_run_client, EditorRunClient)

        fetch_status = fn ->
          send(
            owner,
            {:editor_status, task_id, self(), client.status(token, project_uid, kind, task_id)}
          )
        end

        case Task.Supervisor.start_child(LangboardSocket.CommandTaskSupervisor, fetch_status) do
          {:ok, worker_pid} ->
            monitor_ref = Process.monitor(worker_pid)

            {:ok,
             %{
               state
               | pending_editor_statuses:
                   Map.put(state.pending_editor_statuses, task_id, {worker_pid, monitor_ref})
             }}

          {:error, _reason} ->
            {:stop, :normal, Contract.close_code!("try_again_later"), state}
        end
    end
  end

  defp finish_editor_status(task_id, {:ok, data}, state) when is_map(data) do
    push_payload(
      %{
        event: @editor_status_result_event,
        topic: @notification_topic,
        topic_id: @notification_topic_id,
        data: Map.put(data, "task_id", task_id)
      },
      state
    )
  end

  defp finish_editor_status(task_id, {:error, reason}, state) do
    push_payload(
      %{
        event: @editor_status_result_event,
        topic: @notification_topic,
        topic_id: @notification_topic_id,
        data: %{
          "task_id" => task_id,
          "status" => "error",
          "error_code" => editor_status_error_code(reason)
        }
      },
      state
    )
  end

  defp editor_status_error_code(reason)
       when reason in [:forbidden, :unauthorized, :invalid_data, :conflict],
       do: Atom.to_string(reason)

  defp editor_status_error_code(_reason), do: "unavailable"

  defp handle_editor_approval_resume(
         %{
           "topic" => @notification_topic,
           "topic_id" => @notification_topic_id,
           "data" => %{
             "approval_uid" => approval_uid,
             "project_uid" => project_uid,
             "resume" => decision
           }
         },
         state
       ) do
    cond do
      not (valid_short_uid?(approval_uid) and valid_short_uid?(project_uid) and
               valid_editor_approval_decision?(decision)) ->
        {:stop, :normal, Contract.close_code!("invalid_data"), state}

      Map.has_key?(state.pending_editor_resumes, approval_uid) ->
        {:ok, state}

      pending_command_count(state) >=
          Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands) ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}

      true ->
        worker =
          Application.get_env(:langboard_socket, :editor_resume_worker, EditorResumeWorker)

        options = [
          token: state.authorization_token,
          project_uid: project_uid,
          approval_uid: approval_uid,
          decision: decision,
          receiver: self()
        ]

        case DynamicSupervisor.start_child(
               LangboardSocket.EditorRunSupervisor,
               {worker, options}
             ) do
          {:ok, worker_pid} ->
            monitor_ref = Process.monitor(worker_pid)

            pending = %{
              pid: worker_pid,
              monitor: monitor_ref,
              outcome: false
            }

            {:ok,
             %{
               state
               | pending_editor_resumes:
                   Map.put(state.pending_editor_resumes, approval_uid, pending)
             }}

          {:error, _reason} ->
            {:stop, :normal, Contract.close_code!("try_again_later"), state}
        end
    end
  end

  defp handle_editor_approval_resume(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp valid_editor_approval_decision?(
         %{"approved" => approved, "rejected" => rejected} = decision
       ) do
    map_size(decision) in 2..3 and
      Enum.all?(Map.keys(decision), &(&1 in ["approved", "rejected", "reason"])) and
      is_boolean(approved) and is_boolean(rejected) and
      approved != rejected and
      (not Map.has_key?(decision, "reason") or
         (rejected and is_binary(decision["reason"]) and byte_size(decision["reason"]) <= 1000))
  end

  defp valid_editor_approval_decision?(_decision), do: false

  defp editor_resume_error_code(reason)
       when reason in [:conflict, :forbidden, :unauthorized, :invalid_data],
       do: Atom.to_string(reason)

  defp editor_resume_error_code(_reason), do: "unavailable"

  defp valid_editor_send?(data, route) do
    task_id = Map.get(data, "task_id")
    project_uid = Map.get(data, "project_uid")
    scope_uid = Map.get(data, route.scope_field)
    document_name = Map.get(data, "document_name")
    system = Map.get(data, "system", "")

    is_binary(task_id) and String.match?(task_id, @task_id_pattern) and
      valid_short_uid?(project_uid) and valid_short_uid?(scope_uid) and
      valid_editor_document_name?(document_name, route.document_type, scope_uid) and
      is_binary(system) and byte_size(system) <= 65_536 and
      is_nil(Map.get(data, "file_path")) and valid_editor_input?(data, route.kind)
  end

  defp valid_editor_document_name?(name, type, scope_uid)
       when is_binary(name) and byte_size(name) in 1..512,
       do: String.starts_with?(name, "#{type}:#{scope_uid}:")

  defp valid_editor_document_name?(_name, _type, _scope_uid), do: false

  defp valid_editor_input?(data, "editor_chat") do
    messages = Map.get(data, "messages")

    is_nil(Map.get(data, "prompt")) and is_list(messages) and length(messages) in 1..100 and
      Enum.all?(messages, fn
        %{"role" => role, "content" => content} ->
          role in ["system", "user", "assistant"] and is_binary(content) and
            byte_size(content) <= 65_536

        _ ->
          false
      end) and
      Enum.reduce(messages, 0, fn message, total -> total + byte_size(message["content"]) end) <=
        65_536
  end

  defp valid_editor_input?(data, "editor_copilot") do
    prompt = Map.get(data, "prompt")
    is_nil(Map.get(data, "messages")) and is_binary(prompt) and byte_size(prompt) in 1..65_536
  end

  defp editor_command(data, route) do
    base = %{
      "task_id" => data["task_id"],
      "project_uid" => data["project_uid"],
      "scope_uid" => data[route.scope_field],
      "document_name" => data["document_name"],
      "kind" => route.kind,
      "system" => Map.get(data, "system", "")
    }

    case route.kind do
      "editor_chat" ->
        Map.put(base, "messages", Enum.map(data["messages"], &Map.take(&1, ["role", "content"])))

      "editor_copilot" ->
        Map.put(base, "prompt", data["prompt"])
    end
  end

  defp forward_editor_run_event(_task_id, event, data, %{kind: "editor_chat"} = pending, state) do
    {phase, payload} =
      case event do
        :start ->
          {"start", %{}}

        :buffer ->
          {"buffer", %{message: Map.get(data, :message, "")}}

        :end when data.status == "completed" ->
          {"end", %{message: data.message}}

        :end when data.status == "awaiting_approval" ->
          {"end", %{status: "awaiting_approval", message: data.message}}

        _ ->
          {"end", %{status: "failed", message: "Editor AI request failed"}}
      end

    push_payload(
      %{
        event: pending.output <> ":" <> phase,
        topic: @notification_topic,
        topic_id: @notification_topic_id,
        data: payload
      },
      state
    )
  end

  defp forward_editor_run_event(task_id, event, data, pending, state)
       when event in [:end, :failed, :cancelled] do
    text = if event == :end and data.status == "completed", do: data.message, else: "0"

    push_payload(
      %{
        event: pending.output <> ":" <> task_id,
        topic: @notification_topic,
        topic_id: @notification_topic_id,
        data: %{text: if(text == "", do: "0", else: text)}
      },
      state
    )
  end

  defp forward_editor_run_event(_task_id, _event, _data, _pending, state), do: {:ok, state}

  defp handle_subscribe(%{"topic" => topic, "topic_id" => topic_ids}, state)
       when is_binary(topic) do
    cond do
      not valid_topic_ids?(topic_ids) ->
        {:stop, :normal, Contract.close_code!("invalid_data"), state}

      not Contract.valid_topic?(topic) ->
        push_frame(encode_message(Contract.event!("subscribed"), topic, []), state)

      true ->
        requested_ids = normalize_topic_ids(topic_ids)

        case state.authorization_client.authorize_subscriptions(
               state.authorization_token,
               topic,
               requested_ids
             ) do
          {:ok, accepted} ->
            new_subscriptions = MapSet.new(accepted, &{topic, &1})

            rejected =
              requested_ids
              |> MapSet.new(&{topic, &1})
              |> MapSet.difference(new_subscriptions)

            state = remove_subscriptions(state, rejected)

            new_subscriptions
            |> MapSet.difference(state.subscriptions)
            |> Enum.each(&subscribe/1)

            added_count =
              new_subscriptions
              |> MapSet.difference(state.subscriptions)
              |> MapSet.size()

            Telemetry.emit_subscription_change(added_count)

            next_state = %{
              state
              | subscriptions: MapSet.union(state.subscriptions, new_subscriptions)
            }

            push_frame(
              encode_message(Contract.event!("subscribed"), topic, accepted),
              next_state
            )

          {:error, reason} ->
            {:stop, :normal, authorization_close_code(reason), state}
        end
    end
  end

  defp handle_subscribe(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp handle_unsubscribe(%{"topic" => topic, "topic_id" => topic_ids}, state)
       when is_binary(topic) do
    if valid_topic_ids?(topic_ids) do
      requested_ids = normalize_topic_ids(topic_ids)
      requested = MapSet.new(requested_ids, &{topic, &1})
      next_state = remove_subscriptions(state, requested)

      push_frame(
        encode_message(Contract.event!("unsubscribed"), topic, requested_ids),
        next_state
      )
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_unsubscribe(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp remove_subscriptions(state, requested) do
    removed = MapSet.intersection(state.subscriptions, requested)
    Enum.each(removed, &unsubscribe/1)
    Telemetry.emit_subscription_change(-MapSet.size(removed))

    state
    |> Map.put(:subscriptions, MapSet.difference(state.subscriptions, removed))
    |> cancel_bot_status_for(removed)
    |> cancel_chat_availability_for(removed)
  end

  defp revoke_subscription(topic, topic_id, state) do
    next_state = remove_subscriptions(state, MapSet.new([{topic, topic_id}]))

    push_payloads(
      [
        %{
          event: Contract.event!("subscription_revoked"),
          topic: topic,
          topic_id: topic_id,
          data: %{}
        },
        %{event: Contract.event!("unsubscribed"), topic: topic, topic_id: [topic_id]}
      ],
      next_state
    )
  end

  defp handle_board_authorization_error(topic_id, close_code, state) do
    if close_code == Contract.close_code!("forbidden") and
         MapSet.member?(state.subscriptions, {@board_topic, topic_id}) do
      revoke_subscription(@board_topic, topic_id, state)
    else
      {:stop, :normal, close_code, state}
    end
  end

  defp handle_bot_status_map(%{"topic" => @board_topic, "topic_id" => topic_id}, state)
       when is_binary(topic_id) and topic_id != "" do
    case authorize_board_command(topic_id, state) do
      :ok -> start_bot_status_map(topic_id, state)
      {:error, close_code} -> handle_board_authorization_error(topic_id, close_code, state)
    end
  end

  defp handle_bot_status_map(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp start_bot_status_map(topic_id, state) do
    cond do
      Map.has_key?(state.pending_bot_status, topic_id) ->
        {:ok, state}

      command_capacity_exhausted?(state) ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}

      true ->
        owner = self()
        client = Application.fetch_env!(:langboard_socket, :bot_status_client)

        fetch_status = fn ->
          send(owner, {:bot_status_map, topic_id, self(), client.fetch(topic_id)})
        end

        case Task.Supervisor.start_child(LangboardSocket.CommandTaskSupervisor, fetch_status) do
          {:ok, worker_pid} ->
            monitor_ref = Process.monitor(worker_pid)

            {:ok,
             %{
               state
               | pending_bot_status:
                   Map.put(state.pending_bot_status, topic_id, {worker_pid, monitor_ref})
             }}

          {:error, _reason} ->
            {:stop, :normal, Contract.close_code!("try_again_later"), state}
        end
    end
  end

  defp finish_bot_status_map(topic_id, result, state) do
    with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         :ok <- authorize_board_command(topic_id, state) do
      status_map =
        case result do
          {:ok, value} -> value
          _ -> nil
        end

      push_payload(
        %{
          event: @bot_status_event,
          topic: @board_topic,
          topic_id: topic_id,
          data: %{bot_status_map: status_map}
        },
        state
      )
    else
      false -> {:ok, state}
      {:error, close_code} -> handle_board_authorization_error(topic_id, close_code, state)
    end
  end

  defp handle_chat_availability(%{"topic" => @board_topic, "topic_id" => topic_id}, state)
       when is_binary(topic_id) and topic_id != "" do
    case authorize_board_command(topic_id, state) do
      :ok -> start_chat_availability(topic_id, state)
      {:error, close_code} -> handle_board_authorization_error(topic_id, close_code, state)
    end
  end

  defp handle_chat_availability(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp start_chat_availability(topic_id, state) do
    cond do
      Map.has_key?(state.pending_chat_availability, topic_id) ->
        {:ok, state}

      command_capacity_exhausted?(state) ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}

      true ->
        owner = self()
        token = state.authorization_token
        client = Application.fetch_env!(:langboard_socket, :chat_availability_client)

        fetch_availability = fn ->
          send(owner, {:chat_availability, topic_id, self(), client.fetch(token, topic_id)})
        end

        case Task.Supervisor.start_child(
               LangboardSocket.CommandTaskSupervisor,
               fetch_availability
             ) do
          {:ok, worker_pid} ->
            monitor_ref = Process.monitor(worker_pid)

            {:ok,
             %{
               state
               | pending_chat_availability:
                   Map.put(state.pending_chat_availability, topic_id, {worker_pid, monitor_ref})
             }}

          {:error, _reason} ->
            {:stop, :normal, Contract.close_code!("try_again_later"), state}
        end
    end
  end

  defp finish_chat_availability(topic_id, result, state) do
    with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         :ok <- authorize_board_command(topic_id, state) do
      case result do
        {:ok, data} ->
          push_payload(
            %{
              event: @chat_available_event,
              topic: @board_topic,
              topic_id: topic_id,
              data: data
            },
            state
          )

        {:error, :unauthorized} ->
          {:stop, :normal, Contract.close_code!("unauthorized"), state}

        {:error, :forbidden} ->
          {:stop, :normal, Contract.close_code!("forbidden"), state}

        _ ->
          {:stop, :normal, Contract.close_code!("internal_error"), state}
      end
    else
      false -> {:ok, state}
      {:error, close_code} -> handle_board_authorization_error(topic_id, close_code, state)
    end
  end

  defp handle_chat_send(
         %{"topic" => @board_topic, "topic_id" => topic_id, "data" => data},
         state
       )
       when is_binary(topic_id) and topic_id != "" and is_map(data) do
    if valid_chat_send_data?(data) do
      case authorize_board_command(topic_id, state) do
        :ok -> start_chat_send(topic_id, data, state)
        {:error, close_code} -> {:stop, :normal, close_code, state}
      end
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_chat_send(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp handle_chat_cancel(
         %{"topic" => @board_topic, "topic_id" => topic_id, "data" => %{"task_id" => task_id}},
         state
       )
       when is_binary(topic_id) and topic_id != "" and is_binary(task_id) do
    if String.match?(task_id, @task_id_pattern) do
      case authorize_board_command(topic_id, state) do
        :ok -> start_chat_cancel(topic_id, task_id, state)
        {:error, close_code} -> {:stop, :normal, close_code, state}
      end
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_chat_cancel(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp start_chat_cancel(topic_id, task_id, state) do
    if Map.has_key?(state.pending_chat_cancels, task_id) do
      {:ok, state}
    else
      if command_capacity_exhausted?(state) do
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
      else
        start_chat_cancel_request(topic_id, task_id, state)
      end
    end
  end

  defp start_chat_cancel_request(topic_id, task_id, state) do
    owner = self()
    token = state.authorization_token
    client = Application.get_env(:langboard_socket, :board_chat_run_client, BoardChatRunClient)

    cancel_request = fn ->
      result = client.cancel(token, topic_id, task_id)

      if match?({:ok, _run_uid}, result) do
        {:ok, run_uid} = result

        Phoenix.PubSub.broadcast(
          LangboardSocket.PubSub,
          BoardChatRunWorker.cancel_topic(run_uid),
          {:board_chat_run_cancelled, run_uid}
        )
      end

      send(owner, {:board_chat_cancel_result, task_id, self(), result})
    end

    case Task.Supervisor.start_child(LangboardSocket.CommandTaskSupervisor, cancel_request) do
      {:ok, worker_pid} ->
        monitor_ref = Process.monitor(worker_pid)

        {:ok,
         %{
           state
           | pending_chat_cancels:
               Map.put(state.pending_chat_cancels, task_id, {topic_id, worker_pid, monitor_ref})
         }}

      {:error, _reason} ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
    end
  end

  defp finish_chat_cancel(topic_id, task_id, result, state) do
    with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         :ok <- authorize_board_command(topic_id, state) do
      case {result, Map.get(state.pending_chat_sends, task_id)} do
        {{:ok, _run_uid}, {_topic_id, _pid, _reference, true}} ->
          {:ok, state}

        {{:ok, _run_uid}, {_topic_id, _pid, _reference, false}} ->
          push_payload(
            task_aborted_frame(task_id),
            mark_send_outcome(state, task_id, :cancelled)
          )

        {{:ok, _run_uid}, nil} ->
          push_payload(task_aborted_frame(task_id), state)

        {{:error, _reason}, _pending} ->
          chat_send_failure(topic_id, task_id, false, state)
      end
    else
      false -> {:ok, state}
      {:error, close_code} -> {:stop, :normal, close_code, state}
    end
  end

  defp task_aborted_frame(task_id) do
    %{
      event: @task_aborted_event,
      topic: Contract.topic!("global"),
      topic_id: Contract.topic_id!("global"),
      data: %{task_id: task_id}
    }
  end

  defp valid_chat_send_data?(data) do
    message = Map.get(data, "message")
    file_token = Map.get(data, "file_token")
    task_id = Map.get(data, "task_id")
    scope_table = Map.get(data, "scope_table", "project")
    scope_uid = Map.get(data, "scope_uid")
    session_uid = Map.get(data, "session_uid")
    permission_level = Map.get(data, "api_permission_level", "read")

    valid_chat_content?(message, file_token) and
      is_binary(task_id) and String.match?(task_id, @task_id_pattern) and
      is_nil(Map.get(data, "file_path")) and
      (is_nil(session_uid) or valid_short_uid?(session_uid)) and
      permission_level in ["read", "edit", "full_access"] and
      valid_chat_scope?(scope_table, scope_uid)
  end

  defp valid_chat_content?(message, file_token) when is_binary(message) do
    byte_size(message) <= 65_536 and
      (is_nil(file_token) or valid_file_token?(file_token)) and
      (byte_size(message) > 0 or is_binary(file_token))
  end

  defp valid_chat_content?(_message, _file_token), do: false

  defp valid_chat_scope?("project", nil), do: true

  defp valid_chat_scope?(scope_table, scope_uid)
       when scope_table in ["card", "project_column", "project_wiki"],
       do: valid_short_uid?(scope_uid)

  defp valid_chat_scope?(_scope_table, _scope_uid), do: false

  defp valid_file_token?(token) when is_binary(token),
    do: byte_size(token) in 32..128 and String.match?(token, ~r/^[A-Za-z0-9._:-]+$/)

  defp valid_file_token?(_token), do: false

  defp start_chat_send(topic_id, data, state) do
    task_id = data["task_id"]

    if Map.has_key?(state.pending_chat_sends, task_id) do
      {:ok, state}
    else
      if command_capacity_exhausted?(state) do
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
      else
        start_chat_send_request(topic_id, data, state)
      end
    end
  end

  defp start_chat_send_request(topic_id, data, state) do
    task_id = data["task_id"]
    worker = Application.get_env(:langboard_socket, :board_chat_run_worker, BoardChatRunWorker)

    command =
      data
      |> Map.take([
        "task_id",
        "message",
        "file_token",
        "session_uid",
        "scope_table",
        "scope_uid",
        "api_permission_level"
      ])
      |> Map.put_new("scope_table", "project")
      |> Map.put_new("api_permission_level", "read")

    options = [
      token: state.authorization_token,
      project_uid: topic_id,
      command: command,
      receiver: self()
    ]

    case DynamicSupervisor.start_child(
           LangboardSocket.BoardChatRunSupervisor,
           {worker, options}
         ) do
      {:ok, worker_pid} ->
        monitor_ref = Process.monitor(worker_pid)

        {:ok,
         %{
           state
           | pending_chat_sends:
               Map.put(state.pending_chat_sends, task_id, {
                 topic_id,
                 worker_pid,
                 monitor_ref,
                 false
               })
         }}

      {:error, _reason} ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
    end
  end

  defp mark_send_outcome(state, task_id, event)
       when event in [
              :already_started,
              :accept_failed,
              :end,
              :start_failed,
              :lease_lost,
              :result_unknown,
              :cancelled
            ] do
    {topic_id, worker_pid, monitor_ref, _outcome_received} =
      Map.fetch!(state.pending_chat_sends, task_id)

    %{
      state
      | pending_chat_sends:
          Map.put(state.pending_chat_sends, task_id, {topic_id, worker_pid, monitor_ref, true})
    }
  end

  defp mark_send_outcome(state, _task_id, _event), do: state

  defp forward_chat_send_event(topic_id, _task_id, :accepted, data, state) do
    push_payloads(
      [
        chat_frame(topic_id, @chat_session_event, %{session: data.session}),
        chat_frame(topic_id, @chat_sent_event, %{user_message: data.user_message})
      ],
      state
    )
  end

  defp forward_chat_send_event(topic_id, task_id, :already_started, data, state) do
    push_payloads(
      [
        chat_frame(topic_id, @chat_session_event, %{session: data.session}),
        chat_frame(topic_id, @chat_sent_event, %{user_message: data.user_message}),
        chat_send_failed_frame(topic_id, task_id, true)
      ],
      state
    )
  end

  defp forward_chat_send_event(topic_id, task_id, :start_failed, %{reason: :conflict}, state) do
    push_payload(chat_send_failed_frame(topic_id, task_id, true), state)
  end

  defp forward_chat_send_event(topic_id, _task_id, event, data, state)
       when event in [:start, :buffer, :end] do
    push_payload(chat_frame(topic_id, "#{@chat_stream_event}:#{event}", data), state)
  end

  defp forward_chat_send_event(_topic_id, task_id, :cancelled, _data, state) do
    push_payload(task_aborted_frame(task_id), state)
  end

  defp forward_chat_send_event(topic_id, task_id, _event, _data, state) do
    push_payload(chat_send_failed_frame(topic_id, task_id, false), state)
  end

  defp chat_send_failure(topic_id, task_id, already_started, state) do
    if MapSet.member?(state.subscriptions, {@board_topic, topic_id}) do
      case authorize_board_command(topic_id, state) do
        :ok -> push_payload(chat_send_failed_frame(topic_id, task_id, already_started), state)
        {:error, close_code} -> {:stop, :normal, close_code, state}
      end
    else
      {:ok, state}
    end
  end

  defp chat_send_failed_frame(topic_id, task_id, already_started) do
    chat_frame(topic_id, @chat_send_failed_event, %{
      task_id: task_id,
      already_started: already_started
    })
  end

  defp chat_frame(topic_id, event, data) do
    %{event: event, topic: @board_topic, topic_id: topic_id, data: data}
  end

  defp handle_chat_resume(
         %{"topic" => @board_topic, "topic_id" => topic_id, "data" => data},
         state
       )
       when is_binary(topic_id) and topic_id != "" and is_map(data) do
    if valid_chat_resume_data?(data) do
      case authorize_board_command(topic_id, state) do
        :ok -> start_chat_resume(topic_id, data, state)
        {:error, close_code} -> {:stop, :normal, close_code, state}
      end
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_chat_resume(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp valid_chat_resume_data?(
         %{
           "message_uid" => uid,
           "thread_id" => thread_id,
           "session_id" => session_id,
           "resume" => resume
         } = data
       ) do
    valid_short_uid?(uid) and
      is_binary(thread_id) and byte_size(thread_id) in 1..512 and
      is_binary(session_id) and byte_size(session_id) in @short_uid_length..512 and
      is_map(resume) and
      (is_nil(Map.get(data, "approval_uid")) or valid_short_uid?(data["approval_uid"]))
  end

  defp valid_chat_resume_data?(_data), do: false

  defp valid_short_uid?(uid) do
    is_binary(uid) and byte_size(uid) == @short_uid_length and
      String.match?(uid, ~r/\A[0-9A-Za-z]+\z/)
  end

  defp start_chat_resume(topic_id, data, state) do
    source_uid = data["message_uid"]

    if Map.has_key?(state.pending_chat_resumes, source_uid) do
      {:ok, state}
    else
      if command_capacity_exhausted?(state) do
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
      else
        start_chat_resume_request(topic_id, data, state)
      end
    end
  end

  defp start_chat_resume_request(topic_id, data, state) do
    source_uid = data["message_uid"]

    worker =
      Application.get_env(:langboard_socket, :board_chat_resume_worker, BoardChatResumeWorker)

    options = [
      token: state.authorization_token,
      project_uid: topic_id,
      command: data,
      receiver: self()
    ]

    case DynamicSupervisor.start_child(
           LangboardSocket.BoardChatRunSupervisor,
           {worker, options}
         ) do
      {:ok, worker_pid} ->
        monitor_ref = Process.monitor(worker_pid)

        {:ok,
         %{
           state
           | pending_chat_resumes:
               Map.put(
                 state.pending_chat_resumes,
                 source_uid,
                 {topic_id, worker_pid, monitor_ref, false}
               )
         }}

      {:error, _reason} ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
    end
  end

  defp resume_error_code(%{reason: reason}) do
    case reason do
      :unauthorized -> Contract.close_code!("unauthorized")
      :forbidden -> Contract.close_code!("forbidden")
      reason when reason in [:invalid_data, :conflict] -> Contract.close_code!("invalid_data")
      _ -> Contract.close_code!("internal_error")
    end
  end

  defp resume_error_code(_data), do: Contract.close_code!("internal_error")

  defp mark_resume_outcome(state, source_uid, event)
       when event in [:claim_failed, :result_unknown, :lease_lost] do
    {topic_id, worker_pid, monitor_ref, _outcome_received} =
      Map.fetch!(state.pending_chat_resumes, source_uid)

    %{
      state
      | pending_chat_resumes:
          Map.put(state.pending_chat_resumes, source_uid, {
            topic_id,
            worker_pid,
            monitor_ref,
            true
          })
    }
  end

  defp mark_resume_outcome(state, _source_uid, _event), do: state

  defp resume_result_unknown(topic_id, source_uid, state) do
    if MapSet.member?(state.subscriptions, {@board_topic, topic_id}) do
      case authorize_board_command(topic_id, state) do
        :ok ->
          push_payload(
            %{
              event: "#{@chat_stream_event}:buffer",
              topic: @board_topic,
              topic_id: topic_id,
              data: %{uid: source_uid, resume_error_code: Contract.close_code!("internal_error")}
            },
            state
          )

        {:error, close_code} ->
          {:stop, :normal, close_code, state}
      end
    else
      {:ok, state}
    end
  end

  defp authorize_board_command(topic_id, state) do
    with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         {:ok, accepted} <-
           state.authorization_client.authorize_subscriptions(
             state.authorization_token,
             @board_topic,
             [topic_id]
           ),
         true <- topic_id in accepted do
      :ok
    else
      false -> {:error, Contract.close_code!("forbidden")}
      {:error, reason} -> {:error, authorization_close_code(reason)}
    end
  end

  defp cancel_bot_status_for(state, removed) do
    Enum.reduce(removed, state, fn
      {@board_topic, topic_id}, state ->
        case Map.get(state.pending_bot_status, topic_id) do
          {worker_pid, monitor_ref} ->
            Process.demonitor(monitor_ref, [:flush])
            Task.Supervisor.terminate_child(LangboardSocket.CommandTaskSupervisor, worker_pid)
            clear_pending_bot_status(state, topic_id)

          nil ->
            state
        end

      _subscription, state ->
        state
    end)
  end

  defp clear_pending_bot_status(state, topic_id) do
    %{state | pending_bot_status: Map.delete(state.pending_bot_status, topic_id)}
  end

  defp cancel_chat_availability_for(state, removed) do
    Enum.reduce(removed, state, fn
      {@board_topic, topic_id}, state ->
        case Map.get(state.pending_chat_availability, topic_id) do
          {worker_pid, monitor_ref} ->
            Process.demonitor(monitor_ref, [:flush])
            Task.Supervisor.terminate_child(LangboardSocket.CommandTaskSupervisor, worker_pid)
            clear_pending_chat_availability(state, topic_id)

          nil ->
            state
        end

      _subscription, state ->
        state
    end)
  end

  defp clear_pending_chat_availability(state, topic_id) do
    %{state | pending_chat_availability: Map.delete(state.pending_chat_availability, topic_id)}
  end

  defp handle_notification_command(%{"topic" => @notification_topic} = payload, state) do
    if Map.get(payload, "topic_id") in [nil, @notification_topic_id] do
      action = Map.fetch!(@notification_actions, Map.fetch!(payload, "event"))

      case notification_uid(payload, action) do
        {:ok, uid} -> start_notification_command(action, uid, state)
        {:error, :invalid_data} -> {:stop, :normal, Contract.close_code!("invalid_data"), state}
      end
    else
      {:stop, :normal, Contract.close_code!("forbidden"), state}
    end
  end

  defp handle_notification_command(_payload, state),
    do: {:stop, :normal, Contract.close_code!("forbidden"), state}

  defp notification_uid(%{"data" => %{"uid" => uid}}, action)
       when action in [:read, :delete] and is_binary(uid) and byte_size(uid) == @short_uid_length do
    if String.match?(uid, ~r/\A[0-9A-Za-z]+\z/),
      do: {:ok, uid},
      else: {:error, :invalid_data}
  end

  defp notification_uid(_payload, action) when action in [:read, :delete],
    do: {:error, :invalid_data}

  defp notification_uid(_payload, _action), do: {:ok, nil}

  defp start_notification_command(action, uid, state) do
    if command_capacity_exhausted?(state) do
      {:stop, :normal, Contract.close_code!("try_again_later"), state}
    else
      owner = self()
      reference = make_ref()
      client = Application.fetch_env!(:langboard_socket, :notification_client)
      token = state.authorization_token

      execute_command = fn ->
        send(
          owner,
          {:notification_command, reference, self(), client.execute(token, action, uid)}
        )
      end

      case Task.Supervisor.start_child(LangboardSocket.CommandTaskSupervisor, execute_command) do
        {:ok, worker_pid} ->
          monitor_ref = Process.monitor(worker_pid)

          {:ok,
           %{
             state
             | pending_notifications:
                 Map.put(state.pending_notifications, reference, {worker_pid, monitor_ref})
           }}

        {:error, _reason} ->
          {:stop, :normal, Contract.close_code!("try_again_later"), state}
      end
    end
  end

  defp finish_notification_command(:ok, state), do: {:ok, state}

  defp finish_notification_command({:error, reason}, state) do
    close_code =
      case reason do
        :unauthorized -> Contract.close_code!("unauthorized")
        :forbidden -> Contract.close_code!("forbidden")
        :invalid_data -> Contract.close_code!("invalid_data")
        _ -> Contract.close_code!("internal_error")
      end

    {:stop, :normal, close_code, state}
  end

  defp clear_pending_notification(state, reference) do
    %{state | pending_notifications: Map.delete(state.pending_notifications, reference)}
  end

  defp handle_ollama_command(
         %{"topic" => @ollama_topic, "topic_id" => @ollama_topic_id} = payload,
         state
       ) do
    case authorize_ollama_command(state) do
      :ok ->
        action = Map.fetch!(@ollama_actions, Map.fetch!(payload, "event"))

        case ollama_data(action, Map.get(payload, "data")) do
          {:ok, data} -> start_ollama_command(action, data, state)
          :error -> {:stop, :normal, Contract.close_code!("invalid_data"), state}
        end

      {:error, close_code} ->
        {:stop, :normal, close_code, state}
    end
  end

  defp handle_ollama_command(_payload, state),
    do: {:stop, :normal, Contract.close_code!("forbidden"), state}

  defp authorize_ollama_command(state) do
    with true <- MapSet.member?(state.subscriptions, {@ollama_topic, @ollama_topic_id}),
         {:ok, accepted} <-
           state.authorization_client.authorize_subscriptions(
             state.authorization_token,
             @ollama_topic,
             [@ollama_topic_id]
           ),
         true <- @ollama_topic_id in accepted do
      :ok
    else
      false -> {:error, Contract.close_code!("forbidden")}
      {:error, reason} -> {:error, authorization_close_code(reason)}
    end
  end

  defp ollama_data(:copy, %{"model" => model, "copy_to" => destination})
       when is_binary(model) and byte_size(model) in 1..255 and is_binary(destination) and
              byte_size(destination) in 1..255,
       do: {:ok, %{"model" => model, "copy_to" => destination}}

  defp ollama_data(:delete, %{"model" => model})
       when is_binary(model) and byte_size(model) in 1..255,
       do: {:ok, %{"model" => model}}

  defp ollama_data(:pull, %{"model" => model})
       when is_binary(model) and byte_size(model) in 1..255,
       do: {:ok, %{"model" => model}}

  defp ollama_data(_action, _data), do: :error

  defp start_ollama_command(action, data, state) do
    if command_capacity_exhausted?(state) do
      {:stop, :normal, Contract.close_code!("try_again_later"), state}
    else
      owner = self()
      reference = make_ref()
      client = Application.fetch_env!(:langboard_socket, :ollama_client)
      token = state.authorization_token

      execute_command = fn ->
        send(
          owner,
          {:ollama_command, reference, self(), client.execute(token, action, data)}
        )
      end

      case Task.Supervisor.start_child(LangboardSocket.CommandTaskSupervisor, execute_command) do
        {:ok, worker_pid} ->
          monitor_ref = Process.monitor(worker_pid)

          {:ok,
           %{
             state
             | pending_ollama: Map.put(state.pending_ollama, reference, {worker_pid, monitor_ref})
           }}

        {:error, _reason} ->
          {:stop, :normal, Contract.close_code!("try_again_later"), state}
      end
    end
  end

  defp finish_ollama_command(:ok, state), do: {:ok, state}

  defp finish_ollama_command({:error, reason}, state) do
    close_code =
      case reason do
        :unauthorized -> Contract.close_code!("unauthorized")
        :forbidden -> Contract.close_code!("forbidden")
        :invalid_data -> Contract.close_code!("invalid_data")
        _ -> Contract.close_code!("internal_error")
      end

    {:stop, :normal, close_code, state}
  end

  defp clear_pending_ollama(state, reference) do
    %{state | pending_ollama: Map.delete(state.pending_ollama, reference)}
  end

  defp normalize_topic_ids(topic_id) when is_binary(topic_id) and topic_id != "", do: [topic_id]

  defp normalize_topic_ids(topic_ids) when is_list(topic_ids) do
    Enum.filter(topic_ids, &(is_binary(&1) and &1 != ""))
  end

  defp normalize_topic_ids(_topic_ids), do: []

  defp valid_topic_ids?(topic_id) when is_binary(topic_id),
    do: valid_topic_id?(topic_id)

  defp valid_topic_ids?(topic_ids) when is_list(topic_ids) do
    length(topic_ids) <= @max_topic_ids and Enum.all?(topic_ids, &valid_topic_id?/1)
  end

  defp valid_topic_ids?(_topic_ids), do: false

  defp valid_topic_id?(topic_id) when is_binary(topic_id) do
    topic_id != "" and byte_size(topic_id) <= @max_topic_id_bytes
  end

  defp valid_topic_id?(_topic_id), do: false

  defp command_capacity_exhausted?(state) do
    pending_command_count(state) >=
      Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands)
  end

  defp pending_command_count(state) do
    Enum.sum([
      map_size(state.pending_notifications),
      map_size(state.pending_ollama),
      map_size(state.pending_bot_status),
      map_size(state.pending_chat_availability),
      map_size(state.pending_chat_sends),
      map_size(state.pending_chat_cancels),
      map_size(state.pending_chat_resumes),
      map_size(state.pending_editor_runs),
      map_size(state.pending_editor_cancels),
      map_size(state.pending_editor_statuses),
      map_size(state.pending_editor_resumes)
    ])
  end

  defp subscribe({topic, topic_id}) do
    Phoenix.PubSub.subscribe(LangboardSocket.PubSub, SubscriptionTopic.name(topic, topic_id))
  end

  defp unsubscribe({topic, topic_id}) do
    Phoenix.PubSub.unsubscribe(LangboardSocket.PubSub, SubscriptionTopic.name(topic, topic_id))
  end

  defp schedule_ping(interval), do: Process.send_after(self(), :ping, interval)

  defp authorization_close_code(:expired_token), do: Contract.close_code!("expired_token")
  defp authorization_close_code(:unauthorized), do: Contract.close_code!("unauthorized")
  defp authorization_close_code(_reason), do: Contract.close_code!("internal_error")

  defp message_queue_length do
    case Process.info(self(), :message_queue_len) do
      {:message_queue_len, length} -> length
      nil -> 0
    end
  end

  defp push_frame({_opcode, payload} = frame, state) do
    Telemetry.emit_outbound(byte_size(payload), message_queue_length())
    {:push, frame, state}
  end

  defp push_frames(frames, state) do
    queue_length = message_queue_length()

    Enum.each(frames, fn {_opcode, payload} ->
      Telemetry.emit_outbound(byte_size(payload), queue_length)
    end)

    {:push, frames, state}
  end

  defp encode_message(event, topic, topic_ids) do
    {:text, Jason.encode!(%{event: event, topic: topic, topic_id: topic_ids})}
  end
end
