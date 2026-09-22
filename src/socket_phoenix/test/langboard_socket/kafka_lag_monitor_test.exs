defmodule LangboardSocket.KafkaLagMonitorTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.KafkaLagMonitor
  alias LangboardSocket.KafkaOffsetClient

  test "readiness opens only after zero lag and remains open" do
    {:ok, responses} =
      Agent.start_link(fn -> [{:error, :unavailable}, {:ok, 3}, {:ok, 0}, {:ok, 4}] end)

    fetch_lag = fn _config ->
      Agent.get_and_update(responses, fn [response | remaining] -> {response, remaining} end)
    end

    name = Module.concat(__MODULE__, ZeroLag)

    start_supervised!(
      {KafkaLagMonitor,
       name: name,
       config: [],
       fetch_lag: fetch_lag,
       poll_interval_ms: 60_000,
       initial_delay_ms: 60_000}
    )

    refute KafkaLagMonitor.ready?(name)
    assert KafkaLagMonitor.refresh(name) == {:error, :unavailable}
    refute KafkaLagMonitor.ready?(name)
    assert KafkaLagMonitor.refresh(name) == {:ok, 3}
    refute KafkaLagMonitor.ready?(name)
    assert KafkaLagMonitor.refresh(name) == {:ok, 0}
    assert KafkaLagMonitor.ready?(name)
    assert KafkaLagMonitor.refresh(name) == {:ok, 4}
    assert KafkaLagMonitor.ready?(name)
  end

  test "total lag is the sum of non-negative partition differences" do
    assert KafkaOffsetClient.total_lag(
             [0, 1, 2],
             %{0 => 5, 1 => 10, 2 => 15},
             %{0 => 8, 1 => 9, 2 => 20}
           ) == 8
  end
end
