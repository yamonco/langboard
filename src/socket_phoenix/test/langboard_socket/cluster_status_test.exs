defmodule LangboardSocket.ClusterStatusTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.ClusterStatus

  setup do
    original = Application.fetch_env!(:langboard_socket, :cluster_minimum_size)
    on_exit(fn -> Application.put_env(:langboard_socket, :cluster_minimum_size, original) end)
  end

  test "a standalone runtime is ready when one node is required" do
    Application.put_env(:langboard_socket, :cluster_minimum_size, 1)

    assert ClusterStatus.current_size() >= 1
    assert ClusterStatus.ready?()
  end

  test "readiness fails when the required cluster membership is missing" do
    Application.put_env(
      :langboard_socket,
      :cluster_minimum_size,
      ClusterStatus.current_size() + 1
    )

    refute ClusterStatus.ready?()
  end
end
