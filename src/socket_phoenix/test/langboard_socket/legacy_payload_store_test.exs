defmodule LangboardSocket.LegacyPayloadStoreTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.LegacyPayloadStore

  test "exposes a supervisor child specification" do
    config = [url: "redis://localhost:6379/0"]

    assert %{
             id: LegacyPayloadStore,
             start: {LegacyPayloadStore, :start_link, [^config]},
             type: :worker,
             restart: :permanent,
             shutdown: 5_000
           } = LegacyPayloadStore.child_spec(config)
  end

  test "decodes only bounded JSON objects" do
    payload = Jason.encode!(%{value: "ok"})

    assert {:ok, %{"value" => "ok"}} = LegacyPayloadStore.decode(payload, byte_size(payload))
    assert {:error, :legacy_payload_too_large} = LegacyPayloadStore.decode(payload, 1)
    assert {:error, :invalid_legacy_payload} = LegacyPayloadStore.decode("[]", 10)
    assert {:error, :invalid_legacy_payload} = LegacyPayloadStore.decode("invalid", 10)
  end
end
