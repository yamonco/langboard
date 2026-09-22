defmodule LangboardSocket.RealtimeContract do
  @moduledoc false

  @contract_path Path.expand("../../../shared/realtime/contract.json", __DIR__)
  @external_resource @contract_path
  @contract @contract_path |> File.read!() |> Jason.decode!()
  @topic_values @contract |> Map.fetch!("topics") |> Map.values() |> MapSet.new()
  @client_commands @contract
                   |> get_in(["runtime", "client_commands"])
                   |> Enum.map(&{Map.fetch!(&1, "topic"), Map.fetch!(&1, "event")})
                   |> MapSet.new()
  @broker_consumers @contract
                    |> get_in(["runtime", "broker_consumers"])
                    |> Map.new(&{Map.fetch!(&1, "purpose"), Map.fetch!(&1, "event")})

  def topic!(name), do: get_in(@contract, ["topics", name]) || raise(KeyError, key: name)
  def valid_topic?(topic), do: MapSet.member?(@topic_values, topic)
  def topic_id!(name), do: get_in(@contract, ["topic_ids", name]) || raise(KeyError, key: name)

  def short_uid_length!,
    do:
      get_in(@contract, ["identifiers", "short_uid_length"]) ||
        raise(KeyError, key: "short_uid_length")

  def protocol_limit!(name),
    do: get_in(@contract, ["protocol_limits", name]) || raise(KeyError, key: name)

  def event!(name), do: get_in(@contract, ["events", name]) || raise(KeyError, key: name)
  def client_command?(topic, event), do: MapSet.member?(@client_commands, {topic, event})

  def internal_api_capabilities_path!,
    do: get_in(@contract, ["internal_api", "capabilities_path"])

  def internal_api_contract_version!, do: get_in(@contract, ["internal_api", "contract_version"])
  def broker_schema_version!, do: get_in(@contract, ["broker_envelope", "current_schema_version"])

  def legacy_cache_key_prefix!,
    do: get_in(@contract, ["broker_envelope", "legacy_cache_key_prefix"])

  def legacy_cache_key_max_length!,
    do: get_in(@contract, ["broker_envelope", "legacy_cache_key_max_length"])

  def broker_event!(purpose), do: Map.fetch!(@broker_consumers, purpose)
  def dead_letter_schema_version!, do: get_in(@contract, ["dead_letter", "schema_version"])
  def dead_letter_topic!(purpose), do: get_in(@contract, ["dead_letter", "#{purpose}_topic"])

  def close_code!(name),
    do: get_in(@contract, ["close_codes", name]) || raise(KeyError, key: name)
end
