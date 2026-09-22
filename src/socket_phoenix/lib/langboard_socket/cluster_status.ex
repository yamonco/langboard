defmodule LangboardSocket.ClusterStatus do
  @moduledoc false

  def ready? do
    minimum_size = Application.fetch_env!(:langboard_socket, :cluster_minimum_size)
    is_integer(minimum_size) and minimum_size > 0 and current_size() >= minimum_size
  end

  def current_size, do: length(Node.list(:visible)) + 1

  def emit_measurement do
    :telemetry.execute(
      [:langboard_socket, :cluster, :members],
      %{count: current_size()},
      %{ready: ready?()}
    )
  end
end
