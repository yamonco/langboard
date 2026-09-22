defmodule LangboardSocket.EditorSyncFrame do
  @moduledoc false

  import Bitwise

  @max_varuint 0xFFFFFFFF

  def decode(frame, max_frame_bytes)
      when is_binary(frame) and is_integer(max_frame_bytes) and max_frame_bytes > 0 do
    if byte_size(frame) > max_frame_bytes do
      {:error, :frame_too_large}
    else
      with {:ok, name_length, rest} <- decode_length(frame, 0, 0),
           true <- name_length > 0 and name_length <= byte_size(rest),
           <<name::binary-size(name_length), message::binary>> <- rest,
           true <- String.valid?(name) and message != <<>> do
        {:ok, name, message}
      else
        {:error, reason} -> {:error, reason}
        _result -> {:error, :invalid_frame}
      end
    end
  end

  def decode(_frame, _max_frame_bytes), do: {:error, :invalid_frame}

  def encode(name, message)
      when is_binary(name) and is_binary(message) and name != <<>> and message != <<>> do
    if String.valid?(name) and byte_size(name) <= @max_varuint do
      {:ok, encode_length(byte_size(name)) <> name <> message}
    else
      {:error, :invalid_frame}
    end
  end

  def encode(_name, _message), do: {:error, :invalid_frame}

  def decode_auth_token(<<2, 0, rest::binary>>) do
    with {:ok, token_length, token} <- decode_length(rest, 0, 0),
         true <- token_length == byte_size(token) and String.valid?(token) do
      {:ok, token}
    else
      _result -> {:error, :invalid_auth_frame}
    end
  end

  def decode_auth_token(_message), do: {:error, :invalid_auth_frame}

  def authenticated(name, writable \\ true) when is_boolean(writable) do
    scope = if writable, do: "read-write", else: "readonly"
    encode(name, <<2, 2>> <> encode_length(byte_size(scope)) <> scope)
  end

  def sync_status(name, saved) when is_boolean(saved),
    do: encode(name, <<8, if(saved, do: 1, else: 0)>>)

  def stateless(name, payload) when is_binary(payload),
    do: encode(name, <<5>> <> encode_length(byte_size(payload)) <> payload)

  def decode_stateless(<<5, rest::binary>>) do
    with {:ok, length, payload} <- decode_length(rest, 0, 0),
         true <- length == byte_size(payload) and String.valid?(payload) do
      {:ok, payload}
    else
      _result -> {:error, :invalid_message}
    end
  end

  def decode_stateless(_message), do: {:error, :invalid_message}

  def normalize_awareness(update, max_entries, user_name)
      when is_binary(update) and is_integer(max_entries) and max_entries > 0 and
             is_binary(user_name) and user_name != "" do
    with {:ok, entries} <- decode_awareness(update, max_entries) do
      encode_awareness(entries, user_name)
    end
  end

  def normalize_awareness(_update, _max_entries, _user_name), do: {:error, :invalid_awareness}

  def decode_awareness(update, max_entries)
      when is_binary(update) and is_integer(max_entries) and max_entries > 0 do
    with {:ok, count, rest} <- decode_length(update, 0, 0),
         true <- count <= max_entries,
         {:ok, entries, <<>>} <- decode_awareness_entries(count, rest, []) do
      {:ok, entries}
    else
      _result -> {:error, :invalid_awareness}
    end
  end

  def decode_awareness(_update, _max_entries), do: {:error, :invalid_awareness}

  def encode_awareness(entries, user_name)
      when is_list(entries) and is_binary(user_name) and user_name != "" do
    Enum.reduce_while(entries, {:ok, [], encode_length(length(entries))}, fn
      %{id: id, clock: clock, state: state}, {:ok, ids, output}
      when is_integer(id) and id in 0..@max_varuint and is_binary(clock) ->
        case normalize_awareness_state(state, user_name) do
          {:ok, encoded_state} ->
            entry = [
              encode_length(id),
              clock,
              encode_length(byte_size(encoded_state)),
              encoded_state
            ]

            {:cont, {:ok, [id | ids], [output, entry]}}

          _result ->
            {:halt, {:error, :invalid_awareness}}
        end

      _entry, _accumulator ->
        {:halt, {:error, :invalid_awareness}}
    end)
    |> case do
      {:ok, ids, output} -> {:ok, Enum.reverse(ids), IO.iodata_to_binary(output)}
      error -> error
    end
  end

  def encode_awareness(_entries, _user_name), do: {:error, :invalid_awareness}

  defp decode_awareness_entries(0, rest, entries),
    do: {:ok, Enum.reverse(entries), rest}

  defp decode_awareness_entries(count, rest, entries) do
    with {:ok, client_id, rest} <- decode_length(rest, 0, 0),
         false <- Enum.any?(entries, fn %{id: id} -> id == client_id end),
         {:ok, clock, clock_value, rest} <- read_clock(rest, <<>>, 0, 0),
         {:ok, state_length, rest} <- decode_length(rest, 0, 0),
         true <- state_length <= byte_size(rest),
         <<state::binary-size(state_length), tail::binary>> <- rest,
         {:ok, decoded_state} <- Jason.decode(state),
         true <- is_map(decoded_state) or is_nil(decoded_state) do
      entry = %{id: client_id, clock: clock, clock_value: clock_value, state: decoded_state}
      decode_awareness_entries(count - 1, tail, [entry | entries])
    else
      _result -> {:error, :invalid_awareness}
    end
  end

  defp read_clock(<<byte, rest::binary>>, encoded, value, shift)
       when byte_size(encoded) < 10 do
    clock = encoded <> <<byte>>
    decoded = value ||| (byte &&& 0x7F) <<< shift

    if (byte &&& 0x80) == 0,
      do: {:ok, clock, decoded, rest},
      else: read_clock(rest, clock, decoded, shift + 7)
  end

  defp read_clock(_rest, _encoded, _value, _shift), do: {:error, :invalid_awareness}

  defp normalize_awareness_state(nil, _user_name), do: {:ok, "null"}

  defp normalize_awareness_state(state, user_name) do
    with true <- is_map(state),
         data when is_map(data) <- Map.get(state, "data", %{}),
         user when is_map(user) or is_nil(user) <- Map.get(state, "user") do
      normalized = Map.put(state, "data", Map.put(data, "name", user_name))

      normalized =
        if user,
          do: Map.put(normalized, "user", Map.put(user, "name", user_name)),
          else: normalized

      Jason.encode(normalized)
    else
      _result -> {:error, :invalid_awareness}
    end
  end

  defp decode_length(<<byte, rest::binary>>, value, shift) when shift <= 28 do
    decoded = value ||| (byte &&& 0x7F) <<< shift

    cond do
      decoded > @max_varuint -> {:error, :invalid_length}
      (byte &&& 0x80) == 0 -> {:ok, decoded, rest}
      true -> decode_length(rest, decoded, shift + 7)
    end
  end

  defp decode_length(_frame, _value, _shift), do: {:error, :invalid_length}

  defp encode_length(value) when value < 0x80, do: <<value>>
  defp encode_length(value), do: <<(value &&& 0x7F) ||| 0x80>> <> encode_length(value >>> 7)
end
