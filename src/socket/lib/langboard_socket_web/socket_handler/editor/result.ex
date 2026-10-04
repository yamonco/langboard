defmodule LangboardSocketWeb.SocketHandler.Editor.Result do
  @moduledoc false

  import LangboardSocketWeb.SocketHandler.Outbound, only: [push_payload: 2]

  alias LangboardSocket.RealtimeContract, as: Contract

  @editor_status_result_event Contract.event!("editor_ai_status_result")
  @editor_approval_resume_result_event Contract.event!("editor_approval_resume_result")
  @notification_topic Contract.topic!("none")
  @notification_topic_id Contract.topic_id!("none")

  def result({:editor_resume_event, approval_uid, event, data}, state)
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

  def result({:editor_run_event, task_id, event, data}, state) when is_map(data) do
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

  def result({:editor_status, task_id, worker_pid, result}, state) do
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

  def result({:editor_cancel, reference, worker_pid, task_id, result}, state) do
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

  def detach(state) do
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

    :ok
  end

  def down({:DOWN, monitor_ref, :process, worker_pid, _reason} = message, state) do
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
        handle_editor_status_down(message, state)
    end
  end

  defp handle_editor_status_down({:DOWN, monitor_ref, :process, worker_pid, _reason}, state) do
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
        handle_editor_cancel_down(monitor_ref, worker_pid, state)
    end
  end

  defp handle_editor_cancel_down(monitor_ref, worker_pid, state) do
    case Enum.find(state.pending_editor_cancels, fn {_reference, task} ->
           task == {worker_pid, monitor_ref}
         end) do
      {reference, _task} ->
        {:ok,
         %{state | pending_editor_cancels: Map.delete(state.pending_editor_cancels, reference)}}

      nil ->
        :unhandled
    end
  end

  defp finish_editor_cancel(task_id, {:ok, run_uid}, state) do
    finish_editor_status(task_id, {:ok, %{"run_uid" => run_uid, "status" => "cancelled"}}, state)
  end

  defp finish_editor_cancel(task_id, {:error, _reason} = error, state),
    do: finish_editor_status(task_id, error, state)

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

  defp editor_resume_error_code(reason)
       when reason in [:conflict, :forbidden, :unauthorized, :invalid_data],
       do: Atom.to_string(reason)

  defp editor_resume_error_code(_reason), do: "unavailable"

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
end
