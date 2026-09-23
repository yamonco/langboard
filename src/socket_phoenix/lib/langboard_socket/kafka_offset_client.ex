defmodule LangboardSocket.KafkaOffsetClient do
  @moduledoc false

  alias LangboardSocket.RealtimeContract, as: Contract

  def lag(config) when is_list(config) do
    hosts = config |> Keyword.fetch!(:hosts) |> parse_hosts()
    topic = config |> Keyword.get(:source_topic) |> configured_source_topic()
    group_id = Keyword.fetch!(config, :group_id)
    timeout_ms = Keyword.fetch!(config, :dead_letter_publish_timeout_ms)
    connection_config = [connect_timeout: timeout_ms, request_timeout: timeout_ms]

    with {:ok, hosts} <- hosts,
         {:ok, metadata} <- :brod.get_metadata(hosts, [topic], connection_config),
         {:ok, partitions} <- metadata_partitions(metadata, topic),
         {:ok, responses} <- :brod.fetch_committed_offsets(hosts, connection_config, group_id),
         {:ok, committed} <- committed_offsets(responses, topic, partitions),
         {:ok, earliest} <- source_offsets(hosts, connection_config, topic, partitions, :earliest),
         {:ok, latest} <- source_offsets(hosts, connection_config, topic, partitions, :latest),
         {:ok, lag} <- total_lag(partitions, committed, earliest, latest) do
      {:ok, lag}
    else
      _error -> {:error, :unavailable}
    end
  end

  @doc false
  def total_lag(partitions, committed, earliest, latest) do
    if Enum.all?(partitions, fn partition ->
         Map.fetch!(earliest, partition) <= Map.fetch!(committed, partition) and
           Map.fetch!(committed, partition) <= Map.fetch!(latest, partition)
       end) do
      {:ok,
       Enum.sum(
         Enum.map(partitions, fn partition ->
           Map.fetch!(latest, partition) - Map.fetch!(committed, partition)
         end)
       )}
    else
      {:error, :offset_out_of_range}
    end
  end

  defp parse_hosts(hosts), do: BroadwayKafka.ProducerOptions.validate_hosts(hosts)

  defp metadata_partitions(%{topics: topics}, topic) do
    with %{error_code: :no_error, partitions: partitions} <- find_topic(topics, topic),
         true <- Enum.all?(partitions, &(Map.get(&1, :error_code) == :no_error)) do
      {:ok, partitions |> Enum.map(&Map.fetch!(&1, :partition_index)) |> Enum.sort()}
    else
      _error -> {:error, :topic_unavailable}
    end
  end

  defp metadata_partitions(_metadata, _topic), do: {:error, :topic_unavailable}

  defp committed_offsets(responses, topic, expected_partitions) do
    case find_topic(responses, topic) do
      %{partitions: partitions} ->
        offsets =
          Map.new(partitions, fn partition ->
            {Map.fetch!(partition, :partition_index), Map.fetch!(partition, :committed_offset)}
          end)

        if Enum.all?(expected_partitions, &(Map.get(offsets, &1, -1) >= 0)),
          do: {:ok, offsets},
          else: {:error, :missing_committed_offset}

      _response ->
        {:error, :missing_committed_offset}
    end
  end

  defp source_offsets(hosts, connection_config, topic, partitions, position) do
    Enum.reduce_while(partitions, {:ok, %{}}, fn partition, {:ok, offsets} ->
      case :brod.resolve_offset(hosts, topic, partition, position, connection_config) do
        {:ok, offset} when is_integer(offset) and offset >= 0 ->
          {:cont, {:ok, Map.put(offsets, partition, offset)}}

        _error ->
          {:halt, {:error, :source_offset_unavailable}}
      end
    end)
  end

  defp find_topic(topics, topic), do: Enum.find(topics, &(Map.get(&1, :name) == topic))

  defp configured_source_topic(topic) when is_binary(topic) and topic != "", do: topic
  defp configured_source_topic(_topic), do: Contract.broker_event!("fanout")
end
