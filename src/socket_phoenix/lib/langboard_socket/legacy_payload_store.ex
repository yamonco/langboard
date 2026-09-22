defmodule LangboardSocket.LegacyPayloadStore do
  @moduledoc false

  @connection __MODULE__.Connection

  def child_spec(config) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [config]},
      type: :worker,
      restart: :permanent,
      shutdown: 5_000
    }
  end

  def start_link(config) do
    url = config |> Keyword.fetch!(:url) |> require_url!()
    Redix.start_link(url, name: @connection, sync_connect: false)
  end

  def ready?, do: command(["PING"], timeout: 250) == {:ok, "PONG"}

  def fetch(cache_key, max_payload_bytes) do
    case command(["GET", cache_key]) do
      {:ok, nil} -> {:error, :legacy_payload_missing}
      {:ok, payload} -> decode(payload, max_payload_bytes)
      {:error, _reason} -> {:error, :legacy_store_unavailable}
    end
  end

  @doc false
  def decode(payload, max_payload_bytes)
      when is_binary(payload) and is_integer(max_payload_bytes) and max_payload_bytes > 0 do
    if byte_size(payload) > max_payload_bytes do
      {:error, :legacy_payload_too_large}
    else
      case Jason.decode(payload) do
        {:ok, value} when is_map(value) -> {:ok, value}
        _result -> {:error, :invalid_legacy_payload}
      end
    end
  end

  def decode(_payload, _max_payload_bytes), do: {:error, :invalid_legacy_payload}

  defp command(command, options \\ []) do
    Redix.command(@connection, command, options)
  catch
    :exit, _reason -> {:error, :connection_unavailable}
  end

  defp require_url!(url) when is_binary(url) and url != "", do: url
  defp require_url!(_url), do: raise("Missing legacy Redis configuration: url")
end
