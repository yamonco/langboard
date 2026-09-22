defmodule LangboardSocket.GraphStreamDecoder do
  @moduledoc false

  @enforce_keys [:max_buffer_bytes]
  defstruct buffer: <<>>, ended: false, max_buffer_bytes: nil, mode: :graph

  def new(max_buffer_bytes, mode \\ :graph)
      when is_integer(max_buffer_bytes) and max_buffer_bytes > 0 and
             mode in [:graph, :langflow] do
    %__MODULE__{max_buffer_bytes: max_buffer_bytes, mode: mode}
  end

  def feed(%__MODULE__{ended: true}, _chunk), do: {:error, :already_ended}

  def feed(%__MODULE__{} = decoder, chunk) when is_binary(chunk) do
    buffer = decoder.buffer <> chunk
    frames = :binary.split(buffer, "\n\n", [:global])
    remainder = List.last(frames)
    complete_frames = Enum.drop(frames, -1)

    case decode_frames(complete_frames, decoder.max_buffer_bytes, decoder.mode) do
      {:ok, _events, true} when remainder != <<>> ->
        {:error, :data_after_end}

      {:ok, events, ended} when byte_size(remainder) <= decoder.max_buffer_bytes ->
        {:ok, events, %__MODULE__{decoder | buffer: remainder, ended: ended}}

      {:ok, _events, _ended} ->
        {:error, :buffer_too_large}

      error ->
        error
    end
  end

  def finish(%__MODULE__{ended: true, buffer: <<>>}), do: :ok
  def finish(%__MODULE__{}), do: {:error, :incomplete_stream}

  defp decode_frames(frames, max_buffer_bytes, mode) do
    Enum.reduce_while(frames, {:ok, [], false}, &append_frame(&1, &2, max_buffer_bytes, mode))
    |> case do
      {:ok, events, ended} -> {:ok, Enum.reverse(events), ended}
      error -> error
    end
  end

  defp append_frame(<<>>, state, _max_buffer_bytes, _mode), do: {:cont, state}

  defp append_frame(_frame, {:ok, _events, true}, _max_buffer_bytes, _mode),
    do: {:halt, {:error, :data_after_end}}

  defp append_frame(frame, _state, max_buffer_bytes, _mode)
       when byte_size(frame) > max_buffer_bytes,
       do: {:halt, {:error, :buffer_too_large}}

  defp append_frame(frame, {:ok, events, false}, _max_buffer_bytes, mode) do
    case decode_frame(frame, mode) do
      {:ok, nil} -> {:cont, {:ok, events, false}}
      {:ok, event} -> {:cont, {:ok, [event | events], terminal_event?(event)}}
      error -> {:halt, error}
    end
  end

  defp decode_frame(frame, mode) do
    case Jason.decode(frame) do
      {:ok, event} -> decode_event(event, mode)
      _ -> {:error, :invalid_frame}
    end
  end

  defp decode_event(
         %{"event" => "add_message", "data" => %{"sender" => sender, "text" => text}},
         :langflow
       )
       when is_binary(sender) and is_binary(text) do
    if String.downcase(sender) == "user", do: {:ok, nil}, else: {:ok, {:token, text}}
  end

  defp decode_event(%{"event" => "add_message", "data" => %{"text" => text}}, :langflow)
       when is_binary(text),
       do: {:ok, {:token, text}}

  defp decode_event(
         %{"event" => "token", "data" => %{"token" => token, "chunk" => chunk}},
         :langflow
       )
       when token not in [false, nil] and is_binary(chunk),
       do: {:ok, {:token, chunk}}

  defp decode_event(%{"event" => event}, :langflow) when event in ["token", "interrupt"],
    do: {:ok, nil}

  defp decode_event(%{"event" => "token", "data" => %{"chunk" => chunk}}, :graph)
       when is_binary(chunk),
       do: {:ok, {:token, chunk}}

  defp decode_event(%{"event" => "interrupt", "data" => data}, :graph) when is_map(data),
    do: {:ok, {:interrupt, data}}

  defp decode_event(%{"event" => "error", "data" => %{"message" => message}}, :langflow)
       when is_binary(message),
       do: {:ok, {:error, message}}

  defp decode_event(%{"event" => "error", "data" => %{"error" => message}}, _mode)
       when is_binary(message),
       do: {:ok, {:error, message}}

  defp decode_event(%{"event" => "end", "data" => data}, _mode) when is_map(data),
    do: {:ok, :end}

  defp decode_event(%{"event" => event}, _mode)
       when event in ["token", "interrupt", "error", "end"],
       do: {:error, :invalid_frame}

  defp decode_event(%{"event" => _event}, _mode), do: {:ok, nil}
  defp decode_event(_event, _mode), do: {:error, :invalid_frame}

  defp terminal_event?(:end), do: true
  defp terminal_event?({:error, _}), do: true
  defp terminal_event?(_event), do: false
end
