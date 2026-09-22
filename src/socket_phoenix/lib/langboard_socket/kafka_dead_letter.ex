defmodule LangboardSocket.KafkaDeadLetter do
  @moduledoc false

  use GenServer

  alias LangboardSocket.RealtimeContract, as: Contract

  @client_id __MODULE__.Client

  def start_link(config), do: GenServer.start_link(__MODULE__, config, name: __MODULE__)

  def ready? do
    case Process.whereis(__MODULE__) do
      pid when is_pid(pid) -> GenServer.call(pid, :ready)
      nil -> false
    end
  catch
    :exit, _reason -> false
  end

  def publish(record, timeout_ms) do
    GenServer.call(__MODULE__, {:publish, record}, timeout_ms + 500)
  catch
    :exit, _reason -> {:error, :dead_letter_unavailable}
  end

  @impl true
  def init(config) do
    hosts = config |> Keyword.fetch!(:hosts) |> parse_hosts!()
    topic = configured_topic(Keyword.fetch!(config, :dead_letter_topic))
    timeout_ms = positive_integer!(Keyword.fetch!(config, :dead_letter_publish_timeout_ms))

    producer_config = [
      required_acks: -1,
      ack_timeout: timeout_ms,
      max_retries: 0,
      partition_buffer_limit: 1
    ]

    client_config = [
      connect_timeout: timeout_ms,
      request_timeout: max(timeout_ms, 1_000),
      allow_topic_auto_creation: true,
      auto_start_producers: true,
      default_producer_config: producer_config
    ]

    case :brod.start_link_client(hosts, @client_id, client_config) do
      {:ok, client} -> {:ok, %{client: client, topic: topic}}
      {:error, reason} -> {:stop, {:dead_letter_start_failed, reason}}
    end
  end

  @impl true
  def handle_call(:ready, _from, state), do: {:reply, Process.alive?(state.client), state}

  def handle_call({:publish, record}, _from, state) do
    result =
      with {:ok, payload} <- Jason.encode(record),
           key <- dead_letter_key(record),
           :ok <- :brod.produce_sync(state.client, state.topic, :hash, key, payload) do
        :ok
      else
        _reason -> {:error, :dead_letter_unavailable}
      end

    {:reply, result, state}
  catch
    :exit, _reason -> {:reply, {:error, :dead_letter_unavailable}, state}
  end

  defp configured_topic(topic) when is_binary(topic) and topic != "", do: topic
  defp configured_topic(_topic), do: Contract.dead_letter_topic!("fanout")

  defp dead_letter_key(%{"event_id" => event_id}) when is_binary(event_id) and event_id != "",
    do: event_id

  defp dead_letter_key(record), do: Map.fetch!(record, "payload_sha256")

  defp parse_hosts!(hosts) do
    case BroadwayKafka.ProducerOptions.validate_hosts(hosts) do
      {:ok, parsed_hosts} -> parsed_hosts
      {:error, reason} -> raise ArgumentError, reason
    end
  end

  defp positive_integer!(value) when is_integer(value) and value > 0, do: value

  defp positive_integer!(value),
    do: raise(ArgumentError, "expected a positive integer, got: #{inspect(value)}")
end
