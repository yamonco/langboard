defmodule LangboardSocket.KafkaAcknowledgerTest do
  use ExUnit.Case, async: true

  alias Broadway.Message
  alias LangboardSocket.KafkaAcknowledger

  defmodule Producer do
    use GenStage

    def init(_opts), do: {:producer, nil}
  end

  test "acknowledges rejected records only after dead-letter persistence" do
    ack_ref = {self(), {:generation, "socket_publish", 0}}

    message =
      message(ack_ref, 12)
      |> KafkaAcknowledger.wrap()
      |> Map.update!(:metadata, &Map.put(&1, :dead_letter_persisted, true))

    KafkaAcknowledger.ack(ack_ref, [], [message])
    assert_receive {:ack, {:generation, "socket_publish", 0}, [12]}
  end

  test "restarts the source producer instead of acknowledging an unpersisted rejection" do
    {:ok, producer} = GenStage.start(Producer, [])
    monitor = Process.monitor(producer)
    ack_ref = {producer, {:generation, "socket_publish", 0}}
    message = message(ack_ref, 12) |> KafkaAcknowledger.wrap()

    assert :ok = KafkaAcknowledger.ack(ack_ref, [], [message])
    assert_receive {:DOWN, ^monitor, :process, ^producer, :dead_letter_unavailable}
  end

  defp message(ack_ref, offset) do
    %Message{
      data: "payload",
      metadata: %{},
      status: {:failed, :invalid_broker_envelope},
      acknowledger: {BroadwayKafka.Acknowledger, ack_ref, %{offset: offset}}
    }
  end
end
