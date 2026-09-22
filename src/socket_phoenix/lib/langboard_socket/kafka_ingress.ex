defmodule LangboardSocket.KafkaIngress do
  @moduledoc false

  use Broadway

  require Logger
  require OpenTelemetry.Tracer, as: Tracer

  alias Broadway.Message
  alias LangboardSocket.BrokerEnvelope
  alias LangboardSocket.KafkaAcknowledger
  alias LangboardSocket.KafkaDeadLetter
  alias LangboardSocket.LegacyPayloadStore
  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocket.SocketEventProjector
  alias LangboardSocket.SubscriptionTopic

  def enabled? do
    Application.fetch_env!(:langboard_socket, :kafka) |> Keyword.fetch!(:enabled)
  end

  @reason_codes %{
    invalid_broker_envelope: "invalid_broker_envelope",
    invalid_socket_publish_data: "invalid_socket_publish_data",
    invalid_publish_models: "invalid_publish_models",
    invalid_publish_model: "invalid_publish_model",
    invalid_data_keys: "invalid_data_keys",
    invalid_custom_data: "invalid_custom_data",
    legacy_fallback_disabled: "legacy_fallback_disabled",
    legacy_payload_missing: "legacy_payload_missing",
    legacy_payload_too_large: "legacy_payload_too_large",
    invalid_legacy_payload: "invalid_legacy_payload",
    legacy_store_unavailable: "legacy_store_unavailable",
    pubsub_unavailable: "pubsub_unavailable"
  }

  def ready? do
    not enabled?() or
      (is_pid(Process.whereis(__MODULE__)) and KafkaDeadLetter.ready?() and legacy_store_ready?() and
         cluster_assigned?())
  end

  def assigned? do
    __MODULE__
    |> Broadway.producer_names()
    |> Enum.any?(&producer_assigned?/1)
  catch
    :exit, _reason -> false
  end

  def start_link(_opts) do
    config = Application.fetch_env!(:langboard_socket, :kafka)
    hosts = config |> Keyword.fetch!(:hosts) |> require_value!(:hosts)
    group_id = config |> Keyword.fetch!(:group_id) |> require_value!(:group_id)
    source_topic = config |> Keyword.get(:source_topic) |> configured_source_topic()

    Broadway.start_link(__MODULE__,
      name: __MODULE__,
      context: context(config),
      producer: [
        module:
          {BroadwayKafka.Producer,
           [
             hosts: hosts,
             group_id: group_id,
             topics: [source_topic],
             offset_commit_on_ack: true,
             # A fresh group has no committed offset if its first record cannot reach the DLQ.
             # Resetting to latest after producer restart would silently discard that record.
             offset_reset_policy: :earliest,
             fetch_config: [max_bytes: Keyword.fetch!(config, :max_bytes)]
           ]},
        concurrency: 1
      ],
      processors: [
        default: [
          concurrency: Keyword.fetch!(config, :processor_concurrency),
          max_demand: Keyword.fetch!(config, :max_demand)
        ]
      ]
    )
  end

  @impl true
  def handle_message(_processor, message, context) do
    message = KafkaAcknowledger.wrap(message)
    topic = Map.get(message.metadata, :topic, Contract.broker_event!("fanout"))
    context = context(context)

    case resolve_payload(message.data, topic, context) do
      {:ok, data, source, event_id} ->
        message = put_broker_metadata(message, source, event_id)

        with {:ok, frames} <- project(data),
             :ok <- broadcast(frames, context) do
          emit_result(:ok, topic)
          message
        else
          {:error, reason} -> fail(message, reason, topic)
        end

      {:error, reason} ->
        fail(message, reason, topic)
    end
  end

  @impl true
  def handle_failed(messages, context) do
    context = context(context)
    Enum.map(messages, &dead_letter(&1, context))
  end

  defp resolve_payload(payload, topic, context) do
    Tracer.with_span "langboard.kafka.resolve" do
      case BrokerEnvelope.decode(payload, topic) do
        {:ok, envelope} ->
          Tracer.set_attributes(%{
            "langboard.broker.source" => "inline",
            "langboard.event_id" => envelope.event_id
          })

          {:ok, envelope.data, :inline, envelope.event_id}

        {:legacy, cache_key} ->
          resolve_legacy_payload(cache_key, context)

        {:error, reason} ->
          Tracer.set_status(:error, Atom.to_string(reason))
          {:error, reason}
      end
    end
  end

  defp resolve_legacy_payload(_cache_key, %{legacy_redis_enabled: false}) do
    emit_legacy_result(:disabled)
    {:error, :legacy_fallback_disabled}
  end

  defp resolve_legacy_payload(cache_key, context) do
    Tracer.set_attribute("langboard.broker.source", "legacy_redis")

    result =
      retry(
        fn ->
          fetch_legacy_payload(
            context.legacy_payload_store,
            cache_key,
            context.legacy_max_payload_bytes
          )
        end,
        :legacy_fetch,
        context,
        &(&1 == :legacy_store_unavailable)
      )

    case result do
      {:ok, data} ->
        emit_legacy_result(:hit)
        {:ok, data, :legacy, nil}

      {:error, reason} ->
        emit_legacy_result(legacy_result(reason))
        Tracer.set_status(:error, Atom.to_string(reason))
        {:error, reason}
    end
  end

  defp project(data) do
    Tracer.with_span "langboard.kafka.project" do
      case SocketEventProjector.project(data) do
        {:ok, frames} = result ->
          Tracer.set_attribute("langboard.frame.count", length(frames))
          result

        {:error, reason} = error ->
          Tracer.set_status(:error, reason_code(reason))
          error
      end
    end
  end

  defp broadcast(frames, context) do
    Tracer.with_span "langboard.kafka.pubsub" do
      broadcast_frames(frames, context)
    end
  end

  defp broadcast_frames(frames, context) do
    Enum.reduce_while(frames, :ok, fn frame, :ok ->
      result =
        retry(
          fn -> broadcast_frame(frame) end,
          :pubsub,
          context,
          &(&1 == :pubsub_unavailable)
        )

      case result do
        :ok -> {:cont, :ok}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
  end

  defp broadcast_frame(frame) do
    case Phoenix.PubSub.broadcast(
           LangboardSocket.PubSub,
           SubscriptionTopic.name(frame["topic"], frame["topic_id"]),
           {:socket_event, frame}
         ) do
      :ok -> :ok
      {:error, _reason} -> {:error, :pubsub_unavailable}
    end
  end

  defp dead_letter(message, context) do
    record = dead_letter_record(message, context.dead_letter_max_payload_bytes)
    reason = record["reason"]

    result =
      Tracer.with_span "langboard.kafka.dead_letter",
        attributes: %{
          "messaging.destination.name" => context.dead_letter_topic,
          "langboard.failure.reason" => reason
        } do
        retry(
          fn ->
            publish_dead_letter(
              context.dead_letter_publisher,
              record,
              context.dead_letter_publish_timeout_ms
            )
          end,
          :dead_letter,
          context,
          fn _reason -> true end
        )
      end

    case result do
      :ok ->
        emit_dead_letter_result(:published, reason)

        Logger.warning("Kafka ingress moved a rejected record to the dead-letter topic",
          topic: metadata_value(message.metadata, :topic),
          partition: metadata_value(message.metadata, :partition),
          offset: metadata_value(message.metadata, :offset),
          reason: reason
        )

        %{message | metadata: Map.put(message.metadata, :dead_letter_persisted, true)}

      {:error, _failure} ->
        emit_dead_letter_result(:failed, reason)

        Logger.error("Kafka ingress could not persist a rejected record",
          topic: metadata_value(message.metadata, :topic),
          partition: metadata_value(message.metadata, :partition),
          offset: metadata_value(message.metadata, :offset),
          reason: reason
        )

        message
    end
  end

  defp dead_letter_record(message, max_payload_bytes) do
    payload = message.data
    retained_bytes = min(byte_size(payload), max_payload_bytes)

    %{
      "schema_version" => Contract.dead_letter_schema_version!(),
      "event_id" => metadata_value(message.metadata, :event_id),
      "payload_source" => source_name(metadata_value(message.metadata, :broker_source)),
      "reason" => reason_code(message.status),
      "failed_at" => DateTime.utc_now() |> DateTime.to_iso8601(),
      "source" => %{
        "topic" => metadata_value(message.metadata, :topic),
        "partition" => metadata_value(message.metadata, :partition),
        "offset" => metadata_value(message.metadata, :offset)
      },
      "payload_bytes" => byte_size(payload),
      "payload_sha256" => :crypto.hash(:sha256, payload) |> Base.encode16(case: :lower),
      "payload_base64" => payload |> binary_part(0, retained_bytes) |> Base.encode64(),
      "payload_truncated" => retained_bytes < byte_size(payload)
    }
  end

  defp retry(operation, operation_name, context, retryable?) do
    do_retry(
      operation,
      operation_name,
      retryable?,
      1,
      context.processing_max_attempts,
      context.processing_retry_backoff_ms
    )
  end

  defp do_retry(operation, operation_name, retryable?, attempt, max_attempts, backoff_ms) do
    case operation.() do
      {:error, reason} = error ->
        if attempt < max_attempts and retryable?.(reason) do
          emit_retry(operation_name)
          Process.sleep(min(backoff_ms * attempt, 30_000))
          do_retry(operation, operation_name, retryable?, attempt + 1, max_attempts, backoff_ms)
        else
          error
        end

      result ->
        result
    end
  end

  defp context(
         %{
           legacy_redis_enabled: _legacy_redis_enabled,
           legacy_payload_store: _legacy_payload_store,
           legacy_max_payload_bytes: _legacy_max_payload_bytes,
           dead_letter_publisher: _dead_letter_publisher,
           dead_letter_topic: _dead_letter_topic,
           dead_letter_max_payload_bytes: _dead_letter_max_payload_bytes,
           dead_letter_publish_timeout_ms: _dead_letter_publish_timeout_ms,
           processing_max_attempts: _processing_max_attempts,
           processing_retry_backoff_ms: _processing_retry_backoff_ms
         } = context
       ),
       do: context

  defp context(config) when is_list(config) do
    legacy_redis = Keyword.fetch!(config, :legacy_redis)

    %{
      legacy_redis_enabled: Keyword.fetch!(legacy_redis, :enabled),
      legacy_payload_store: Application.fetch_env!(:langboard_socket, :legacy_payload_store),
      legacy_max_payload_bytes:
        legacy_redis |> Keyword.fetch!(:max_payload_bytes) |> positive_integer!(),
      dead_letter_publisher: Application.fetch_env!(:langboard_socket, :dead_letter_publisher),
      dead_letter_topic: configured_dead_letter_topic(Keyword.fetch!(config, :dead_letter_topic)),
      dead_letter_max_payload_bytes:
        config |> Keyword.fetch!(:dead_letter_max_payload_bytes) |> positive_integer!(),
      dead_letter_publish_timeout_ms:
        config |> Keyword.fetch!(:dead_letter_publish_timeout_ms) |> positive_integer!(),
      processing_max_attempts:
        config |> Keyword.fetch!(:processing_max_attempts) |> positive_integer!(),
      processing_retry_backoff_ms:
        config |> Keyword.fetch!(:processing_retry_backoff_ms) |> non_negative_integer!()
    }
  end

  defp context(_context) do
    Application.fetch_env!(:langboard_socket, :kafka) |> context()
  end

  defp fetch_legacy_payload(store, cache_key, max_payload_bytes) when is_function(store, 2),
    do: store.(cache_key, max_payload_bytes)

  defp fetch_legacy_payload(store, cache_key, max_payload_bytes),
    do: store.fetch(cache_key, max_payload_bytes)

  defp publish_dead_letter(publisher, record, timeout_ms) when is_function(publisher, 2),
    do: publisher.(record, timeout_ms)

  defp publish_dead_letter(publisher, record, timeout_ms),
    do: publisher.publish(record, timeout_ms)

  defp put_broker_metadata(message, source, event_id) do
    metadata =
      message.metadata
      |> Map.put(:broker_source, source)
      |> Map.put(:event_id, event_id)

    %{message | metadata: metadata}
  end

  defp fail(message, reason, topic) do
    emit_result(:error, topic)
    Message.failed(message, reason)
  end

  defp legacy_store_ready? do
    config = Application.fetch_env!(:langboard_socket, :kafka)
    legacy_redis = Keyword.fetch!(config, :legacy_redis)

    not Keyword.fetch!(legacy_redis, :enabled) or LegacyPayloadStore.ready?()
  end

  defp cluster_assigned? do
    assigned?() or
      Enum.any?(Node.list(:visible), fn node ->
        :rpc.call(node, __MODULE__, :assigned?, [], 1_000) == true
      end)
  catch
    :exit, _reason -> false
  end

  defp producer_assigned?(producer) do
    case :sys.get_state(producer, 1_000) do
      %GenStage{
        state: %{
          module_state: %{
            client_connected?: true,
            fenced?: false,
            shutting_down?: false,
            group_coordinator: coordinator,
            acks: acknowledger
          }
        }
      } ->
        is_pid(coordinator) and BroadwayKafka.Acknowledger.keys(acknowledger) != []

      _state ->
        false
    end
  catch
    :exit, _reason -> false
  end

  defp metadata_value(metadata, key),
    do: Map.get(metadata, key, Map.get(metadata, Atom.to_string(key)))

  defp source_name(:inline), do: "inline"
  defp source_name(:legacy), do: "legacy_redis"
  defp source_name(_source), do: "unknown"

  defp reason_code({:failed, reason}), do: reason_code(reason)
  defp reason_code(reason), do: Map.get(@reason_codes, reason, "processing_failure")

  defp legacy_result(:legacy_payload_missing), do: :missing
  defp legacy_result(:legacy_payload_too_large), do: :too_large
  defp legacy_result(:invalid_legacy_payload), do: :invalid
  defp legacy_result(_reason), do: :unavailable

  defp configured_dead_letter_topic(topic) when is_binary(topic) and topic != "", do: topic
  defp configured_dead_letter_topic(_topic), do: Contract.dead_letter_topic!("fanout")

  defp configured_source_topic(topic) when is_binary(topic) and topic != "", do: topic
  defp configured_source_topic(_topic), do: Contract.broker_event!("fanout")

  defp emit_result(result, topic) do
    :telemetry.execute(
      [:langboard_socket, :kafka, :message],
      %{count: 1},
      %{result: result, topic: topic}
    )
  end

  defp emit_legacy_result(result) do
    :telemetry.execute(
      [:langboard_socket, :kafka, :legacy_fallback],
      %{count: 1},
      %{result: result}
    )
  end

  defp emit_retry(operation) do
    :telemetry.execute(
      [:langboard_socket, :kafka, :processing_retry],
      %{count: 1},
      %{operation: operation}
    )
  end

  defp emit_dead_letter_result(result, reason) do
    :telemetry.execute(
      [:langboard_socket, :kafka, :dead_letter],
      %{count: 1},
      %{result: result, reason: reason}
    )
  end

  defp require_value!(value, _key) when is_binary(value) and value != "", do: value
  defp require_value!(_value, key), do: raise("Missing Kafka configuration: #{key}")

  defp positive_integer!(value) when is_integer(value) and value > 0, do: value

  defp positive_integer!(value),
    do: raise(ArgumentError, "expected a positive integer, got: #{inspect(value)}")

  defp non_negative_integer!(value) when is_integer(value) and value >= 0, do: value

  defp non_negative_integer!(value),
    do: raise(ArgumentError, "expected a non-negative integer, got: #{inspect(value)}")
end
