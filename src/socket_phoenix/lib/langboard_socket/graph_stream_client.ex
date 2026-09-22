defmodule LangboardSocket.GraphStreamClient do
  @moduledoc false

  alias LangboardSocket.GraphStreamDecoder

  def stream(session_id, request_body, on_event)
      when is_binary(session_id) and session_id != "" and is_map(request_body) and
             is_function(on_event, 1) do
    base_url = Application.fetch_env!(:langboard_socket, :graph_internal_url)

    url =
      base_url <>
        "/api/v1/graph/run/" <>
        URI.encode(session_id, &URI.char_unreserved?/1) <> "?stream=true"

    stream_http(url, [{"accept", "application/json"}], request_body, :graph, on_event)
  end

  def stream_http(url, headers, request_body, mode, on_event)
      when is_binary(url) and is_list(headers) and is_map(request_body) and
             mode in [:graph, :langflow] and is_function(on_event, 1) do
    timeout = Application.fetch_env!(:langboard_socket, :graph_timeout_ms)
    max_chunk_bytes = Application.fetch_env!(:langboard_socket, :graph_stream_max_chunk_bytes)

    request =
      Finch.build(
        :post,
        url,
        [{"content-type", "application/json"} | headers],
        Jason.encode!(request_body)
      )

    state = %{
      decoder: GraphStreamDecoder.new(max_chunk_bytes, mode),
      error: nil,
      upstream_error: false,
      status: nil
    }

    case Finch.stream_while(
           request,
           LangboardSocket.GraphFinch,
           state,
           &handle_response(&1, &2, on_event, max_chunk_bytes),
           pool_timeout: timeout,
           receive_timeout: timeout,
           request_timeout: timeout
         ) do
      {:ok, state} ->
        finish_response(state, mode, on_event)

      {:error, _reason, _state} ->
        {:error, :unavailable}
    end
  end

  defp finish_response(
         %{error: nil, status: 200, decoder: decoder, upstream_error: upstream_error},
         mode,
         on_event
       ) do
    with :ok <- GraphStreamDecoder.finish(decoder),
         false <- upstream_error do
      case on_event.(:end) do
        :ok -> :ok
        {:error, reason} -> {:error, {:downstream, reason}}
        _result -> {:error, :invalid_callback}
      end
    else
      true -> {:error, if(mode == :graph, do: :graph_error, else: :upstream_error)}
      error -> error
    end
  end

  defp finish_response(%{error: error}, _mode, _on_event) when not is_nil(error),
    do: {:error, error}

  defp finish_response(_state, _mode, _on_event), do: {:error, :invalid_response}

  defp handle_response({:status, 200}, state, _on_event, _max_chunk_bytes),
    do: {:cont, %{state | status: 200}}

  defp handle_response({:status, _status}, state, _on_event, _max_chunk_bytes),
    do: {:halt, %{state | error: :upstream_status}}

  defp handle_response({:data, chunk}, %{status: 200} = state, on_event, max_chunk_bytes) do
    if byte_size(chunk) > max_chunk_bytes do
      {:halt, %{state | error: :chunk_too_large}}
    else
      case GraphStreamDecoder.feed(state.decoder, chunk) do
        {:ok, events, decoder} ->
          dispatch_events(events, on_event, %{state | decoder: decoder})

        {:error, reason} ->
          {:halt, %{state | error: reason}}
      end
    end
  end

  defp handle_response({:data, _chunk}, state, _on_event, _max_chunk_bytes),
    do: {:halt, %{state | error: :invalid_response}}

  defp handle_response(_message, state, _on_event, _max_chunk_bytes), do: {:cont, state}

  defp dispatch_events(events, on_event, state) do
    Enum.reduce_while(events, {:cont, state}, fn
      :end, accumulator ->
        {:cont, accumulator}

      event, {:cont, current_state} ->
        next_state = %{
          current_state
          | upstream_error: current_state.upstream_error or match?({:error, _}, event)
        }

        case on_event.(event) do
          :ok -> {:cont, {:cont, next_state}}
          {:error, reason} -> {:halt, {:halt, %{next_state | error: {:downstream, reason}}}}
          _result -> {:halt, {:halt, %{next_state | error: :invalid_callback}}}
        end
    end)
  end
end
