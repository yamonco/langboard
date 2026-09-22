defmodule LangboardSocket.LangflowStreamClientTest do
  use ExUnit.Case

  alias LangboardSocket.LangflowStreamClient

  test "streams cumulative bot text and sends the server-owned API key" do
    test_pid = self()

    url =
      start_server(fn conn, _opts ->
        {:ok, body, conn} = Plug.Conn.read_body(conn)

        send(
          test_pid,
          {:request, conn.method, conn.request_path, conn.query_string,
           Plug.Conn.get_req_header(conn, "x-api-key"), Jason.decode!(body)}
        )

        conn = Plug.Conn.send_chunked(conn, 200)

        {:ok, conn} =
          Plug.Conn.chunk(conn, frame("add_message", %{"sender" => "user", "text" => "question"}))

        {:ok, conn} =
          Plug.Conn.chunk(conn, frame("token", %{"token" => true, "chunk" => "partial"}))

        {:ok, conn} =
          Plug.Conn.chunk(conn, frame("add_message", %{"sender" => "AI", "text" => "complete"}))

        {:ok, conn} = Plug.Conn.chunk(conn, frame("end", %{}))
        conn
      end)

    request = %{
      "url" => url <> "/api/v1/run/flow?stream=true",
      "api_key" => "server-only-key",
      "request_body" => %{"session_id" => "session-1", "input_value" => "question"}
    }

    assert :ok =
             LangflowStreamClient.stream("session-1", request, fn event ->
               send(test_pid, {:event, event})
               :ok
             end)

    assert_received {:request, "POST", "/api/v1/run/flow", "stream=true", ["server-only-key"],
                     %{"session_id" => "session-1", "input_value" => "question"}}

    assert_received {:event, {:token, "partial"}}
    assert_received {:event, {:token, "complete"}}
    assert_received {:event, :end}
  end

  test "rejects malformed requests before sending an external call" do
    body = %{"session_id" => "session-1"}

    for url <- [
          "file:///tmp/unsafe",
          "http://user@localhost/run",
          "http://localhost/run#fragment"
        ] do
      assert {:error, :invalid_request} =
               LangflowStreamClient.stream(
                 "session-1",
                 %{"url" => url, "api_key" => "key", "request_body" => body},
                 fn _event -> :ok end
               )
    end

    assert {:error, :invalid_request} =
             LangflowStreamClient.stream(
               "other-session",
               %{"url" => "https://example.test/run", "api_key" => "key", "request_body" => body},
               fn _event -> :ok end
             )
  end

  defp start_server(plug) do
    server =
      start_supervised!(
        {Bandit, plug: plug, scheme: :http, ip: {127, 0, 0, 1}, port: 0, startup_log: false}
      )

    {:ok, {{127, 0, 0, 1}, port}} = ThousandIsland.listener_info(server)
    "http://127.0.0.1:#{port}"
  end

  defp frame(event, data), do: Jason.encode!(%{"event" => event, "data" => data}) <> "\n\n"
end
