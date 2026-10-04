defmodule LangboardSocketWeb.SocketHandler.BoardQuery do
  @moduledoc false

  import LangboardSocketWeb.SocketHandler.Outbound, only: [push_payload: 2]

  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocketWeb.SocketHandler.State
  alias LangboardSocketWeb.SocketHandler.Subscriptions

  @board_topic Contract.topic!("board")
  @bot_status_event Contract.event!("board_bot_status_map")
  @chat_available_event Contract.event!("board_chat_available")

  def handle_bot_status(%{"topic" => @board_topic, "topic_id" => topic_id}, state)
      when is_binary(topic_id) and topic_id != "" do
    case Subscriptions.authorize_board_command(topic_id, state) do
      :ok ->
        start_bot_status(topic_id, state)

      {:error, close_code} ->
        Subscriptions.handle_board_authorization_error(topic_id, close_code, state)
    end
  end

  def handle_bot_status(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  def bot_status_result(topic_id, result, state) do
    with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         :ok <- Subscriptions.authorize_board_command(topic_id, state) do
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
      false ->
        {:ok, state}

      {:error, close_code} ->
        Subscriptions.handle_board_authorization_error(topic_id, close_code, state)
    end
  end

  def handle_chat_availability(%{"topic" => @board_topic, "topic_id" => topic_id}, state)
      when is_binary(topic_id) and topic_id != "" do
    case Subscriptions.authorize_board_command(topic_id, state) do
      :ok ->
        start_chat_availability(topic_id, state)

      {:error, close_code} ->
        Subscriptions.handle_board_authorization_error(topic_id, close_code, state)
    end
  end

  def handle_chat_availability(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  def chat_availability_result(topic_id, result, state) do
    with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         :ok <- Subscriptions.authorize_board_command(topic_id, state) do
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
      false ->
        {:ok, state}

      {:error, close_code} ->
        Subscriptions.handle_board_authorization_error(topic_id, close_code, state)
    end
  end

  defp start_bot_status(topic_id, state) do
    cond do
      Map.has_key?(state.pending_bot_status, topic_id) ->
        {:ok, state}

      State.command_capacity_exhausted?(state) ->
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

  defp start_chat_availability(topic_id, state) do
    cond do
      Map.has_key?(state.pending_chat_availability, topic_id) ->
        {:ok, state}

      State.command_capacity_exhausted?(state) ->
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
end
