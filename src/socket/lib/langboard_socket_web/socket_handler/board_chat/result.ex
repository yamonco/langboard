defmodule LangboardSocketWeb.SocketHandler.BoardChat.Result do
  @moduledoc false

  import LangboardSocketWeb.SocketHandler.Outbound, only: [push_payload: 2, push_payloads: 2]

  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocketWeb.SocketHandler.Subscriptions

  @board_topic Contract.topic!("board")
  @chat_session_event Contract.event!("board_chat_session")
  @chat_sent_event Contract.event!("board_chat_sent")
  @chat_send_failed_event Contract.event!("board_chat_send_failed")
  @chat_stream_event Contract.event!("board_chat_stream")
  @task_aborted_event Contract.event!("task_aborted")

  defp finish_cancel(topic_id, task_id, result, state) do
    with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         :ok <- Subscriptions.authorize_board_command(topic_id, state) do
      case {result, Map.get(state.pending_chat_sends, task_id)} do
        {{:ok, _run_uid}, {_topic_id, _pid, _reference, true}} ->
          {:ok, state}

        {{:ok, _run_uid}, {_topic_id, _pid, _reference, false}} ->
          push_payload(aborted_frame(task_id), mark_send_outcome(state, task_id, :cancelled))

        {{:ok, _run_uid}, nil} ->
          push_payload(aborted_frame(task_id), state)

        {{:error, _reason}, _pending} ->
          send_failure(topic_id, task_id, false, state)
      end
    else
      false -> {:ok, state}
      {:error, close_code} -> {:stop, :normal, close_code, state}
    end
  end

  defp send_failure(topic_id, task_id, already_started, state) do
    if MapSet.member?(state.subscriptions, {@board_topic, topic_id}) do
      case Subscriptions.authorize_board_command(topic_id, state) do
        :ok -> push_payload(failed_frame(topic_id, task_id, already_started), state)
        {:error, close_code} -> {:stop, :normal, close_code, state}
      end
    else
      {:ok, state}
    end
  end

  defp resume_result_unknown(topic_id, source_uid, state) do
    if MapSet.member?(state.subscriptions, {@board_topic, topic_id}) do
      case Subscriptions.authorize_board_command(topic_id, state) do
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

  defp aborted_frame(task_id) do
    %{
      event: @task_aborted_event,
      topic: Contract.topic!("global"),
      topic_id: Contract.topic_id!("global"),
      data: %{task_id: task_id}
    }
  end

  defp failed_frame(topic_id, task_id, already_started) do
    chat_frame(topic_id, @chat_send_failed_event, %{
      task_id: task_id,
      already_started: already_started
    })
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

  defp resume_error_code(%{reason: reason}) do
    case reason do
      :unauthorized -> Contract.close_code!("unauthorized")
      :forbidden -> Contract.close_code!("forbidden")
      reason when reason in [:invalid_data, :conflict] -> Contract.close_code!("invalid_data")
      _ -> Contract.close_code!("internal_error")
    end
  end

  defp resume_error_code(_data), do: Contract.close_code!("internal_error")

  defp forward_send_event(topic_id, _task_id, :accepted, data, state) do
    push_payloads(
      [
        chat_frame(topic_id, @chat_session_event, %{session: data.session}),
        chat_frame(topic_id, @chat_sent_event, %{user_message: data.user_message})
      ],
      state
    )
  end

  defp forward_send_event(topic_id, task_id, :already_started, data, state) do
    push_payloads(
      [
        chat_frame(topic_id, @chat_session_event, %{session: data.session}),
        chat_frame(topic_id, @chat_sent_event, %{user_message: data.user_message}),
        failed_frame(topic_id, task_id, true)
      ],
      state
    )
  end

  defp forward_send_event(topic_id, task_id, :start_failed, %{reason: :conflict}, state) do
    push_payload(failed_frame(topic_id, task_id, true), state)
  end

  defp forward_send_event(topic_id, _task_id, event, data, state)
       when event in [:start, :buffer, :end] do
    push_payload(chat_frame(topic_id, "#{@chat_stream_event}:#{event}", data), state)
  end

  defp forward_send_event(_topic_id, task_id, :cancelled, _data, state) do
    push_payload(aborted_frame(task_id), state)
  end

  defp forward_send_event(topic_id, task_id, _event, _data, state) do
    push_payload(failed_frame(topic_id, task_id, false), state)
  end

  defp chat_frame(topic_id, event, data) do
    %{event: event, topic: @board_topic, topic_id: topic_id, data: data}
  end

  def resume_event({:board_chat_resume_event, topic_id, source_uid, :finished, _data}, state) do
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

  def resume_event({:board_chat_resume_event, topic_id, source_uid, event, data}, state)
      when event in [:start, :buffer, :end, :claim_failed, :result_unknown, :lease_lost] do
    with true <-
           match?(
             {^topic_id, _worker_pid, _monitor_ref, _outcome_received},
             Map.get(state.pending_chat_resumes, source_uid)
           ) and
             MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         :ok <- Subscriptions.authorize_board_command(topic_id, state) do
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

  def run_event({:board_chat_run_event, task_id, event, data}, state) when is_map(data) do
    case Map.get(state.pending_chat_sends, task_id) do
      {_topic_id, _worker_pid, _monitor_ref, true} when event != :accepted ->
        {:ok, state}

      {topic_id, _worker_pid, _monitor_ref, _outcome_received} ->
        with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
             :ok <- Subscriptions.authorize_board_command(topic_id, state) do
          next_state = mark_send_outcome(state, task_id, event)
          forward_send_event(topic_id, task_id, event, data, next_state)
        else
          false -> {:ok, state}
          {:error, close_code} -> {:stop, :normal, close_code, state}
        end

      _ ->
        {:ok, state}
    end
  end

  def cancel_result({:board_chat_cancel_result, task_id, worker_pid, result}, state) do
    case Map.get(state.pending_chat_cancels, task_id) do
      {topic_id, ^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])

        next_state = %{
          state
          | pending_chat_cancels: Map.delete(state.pending_chat_cancels, task_id)
        }

        finish_cancel(topic_id, task_id, result, next_state)

      _ ->
        {:ok, state}
    end
  end

  def down({:DOWN, monitor_ref, :process, worker_pid, _reason}, state) do
    case Enum.find(state.pending_chat_sends, fn {_task_id, {_topic_id, pid, reference, _outcome}} ->
           pid == worker_pid and reference == monitor_ref
         end) do
      {task_id, {topic_id, _worker_pid, _monitor_ref, outcome_received}} ->
        next_state = %{state | pending_chat_sends: Map.delete(state.pending_chat_sends, task_id)}

        if outcome_received,
          do: {:ok, next_state},
          else: send_failure(topic_id, task_id, false, next_state)

      nil ->
        cancel_down(monitor_ref, worker_pid, state)
    end
  end

  defp cancel_down(monitor_ref, worker_pid, state) do
    case Enum.find(state.pending_chat_cancels, fn {_task_id, {_topic_id, pid, reference}} ->
           pid == worker_pid and reference == monitor_ref
         end) do
      {task_id, {topic_id, _pid, _reference}} ->
        next_state = %{
          state
          | pending_chat_cancels: Map.delete(state.pending_chat_cancels, task_id)
        }

        send_failure(topic_id, task_id, false, next_state)

      nil ->
        resume_down(monitor_ref, worker_pid, state)
    end
  end

  defp resume_down(monitor_ref, worker_pid, state) do
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
        :unhandled
    end
  end
end
