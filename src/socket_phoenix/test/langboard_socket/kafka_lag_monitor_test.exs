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

  test "readiness closes when lag becomes unavailable and reopens after catch-up" do
    {:ok, responses} =
      Agent.start_link(fn -> [{:ok, 0}, {:error, :unavailable}, {:ok, 2}, {:ok, 0}] end)

    fetch_lag = fn _config ->
      Agent.get_and_update(responses, fn [response | remaining] -> {response, remaining} end)
    end

    name = Module.concat(__MODULE__, LagRecovery)

    start_supervised!(
      {KafkaLagMonitor,
       name: name,
       config: [],
       fetch_lag: fetch_lag,
       poll_interval_ms: 60_000,
       initial_delay_ms: 60_000}
    )

    assert KafkaLagMonitor.refresh(name) == {:ok, 0}
    assert KafkaLagMonitor.ready?(name)
    assert KafkaLagMonitor.refresh(name) == {:error, :unavailable}
    refute KafkaLagMonitor.ready?(name)
    assert KafkaLagMonitor.refresh(name) == {:ok, 2}
    refute KafkaLagMonitor.ready?(name)
    assert KafkaLagMonitor.refresh(name) == {:ok, 0}
    assert KafkaLagMonitor.ready?(name)
  end

  test "total lag requires committed offsets within the retained log" do
    committed = %{0 => 5, 1 => 10, 2 => 15}
    earliest = %{0 => 2, 1 => 8, 2 => 12}
    latest = %{0 => 8, 1 => 10, 2 => 20}

    assert KafkaOffsetClient.total_lag([0, 1, 2], committed, earliest, latest) == {:ok, 8}

    assert KafkaOffsetClient.total_lag([0, 1, 2], %{committed | 0 => 1}, earliest, latest) ==
             {:error, :offset_out_of_range}

    assert KafkaOffsetClient.total_lag([0, 1, 2], %{committed | 1 => 11}, earliest, latest) ==
             {:error, :offset_out_of_range}
  end
end
