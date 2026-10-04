defmodule LangboardSocketWeb.SocketHandler.State do
  @moduledoc false

  alias LangboardSocket.RealtimeContract, as: Contract

  @board_topic Contract.topic!("board")

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

  def clear_pending_bot_status(state, topic_id) do
    %{state | pending_bot_status: Map.delete(state.pending_bot_status, topic_id)}
  end

  def clear_pending_chat_availability(state, topic_id) do
    %{state | pending_chat_availability: Map.delete(state.pending_chat_availability, topic_id)}
  end

  def cancel_board_queries_for(state, removed) do
    Enum.reduce([:pending_bot_status, :pending_chat_availability], state, fn field, state ->
      Enum.reduce(removed, state, fn
        {@board_topic, topic_id}, state -> cancel_pending(state, field, topic_id)
        _subscription, state -> state
      end)
    end)
  end

  def command_capacity_exhausted?(state) do
    pending_command_count(state) >=
      Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands)
  end

  defp cancel_pending(state, field, topic_id) do
    case Map.get(Map.fetch!(state, field), topic_id) do
      {worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])
        Task.Supervisor.terminate_child(LangboardSocket.CommandTaskSupervisor, worker_pid)
        Map.update!(state, field, &Map.delete(&1, topic_id))

      nil ->
        state
    end
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
end
