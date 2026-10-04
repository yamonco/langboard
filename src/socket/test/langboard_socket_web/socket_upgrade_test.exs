defmodule LangboardSocketWeb.SocketUpgradeTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.RuntimeStatus
  alias LangboardSocketWeb.SocketUpgrade

  test "authenticated users can upgrade the JSON socket" do
    on_exit(fn -> Process.delete(:authentication_result) end)
    Process.put(:authentication_result, {:ok, "test-user"})

    conn =
      :get
      |> Plug.Test.conn("/?authorization=test-token")
      |> then(&%{&1 | host: "localhost", req_headers: [{"host", "localhost"} | &1.req_headers]})
      |> Plug.Conn.put_req_header("connection", "upgrade")
      |> Plug.Conn.put_req_header("upgrade", "websocket")
      |> Plug.Conn.put_req_header("sec-websocket-key", "dGhlIHNhbXBsZSBub25jZQ==")
      |> Plug.Conn.put_req_header("sec-websocket-version", "13")
      |> SocketUpgrade.call([])

    assert conn.status == 101
    assert conn.halted

    Process.put(:authentication_result, {:error, :expired_token})

    expired_conn =
      :get
      |> Plug.Test.conn("/?authorization=expired")
      |> then(&%{&1 | host: "localhost", req_headers: [{"host", "localhost"} | &1.req_headers]})
      |> Plug.Conn.put_req_header("connection", "upgrade")
      |> Plug.Conn.put_req_header("upgrade", "websocket")
      |> Plug.Conn.put_req_header("sec-websocket-key", "dGhlIHNhbXBsZSBub25jZQ==")
      |> Plug.Conn.put_req_header("sec-websocket-version", "13")
      |> SocketUpgrade.call([])

    assert expired_conn.status == 101
    assert expired_conn.halted
  end

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
