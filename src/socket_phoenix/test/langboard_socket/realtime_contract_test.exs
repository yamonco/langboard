defmodule LangboardSocket.RealtimeContractTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.RealtimeContract

  test "client command inventory is read from the shared contract" do
    assert RealtimeContract.client_command?("board", "board:chat:send")
    assert RealtimeContract.client_command?("none", "board:card:editor:copilot:abort")
    refute RealtimeContract.client_command?("board", "unknown")
    refute RealtimeContract.client_command?("unknown", "board:chat:send")
  end

  test "broker ownership is read from the shared contract" do
    assert RealtimeContract.broker_schema_version!() == "2"
    assert RealtimeContract.broker_event!("fanout") == "socket_publish"
    assert RealtimeContract.broker_event!("side_effect") == "notification_publish"
    assert RealtimeContract.legacy_cache_key_prefix!() == "broadcast-"
    assert RealtimeContract.legacy_cache_key_max_length!() == 160
    assert RealtimeContract.dead_letter_schema_version!() == "1"
    assert RealtimeContract.dead_letter_topic!("fanout") == "socket_publish_dead_letter"
  end

  test "protocol limits are read from the shared contract" do
    assert RealtimeContract.protocol_limit!("max_topic_ids") == 64
    assert RealtimeContract.protocol_limit!("max_topic_id_bytes") == 128
  end

  test "internal API compatibility is read from the shared contract" do
    assert RealtimeContract.internal_api_capabilities_path!() == "/auth/socket/capabilities"
    assert RealtimeContract.internal_api_contract_version!() == 1
  end
end
