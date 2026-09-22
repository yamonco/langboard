defmodule LangboardSocket.GraphStreamClientTest do
  use ExUnit.Case

  alias LangboardSocket.GraphStreamClient

  setup do
    original_url = Application.fetch_env!(:langboard_socket, :graph_internal_url)
    original_limit = Application.fetch_env!(:langboard_socket, :graph_stream_max_chunk_bytes)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :graph_internal_url, original_url)
      Application.put_env(:langboard_socket, :graph_stream_max_chunk_bytes, original_limit)
    end)

    :ok
  end

  test "posts to the configured graph and delivers fragmented events in order" do
    test_pid = self()

    server_url =
      start_graph(fn conn, _opts ->
        {:ok, body, conn} = Plug.Conn.read_body(conn)

        send(
          test_pid,
          {:request, conn.method, conn.request_path, conn.query_string, Jason.decode!(body)}
        )

        conn = Plug.Conn.send_chunked(conn, 200)
        {:ok, conn} = Plug.Conn.chunk(conn, ~s({"event":"token","data":{"chunk":"hello"}}\n))

        {:ok, conn} =
          Plug.Conn.chunk(conn, "\n" <> frame("interrupt", %{"thread_id" => "thread-1"}))

        {:ok, conn} = Plug.Conn.chunk(conn, frame("end", %{}))
        conn
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert :ok =
             GraphStreamClient.stream("session /1", %{"input_value" => "hello"}, fn event ->
               send(test_pid, {:event, event})
               :ok
             end)

    assert_received {:request, "POST", "/api/v1/graph/run/session%20%2F1", "stream=true",
                     %{"input_value" => "hello"}}

    assert_received {:event, {:token, "hello"}}
    assert_received {:event, {:interrupt, %{"thread_id" => "thread-1"}}}
    assert_received {:event, :end}
  end

  test "rejects malformed graph responses" do
    server_url =
      start_graph(fn conn, _opts ->
        Plug.Conn.resp(conn, 200, ~s({"event":"token"}\n\n))
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert {:error, :invalid_frame} =
             GraphStreamClient.stream("session", %{}, fn _event -> :ok end)
  end

  test "does not emit success when the graph closes before its end frame" do
    server_url =
      start_graph(fn conn, _opts ->
        Plug.Conn.resp(conn, 200, frame("token", %{"chunk" => "partial"}))
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert {:error, :incomplete_stream} =
             GraphStreamClient.stream("session", %{}, fn event ->
               send(self(), {:event, event})
               :ok
             end)

    assert_received {:event, {:token, "partial"}}
    refute_received {:event, :end}
  end

  test "does not emit success when data follows an end frame" do
    server_url =
      start_graph(fn conn, _opts ->
        Plug.Conn.resp(conn, 200, frame("end", %{}) <> frame("token", %{"chunk" => "late"}))
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert {:error, :data_after_end} =
             GraphStreamClient.stream("session", %{}, fn event ->
               send(self(), {:event, event})
               :ok
             end)

    refute_received {:event, :end}
  end

  test "reports graph errors without accepting a successful completion" do
    server_url =
      start_graph(fn conn, _opts ->
        Plug.Conn.resp(conn, 200, frame("error", %{"error" => "graph failed"}))
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert {:error, :graph_error} =
             GraphStreamClient.stream("session", %{}, fn event ->
               send(self(), {:event, event})
               :ok
             end)

    assert_received {:event, {:error, "graph failed"}}
  end

  test "halts when the downstream consumer cannot accept another event" do
    server_url =
      start_graph(fn conn, _opts ->
        Plug.Conn.resp(conn, 200, frame("token", %{"chunk" => "a"}) <> frame("end", %{}))
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert {:error, {:downstream, :full}} =
             GraphStreamClient.stream("session", %{}, fn event ->
               send(self(), {:event, event})
               {:error, :full}
             end)

    assert_received {:event, {:token, "a"}}
    refute_received {:event, :end}
  end

  test "rejects non-success status before invoking the consumer" do
    server_url = start_graph(fn conn, _opts -> Plug.Conn.resp(conn, 403, "denied") end)
    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert {:error, :upstream_status} =
             GraphStreamClient.stream("session", %{}, fn event ->
               send(self(), {:event, event})
               :ok
             end)

    refute_received {:event, _event}
  end

  test "preserves downstream rejection and invalid results on completion" do
    server_url = start_graph(fn conn, _opts -> Plug.Conn.resp(conn, 200, frame("end", %{})) end)
    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    for {result, expected} <- [
          {{:error, :closed}, {:error, {:downstream, :closed}}},
          {:unexpected, {:error, :invalid_callback}}
        ] do
      assert ^expected =
               GraphStreamClient.stream("session", %{}, fn :end -> result end)
    end
  end

  defp start_graph(plug) do
    server =
      start_supervised!(
        {Bandit, plug: plug, scheme: :http, ip: {127, 0, 0, 1}, port: 0, startup_log: false}
      )

    {:ok, {{127, 0, 0, 1}, port}} = ThousandIsland.listener_info(server)
    "http://127.0.0.1:#{port}"
  end

  defp frame(event, data) do
    Jason.encode!(%{"event" => event, "data" => data}) <> "\n\n"
  end
end
