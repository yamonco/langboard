defmodule LangboardSocket.GraphResumeClient do
  @moduledoc false

  def resume(thread_id, session_id, decision)
      when is_binary(thread_id) and thread_id != "" and is_binary(session_id) and
             session_id != "" and is_map(decision) do
    base_url = Application.fetch_env!(:langboard_socket, :graph_internal_url)
    timeout = Application.fetch_env!(:langboard_socket, :graph_timeout_ms)
    max_message_bytes = Application.fetch_env!(:langboard_socket, :graph_stream_max_chunk_bytes)
    url = base_url <> "/api/v1/graph/resume/" <> URI.encode(thread_id, &URI.char_unreserved?/1)

    request =
      Finch.build(
        :post,
        url,
        [{"accept", "application/json"}, {"content-type", "application/json"}],
        Jason.encode!(%{resume: decision, session_id: session_id})
      )

    initial = %{status: nil, body: <<>>, error: nil}

    case Finch.stream_while(
           request,
           LangboardSocket.GraphFinch,
           initial,
           &collect_response(&1, &2, max_message_bytes * 3),
           pool_timeout: timeout,
           receive_timeout: timeout,
           request_timeout: timeout
         ) do
      {:ok, %{status: 200, error: nil, body: body}} ->
        decode_response(body, thread_id, session_id, max_message_bytes)

      {:ok, %{error: error}} when not is_nil(error) ->
        {:error, error}

      {:ok, _state} ->
        {:error, :invalid_response}

      {:error, _reason, _state} ->
        {:error, :unavailable}
    end
  end

  def resume(_thread_id, _session_id, _decision), do: {:error, :invalid_data}

  defp collect_response({:status, 200}, state, _limit), do: {:cont, %{state | status: 200}}
  defp collect_response({:status, 409}, state, _limit), do: {:halt, %{state | error: :conflict}}

  defp collect_response({:status, _status}, state, _limit),
    do: {:halt, %{state | error: :upstream_status}}

  defp collect_response({:data, chunk}, %{status: 200} = state, limit) do
    if byte_size(state.body) + byte_size(chunk) <= limit do
      {:cont, %{state | body: state.body <> chunk}}
    else
      {:halt, %{state | error: :response_too_large}}
    end
  end

  defp collect_response(_message, state, _limit), do: {:cont, state}

  defp decode_response(body, thread_id, session_id, max_message_bytes) do
    case Jason.decode(body) do
      {:ok,
       %{
         "thread_id" => ^thread_id,
         "session_id" => ^session_id,
         "message" => message,
         "interrupts" => interrupts
       }}
      when is_binary(message) and byte_size(message) <= max_message_bytes ->
        case interrupts do
          [] ->
            {:ok, %{response_text: message, interrupt: nil}}

          [%{"value" => %{"thread_id" => ^thread_id, "session_id" => ^session_id}} = interrupt] ->
            {:ok, %{response_text: message, interrupt: interrupt}}

          _ ->
            {:error, :invalid_response}
        end

      _ ->
        {:error, :invalid_response}
    end
  end
end
