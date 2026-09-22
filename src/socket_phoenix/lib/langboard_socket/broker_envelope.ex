defmodule LangboardSocket.BrokerEnvelope do
  @moduledoc false

  alias LangboardSocket.RealtimeContract, as: Contract

  @enforce_keys [:data, :event, :event_id, :occurred_at]
  defstruct @enforce_keys

  def decode(payload, topic) when is_binary(payload) and is_binary(topic) do
    case Jason.decode(payload) do
      {:ok, value} when is_map(value) ->
        if Map.has_key?(value, "schema_version") do
          decode_inline(value, topic)
        else
          decode_legacy(value)
        end

      _reason ->
        {:error, :invalid_broker_envelope}
    end
  end

  def decode(_payload, _topic), do: {:error, :invalid_broker_envelope}

  defp decode_inline(value, topic) do
    with true <- value["schema_version"] == Contract.broker_schema_version!(),
         event_id when is_binary(event_id) and event_id != "" <- value["event_id"],
         ^topic <- value["event"],
         occurred_at when is_binary(occurred_at) <- value["occurred_at"],
         {:ok, parsed_at, _offset} <- DateTime.from_iso8601(occurred_at),
         data when is_map(data) <- value["data"] do
      {:ok,
       %__MODULE__{
         data: data,
         event: topic,
         event_id: event_id,
         occurred_at: parsed_at
       }}
    else
      _reason -> {:error, :invalid_broker_envelope}
    end
  end

  defp decode_legacy(value) do
    cache_key = value["cache_key"]

    if valid_legacy_cache_key?(cache_key),
      do: {:legacy, cache_key},
      else: {:error, :invalid_broker_envelope}
  end

  defp valid_legacy_cache_key?(cache_key) when is_binary(cache_key) do
    byte_size(cache_key) <= Contract.legacy_cache_key_max_length!() and
      String.starts_with?(cache_key, Contract.legacy_cache_key_prefix!())
  end

  defp valid_legacy_cache_key?(_cache_key), do: false
end
