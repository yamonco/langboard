defmodule LangboardSocket.GraphResumeClientTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.GraphResumeClient

  setup do
    original_url = Application.fetch_env!(:langboard_socket, :graph_internal_url)
    original_limit = Application.fetch_env!(:langboard_socket, :graph_stream_max_chunk_bytes)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :graph_internal_url, original_url)
      Application.put_env(:langboard_socket, :graph_stream_max_chunk_bytes, original_limit)
    end)

    :ok
  end

  test "posts the claimed decision and accepts a matching completed response" do
    test_pid = self()

    server_url =
      start_graph(fn conn, _opts ->
        {:ok, body, conn} = Plug.Conn.read_body(conn)
        send(test_pid, {:request, conn.method, conn.request_path, Jason.decode!(body)})

        Plug.Conn.resp(
          conn,
          200,
          Jason.encode!(%{
            thread_id: "thread /1",
            session_id: "session-uid",
            message: "Graph answer",
            interrupts: []
          })
        )
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)
    decision = %{"approved" => true, "rejected" => false, "app_api_token" => "private-token"}

    assert {:ok, %{response_text: "Graph answer", interrupt: nil}} =
             GraphResumeClient.resume("thread /1", "session-uid", decision)

    assert_received {:request, "POST", "/api/v1/graph/resume/thread%20%2F1",
                     %{"resume" => ^decision, "session_id" => "session-uid"}}
  end

  test "accepts one matching next interrupt" do
    interrupt = %{
      "id" => "next-interrupt",
      "value" => %{
        "type" => "approval_request",
        "thread_id" => "thread-id",
        "session_id" => "session-uid"
      }
    }

    server_url =
      start_graph(fn conn, _opts ->
        Plug.Conn.resp(
          conn,
          200,
          Jason.encode!(%{
            thread_id: "thread-id",
            session_id: "session-uid",
            message: "Partial",
            interrupts: [interrupt]
          })
        )
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert {:ok, %{response_text: "Partial", interrupt: ^interrupt}} =
             GraphResumeClient.resume("thread-id", "session-uid", %{"rejected" => true})
  end

  test "rejects mismatched identity and multiple interrupts" do
    server_url =
      start_graph(fn conn, _opts ->
        Plug.Conn.resp(
          conn,
          200,
          Jason.encode!(%{
            thread_id: "other-thread",
            session_id: "session-uid",
            message: "Answer",
            interrupts: []
          })
        )
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert {:error, :invalid_response} =
             GraphResumeClient.resume("thread-id", "session-uid", %{})

    other_url =
      start_graph(fn conn, _opts ->
        Plug.Conn.resp(
          conn,
          200,
          Jason.encode!(%{
            thread_id: "thread-id",
            session_id: "session-uid",
            message: "Answer",
            interrupts: [%{}, %{}]
          })
        )
      end)

    Application.put_env(:langboard_socket, :graph_internal_url, other_url)

    assert {:error, :invalid_response} =
             GraphResumeClient.resume("thread-id", "session-uid", %{})
  end

  test "rejects malformed or foreign nested interrupt identity" do
    for value <- [
          nil,
          [],
          %{},
          %{"thread_id" => "other-thread", "session_id" => "session-uid"},
          %{"thread_id" => "thread-id", "session_id" => "other-session"},
          %{"thread_id" => "thread-id"},
          %{"session_id" => "session-uid"}
        ] do
      server_url =
        start_graph(fn conn, _opts ->
          Plug.Conn.resp(
            conn,
            200,
            Jason.encode!(%{
              thread_id: "thread-id",
              session_id: "session-uid",
              message: "Partial",
              interrupts: [%{"value" => value}]
            })
          )
        end)

      Application.put_env(:langboard_socket, :graph_internal_url, server_url)

      assert {:error, :invalid_response} =
               GraphResumeClient.resume("thread-id", "session-uid", %{"approved" => true})
    end
  end

  test "bounds the Graph response and maps a conflict" do
    Application.put_env(:langboard_socket, :graph_stream_max_chunk_bytes, 16)

    server_url =
      start_graph(fn conn, _opts -> Plug.Conn.resp(conn, 200, String.duplicate("x", 100)) end)

    Application.put_env(:langboard_socket, :graph_internal_url, server_url)

    assert {:error, :response_too_large} =
             GraphResumeClient.resume("thread-id", "session-uid", %{})

    conflict_url = start_graph(fn conn, _opts -> Plug.Conn.resp(conn, 409, "conflict") end)
    Application.put_env(:langboard_socket, :graph_internal_url, conflict_url)

    assert {:error, :conflict} = GraphResumeClient.resume("thread-id", "session-uid", %{})
  end

  defp start_graph(plug) do
    server =
      start_supervised!(
        {Bandit, plug: plug, scheme: :http, ip: {127, 0, 0, 1}, port: 0, startup_log: false},
        id: make_ref()
      )

    {:ok, {{127, 0, 0, 1}, port}} = ThousandIsland.listener_info(server)
    "http://127.0.0.1:#{port}"
  end
end
