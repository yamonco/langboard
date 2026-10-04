defmodule LangboardSocketWeb.SocketHandler.OllamaCommand do
  @moduledoc false

  alias LangboardSocket.RealtimeContract, as: Contract

  @topic Contract.topic!("ollama_manager")
  @topic_id Contract.topic_id!("global")

  def handle(
        %{"topic" => @topic, "topic_id" => @topic_id} = payload,
        action,
        state,
        capacity_exhausted?
      ) do
    case authorize(state) do
      :ok ->
        case ollama_data(action, Map.get(payload, "data")) do
          {:ok, data} -> start(action, data, state, capacity_exhausted?)
          :error -> {:stop, :normal, Contract.close_code!("invalid_data"), state}
        end

      {:error, close_code} ->
        {:stop, :normal, close_code, state}
    end
  end

  def handle(_payload, _action, state, _capacity_exhausted?),
    do: {:stop, :normal, Contract.close_code!("forbidden"), state}

  def result(reference, worker_pid, result, state) do
    case Map.get(state.pending_ollama, reference) do
      {^worker_pid, monitor_ref} ->
        Process.demonitor(monitor_ref, [:flush])
        finish(result, clear(state, reference))

      _ ->
        {:ok, state}
    end
  end

  def failed(reference, state), do: finish({:error, :unavailable}, clear(state, reference))

  defp authorize(state) do
    with true <- MapSet.member?(state.subscriptions, {@topic, @topic_id}),
         {:ok, accepted} <-
           state.authorization_client.authorize_subscriptions(
             state.authorization_token,
             @topic,
             [@topic_id]
           ),
         true <- @topic_id in accepted do
      :ok
    else
      false -> {:error, Contract.close_code!("forbidden")}
      {:error, reason} -> {:error, authorization_close_code(reason)}
    end
  end

  defp authorization_close_code(:expired_token), do: Contract.close_code!("expired_token")
  defp authorization_close_code(:unauthorized), do: Contract.close_code!("unauthorized")
  defp authorization_close_code(_reason), do: Contract.close_code!("internal_error")

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

  defp start(_action, _data, state, true),
    do: {:stop, :normal, Contract.close_code!("try_again_later"), state}

  defp start(action, data, state, false) do
    owner = self()
    reference = make_ref()
    client = Application.fetch_env!(:langboard_socket, :ollama_client)
    token = state.authorization_token

    execute_command = fn ->
      send(owner, {:ollama_command, reference, self(), client.execute(token, action, data)})
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
    %{state | pending_ollama: Map.delete(state.pending_ollama, reference)}
  end
end
