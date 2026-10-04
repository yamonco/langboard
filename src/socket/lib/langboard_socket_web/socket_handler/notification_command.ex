defmodule LangboardSocketWeb.SocketHandler.NotificationCommand do
  @moduledoc false

  alias LangboardSocket.RealtimeContract, as: Contract

  @topic Contract.topic!("none")
  @topic_id Contract.topic_id!("none")
  @short_uid_length Contract.short_uid_length!()

  def handle(%{"topic" => @topic} = payload, action, state, capacity_exhausted?) do
    if Map.get(payload, "topic_id") in [nil, @topic_id] do
      case notification_uid(payload, action) do
        {:ok, uid} -> start(action, uid, state, capacity_exhausted?)
        {:error, :invalid_data} -> {:stop, :normal, Contract.close_code!("invalid_data"), state}
      end
    else
      {:stop, :normal, Contract.close_code!("forbidden"), state}
    end
  end

  def handle(_payload, _action, state, _capacity_exhausted?),
    do: {:stop, :normal, Contract.close_code!("forbidden"), state}

  def result(reference, worker_pid, result, state) do
    case Map.get(state.pending_notifications, reference) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])
        finish(result, clear(state, reference))

      _ ->
        {:ok, state}
    end
  end

  def failed(reference, state), do: finish({:error, :unavailable}, clear(state, reference))

  defp notification_uid(%{"data" => %{"uid" => uid}}, action)
       when action in [:read, :delete] and is_binary(uid) and byte_size(uid) == @short_uid_length do
    if String.match?(uid, ~r/\A[0-9A-Za-z]+\z/),
      do: {:ok, uid},
      else: {:error, :invalid_data}
  end

  defp notification_uid(_payload, action) when action in [:read, :delete],
    do: {:error, :invalid_data}

  defp notification_uid(_payload, _action), do: {:ok, nil}

  defp start(_action, _uid, state, true),
    do: {:stop, :normal, Contract.close_code!("try_again_later"), state}

  defp start(action, uid, state, false) do
    owner = self()
    reference = make_ref()
    client = Application.fetch_env!(:langboard_socket, :notification_client)
    token = state.authorization_token

    execute_command = fn ->
      send(owner, {:notification_command, reference, self(), client.execute(token, action, uid)})
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

  defp finish(:ok, state), do: {:ok, state}

  defp finish({:error, reason}, state) do
    close_code =
      case reason do
        :unauthorized -> Contract.close_code!("unauthorized")
        :forbidden -> Contract.close_code!("forbidden")
        :invalid_data -> Contract.close_code!("invalid_data")
        _ -> Contract.close_code!("internal_error")
      end

    {:stop, :normal, close_code, state}
  end

  defp clear(state, reference) do
    %{state | pending_notifications: Map.delete(state.pending_notifications, reference)}
  end
end
