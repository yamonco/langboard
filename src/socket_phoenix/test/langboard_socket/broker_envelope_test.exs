defmodule LangboardSocket.BrokerEnvelopeTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.BrokerEnvelope

  test "decodes the current inline envelope" do
    payload =
      Jason.encode!(%{
        schema_version: "2",
        event_id: "event-1",
        event: "socket_publish",
        occurred_at: "2026-09-12T12:00:00Z",
        data: %{value: "ok"},
        cache_key: "legacy-key"
      })

    assert {:ok, envelope} = BrokerEnvelope.decode(payload, "socket_publish")
    assert envelope.event_id == "event-1"
    assert envelope.data == %{"value" => "ok"}
  end

  test "accepts only legacy keys from the broadcast namespace" do
    assert {:legacy, "broadcast-legacy-key"} =
             BrokerEnvelope.decode(
               Jason.encode!(%{cache_key: "broadcast-legacy-key"}),
               "socket_publish"
             )

    assert {:error, :invalid_broker_envelope} =
             BrokerEnvelope.decode(Jason.encode!(%{cache_key: "other-key"}), "socket_publish")

    oversized_key = "broadcast-" <> String.duplicate("x", 151)

    assert {:error, :invalid_broker_envelope} =
             BrokerEnvelope.decode(Jason.encode!(%{cache_key: oversized_key}), "socket_publish")
  end

  test "never falls back when a versioned envelope is invalid" do
    assert {:error, :invalid_broker_envelope} =
             BrokerEnvelope.decode(
               Jason.encode!(%{
                 schema_version: "invalid",
                 cache_key: "broadcast-legacy-key"
               }),
               "socket_publish"
             )
  end

  test "rejects mismatched and malformed inline envelopes" do
    assert {:error, :invalid_broker_envelope} =
             BrokerEnvelope.decode(
               Jason.encode!(%{
                 schema_version: "2",
                 event_id: "event-1",
                 event: "notification_publish",
                 occurred_at: "2026-09-12T12:00:00Z",
                 data: %{}
               }),
               "socket_publish"
             )

    assert {:error, :invalid_broker_envelope} =
             BrokerEnvelope.decode(
               Jason.encode!(%{
                 schema_version: "2",
                 event_id: "event-1",
                 event: "socket_publish",
                 occurred_at: "invalid",
                 data: %{}
               }),
               "socket_publish"
             )
  end
end
