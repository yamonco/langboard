defmodule LangboardSocketWeb.EditorSyncHandler do
  @moduledoc false
  @behaviour WebSock

  alias LangboardSocket.EditorDocument
  alias LangboardSocket.EditorSyncFrame
  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocketWeb.Telemetry

  @unauthorized 4401
  @forbidden 4403
  @invalid_data 1007
  @internal_error 1011
  @try_again_later 1013

  defmodule State do
    @moduledoc false
    @derive {Inspect, only: [:directory, :documents, :max_payload]}
    @enforce_keys [
      :authorization_client,
      :directory,
      :documents,
      :max_payload,
      :ping_interval,
      :token
    ]
    defstruct @enforce_keys
  end

  @impl true
  def init({token, directory, max_payload, ping_interval}) do
    schedule_ping(ping_interval)
    Telemetry.emit_connection_change(1)

    state = %State{
      authorization_client: Application.fetch_env!(:langboard_socket, :authorization_client),
      directory: directory,
      documents: %{},
      max_payload: max_payload,
      ping_interval: ping_interval,
      token: token
    }

    case LangboardSocket.RuntimeStatus.register_socket() do
      :ok -> {:ok, state}
      {:error, :draining} -> {:stop, :normal, Contract.close_code!("service_restart"), state}
    end
  end

  @impl true
  def handle_in({payload, opcode: :binary}, state) do
    case EditorSyncFrame.decode(payload, state.max_payload) do
      {:ok, name, <<2, _rest::binary>> = message} ->
        handle_auth(name, message, state)

      {:ok, name, message} ->
        with {:ok, server, next_state, initial, user_name, writable} <-
               ensure_document(name, state.token, state),
             {:ok, result} <-
               handle_document_message(server, name, message, user_name, writable) do
          push_frames(initial ++ result, next_state)
        else
          {:stop, code} -> {:stop, :normal, code, state}
          {:error, :forbidden} -> {:stop, :normal, @forbidden, state}
          {:error, :invalid_message} -> {:stop, :normal, @invalid_data, state}
          _result -> {:stop, :normal, @internal_error, state}
        end

      {:error, :frame_too_large} ->
        {:stop, :normal, 1009, state}

      {:error, _reason} ->
        {:stop, :normal, @invalid_data, state}
    end
  end

  def handle_in({_payload, opcode: :text}, state), do: {:stop, :normal, 1003, state}

  @impl true
  def handle_info(:socket_drain, state),
    do: {:stop, :normal, Contract.close_code!("service_restart"), state}

  def handle_info({:editor_document_update, name, update}, state) do
    if Map.has_key?(state.documents, name) do
      case authorize_document(name, state) do
        {:ok, _user_name, _writable} ->
          {:ok, message} = Yex.Sync.message_encode({:sync, {:sync_update, update}})
          push_frames([{name, message}], state)

        {:stop, code} ->
          {:stop, :normal, code, state}
      end
    else
      {:ok, state}
    end
  end

  def handle_info({:editor_document_awareness, name, update}, state) do
    if Map.has_key?(state.documents, name) do
      case authorize_document(name, state) do
        {:ok, _user_name, _writable} ->
          {:ok, message} = Yex.Sync.message_encode({:awareness, update})
          push_frames([{name, message}], state)

        {:stop, code} ->
          {:stop, :normal, code, state}
      end
    else
      {:ok, state}
    end
  end

  def handle_info({:editor_document_stateless, name, frame}, state) do
    if Map.has_key?(state.documents, name) do
      case authorize_document(name, state) do
        {:ok, _user_name, _writable} -> push_frames([{name, frame, :encoded}], state)
        {:stop, code} -> {:stop, :normal, code, state}
      end
    else
      {:ok, state}
    end
  end

  def handle_info({:editor_document_closed, name, _reason}, state) do
    if Map.has_key?(state.documents, name),
      do: {:stop, :normal, @internal_error, state},
      else: {:ok, state}
  end

  def handle_info({:DOWN, monitor, :process, _pid, _reason}, state) do
    if Enum.any?(state.documents, fn {_name, {_pid, reference}} -> reference == monitor end),
      do: {:stop, :normal, @internal_error, state},
      else: {:ok, state}
  end

  def handle_info(:ping, state) do
    authorization =
      Enum.find_value(state.documents, fn {name, _server} ->
        case authorize_document(name, state) do
          {:ok, _user_name, _writable} -> nil
          denied -> denied
        end
      end)

    case authorization do
      nil ->
        schedule_ping(state.ping_interval)
        push_frame({:ping, ""}, state)

      {:stop, code} ->
        {:stop, :normal, code, state}
    end
  end

  def handle_info(_message, state), do: {:ok, state}

  @impl true
  def terminate(_reason, %State{} = state) do
    Enum.each(state.documents, fn {_name, {_server, monitor}} ->
      Process.demonitor(monitor, [:flush])
    end)

    Telemetry.emit_connection_change(-1)
    :ok
  end

  defp handle_auth(name, message, state) do
    with {:ok, requested_token} <- EditorSyncFrame.decode_auth_token(message),
         token <- if(requested_token == "", do: state.token, else: requested_token),
         true <-
           is_binary(token) and token != "" and
             (state.documents == %{} or token == state.token),
         {:ok, _server, next_state, initial, _user_name, writable} <-
           ensure_document(name, token, state),
         {:ok, authenticated} <- EditorSyncFrame.authenticated(name, writable) do
      push_frames([{name, authenticated, :encoded} | initial], next_state)
    else
      {:stop, code} -> {:stop, :normal, code, state}
      {:error, :invalid_auth_frame} -> {:stop, :normal, @invalid_data, state}
      _result -> {:stop, :normal, @unauthorized, state}
    end
  end

  defp ensure_document(name, token, state) do
    cond do
      not is_binary(token) or token == "" ->
        {:stop, @unauthorized}

      byte_size(name) > 512 ->
        {:stop, 1009}

      map_size(state.documents) >=
        Application.fetch_env!(:langboard_socket, :editor_sync_max_documents_per_connection) and
          not Map.has_key?(state.documents, name) ->
        {:stop, @try_again_later}

      true ->
        authorize_and_join(name, token, state)
    end
  end

  defp authorize_and_join(name, token, state) do
    authorized_state = %{state | token: token}

    case authorize_document(name, authorized_state) do
      {:ok, user_name, writable} ->
        case Map.get(state.documents, name) do
          {server, _monitor} -> {:ok, server, authorized_state, [], user_name, writable}
          nil -> join_document(name, token, state, user_name, writable)
        end

      denied ->
        denied
    end
  end

  defp authorize_document(name, state) do
    case state.authorization_client.authorize_editor_document(state.token, name) do
      {:ok, user_name, writable} -> {:ok, user_name, writable}
      {:error, :forbidden} -> {:stop, @forbidden}
      {:error, :unauthorized} -> {:stop, @unauthorized}
      {:error, :expired_token} -> {:stop, @unauthorized}
      _result -> {:stop, @internal_error}
    end
  end

  defp join_document(name, token, state, user_name, writable) do
    with {:ok, server} <- EditorDocument.ensure_started(name, state.directory),
         {:ok, messages} <- call_document(fn -> EditorDocument.join(server, self()) end) do
      monitor = Process.monitor(server)
      documents = Map.put(state.documents, name, {server, monitor})
      initial = Enum.map(messages, &{name, &1})
      {:ok, server, %{state | documents: documents, token: token}, initial, user_name, writable}
    else
      {:error, :too_many_clients} -> {:stop, @try_again_later}
      _result -> {:stop, @internal_error}
    end
  end

  defp handle_document_message(
         _server,
         _name,
         <<5, _rest::binary>>,
         _user_name,
         false
       ),
       do: {:error, :forbidden}

  defp handle_document_message(
         server,
         _name,
         <<5, _rest::binary>> = message,
         _user_name,
         true
       ) do
    with {:ok, payload} <- EditorSyncFrame.decode_stateless(message),
         {:ok, %{"type" => "rich_patch_prepared", "request_id" => id, "update" => encoded}} <-
           Jason.decode(payload),
         true <- is_binary(id) and byte_size(id) == 32 and is_binary(encoded),
         {:ok, update} <- Base.decode64(encoded),
         :ok <-
           call_document(fn -> EditorDocument.apply_rich_patch(server, self(), id, update) end) do
      {:ok, []}
    else
      _result -> {:error, :invalid_message}
    end
  end

  defp handle_document_message(server, name, message, user_name, writable) do
    handle_decoded_message(
      Yex.Sync.message_decode(message),
      server,
      name,
      user_name,
      writable
    )
  end

  defp handle_decoded_message(
         {:ok, {:sync, {:sync_step1, vector}}},
         server,
         name,
         _user_name,
         _writable
       ) do
    case call_document(fn -> EditorDocument.sync_step1(server, self(), vector) end) do
      {:ok, reply} -> {:ok, [{name, reply}]}
      _result -> {:error, :document_unavailable}
    end
  end

  defp handle_decoded_message(
         {:ok, {:sync, {kind, _update}}},
         _server,
         name,
         _user_name,
         false
       )
       when kind in [:sync_step2, :sync_update] do
    {:ok, status} = EditorSyncFrame.sync_status(name, false)
    {:ok, [{name, status, :encoded}]}
  end

  defp handle_decoded_message({:ok, {:sync, {kind, update}}}, server, name, _user_name, true)
       when kind in [:sync_step2, :sync_update] do
    case call_document(fn -> EditorDocument.apply_update(server, self(), update) end) do
      :ok ->
        {:ok, status} = EditorSyncFrame.sync_status(name, true)
        {:ok, [{name, status, :encoded}]}

      _result ->
        {:error, :document_unavailable}
    end
  end

  defp handle_decoded_message(
         {:ok, {:awareness, update}},
         server,
         _name,
         user_name,
         _writable
       ) do
    case call_document(fn ->
           EditorDocument.apply_awareness(server, self(), update, user_name)
         end) do
      :ok -> {:ok, []}
      {:error, :invalid_awareness} -> {:error, :invalid_message}
      _result -> {:error, :document_unavailable}
    end
  end

  defp handle_decoded_message(
         {:ok, :query_awareness},
         server,
         name,
         _user_name,
         _writable
       ) do
    with {:ok, update} <- call_document(fn -> EditorDocument.query_awareness(server, self()) end),
         {:ok, reply} <- Yex.Sync.message_encode({:awareness, update}) do
      {:ok, [{name, reply}]}
    else
      _result ->
        {:error, :document_unavailable}
    end
  end

  defp handle_decoded_message(_result, _server, _name, _user_name, _writable),
    do: {:error, :invalid_message}

  defp push_frames(messages, state) do
    queue_size = message_queue_length()
    max_queue = Application.fetch_env!(:langboard_socket, :socket_max_outbound_queue_messages)

    if queue_size + length(messages) > max_queue do
      Telemetry.emit_slow_client(queue_size)
      {:stop, :normal, @try_again_later, state}
    else
      case encode_frames(messages, state.max_payload) do
        {:ok, []} -> {:ok, state}
        {:ok, [frame]} -> push_frame(frame, state, queue_size)
        {:ok, frames} -> push_frames(frames, state, queue_size)
        {:error, :frame_too_large} -> {:stop, :normal, 1009, state}
        {:error, _reason} -> {:stop, :normal, @internal_error, state}
      end
    end
  end

  defp push_frame(frame, state), do: push_frame(frame, state, message_queue_length())

  defp push_frame({_opcode, payload} = frame, state, queue_size) do
    Telemetry.emit_outbound(byte_size(payload), queue_size)
    {:push, frame, state}
  end

  defp push_frames(frames, state, queue_size) do
    Enum.each(frames, fn {_opcode, payload} ->
      Telemetry.emit_outbound(byte_size(payload), queue_size)
    end)

    {:push, frames, state}
  end

  defp encode_frames(messages, max_payload) do
    Enum.reduce_while(messages, {:ok, []}, fn message, {:ok, frames} ->
      result =
        case message do
          {_name, frame, :encoded} -> {:ok, frame}
          {name, body} -> EditorSyncFrame.encode(name, body)
        end

      case result do
        {:ok, frame} when byte_size(frame) <= max_payload ->
          {:cont, {:ok, [{:binary, frame} | frames]}}

        {:ok, _frame} ->
          {:halt, {:error, :frame_too_large}}

        {:error, _reason} = error ->
          {:halt, error}
      end
    end)
    |> case do
      {:ok, frames} -> {:ok, Enum.reverse(frames)}
      error -> error
    end
  end

  defp call_document(fun) do
    fun.()
  catch
    :exit, _reason -> {:error, :document_unavailable}
  end

  defp message_queue_length, do: Process.info(self(), :message_queue_len) |> elem(1)
  defp schedule_ping(interval), do: Process.send_after(self(), :ping, interval)
end
