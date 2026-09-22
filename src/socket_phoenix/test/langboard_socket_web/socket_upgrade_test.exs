defmodule LangboardSocketWeb.SocketUpgradeTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.RuntimeStatus
  alias LangboardSocketWeb.SocketUpgrade

  test "new realtime WebSockets are rejected while the runtime drains" do
    on_exit(fn -> RuntimeStatus.reset() end)
    assert :ok = RuntimeStatus.begin_drain()

    conn =
      :get
      |> Plug.Test.conn("/?authorization=test-token")
      |> Plug.Conn.put_req_header("upgrade", "websocket")
      |> SocketUpgrade.call([])

    assert conn.status == 503
    assert conn.halted
  end

  test "new realtime WebSockets are rejected while the cluster is incomplete" do
    previous_size = Application.fetch_env!(:langboard_socket, :cluster_minimum_size)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :cluster_minimum_size, previous_size)
    end)

    Application.put_env(:langboard_socket, :cluster_minimum_size, 2)

    conn =
      :get
      |> Plug.Test.conn("/?authorization=test-token")
      |> Plug.Conn.put_req_header("upgrade", "websocket")
      |> SocketUpgrade.call([])

    assert conn.status == 503
    assert conn.halted
  end
end
