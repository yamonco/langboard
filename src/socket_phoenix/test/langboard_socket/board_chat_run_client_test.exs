defmodule LangboardSocket.BoardChatRunClientTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.BoardChatRunClient

  @secret String.duplicate("s", 32)
  @command %{
    "task_id" => "0750a86b-6cd7-492c-b846-6104e3c4c7c9",
    "message" => "Summarize this card",
    "scope_table" => "card",
    "scope_uid" => "123456789ab",
    "api_permission_level" => "read"
  }

  setup do
    previous = Application.fetch_env!(:langboard_socket, :internal_api_secret)
    Application.put_env(:langboard_socket, :internal_api_secret, @secret)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :internal_api_secret, previous)
    end)

    :ok
  end

  test "rejects empty and non-binary credentials and identities before HTTP dispatch" do
    options = [plug: {Req.Test, __MODULE__}]

    for invalid <- [nil, "", 0, false, [], %{}] do
      assert {:error, :invalid_data} =
               BoardChatRunClient.accept(invalid, "project-uid", @command, options)

      assert {:error, :invalid_data} =
               BoardChatRunClient.accept("access-token", invalid, @command, options)

      assert {:error, :invalid_data} =
               BoardChatRunClient.cancel("access-token", "project-uid", invalid, options)

      assert {:error, :invalid_data} =
               BoardChatRunClient.start("access-token", "project-uid", invalid, [], options)
    end
  end

  test "sends an authenticated and scoped acceptance request" do
    response = %{
      run_uid: "run-uid",
      status: "accepted",
      accepted: true,
      session: %{uid: "session-uid"},
      user_message: %{uid: "message-uid", chat_session_uid: "session-uid"}
    }

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "POST"
      assert conn.request_path == "/auth/socket/board/a%2Fb/chat/runs"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == @command

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, Jason.encode!(response))
    end)

    assert {:ok, %{"accepted" => true, "run_uid" => "run-uid"}} =
             BoardChatRunClient.accept("access-token", "a/b", @command,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "returns the same persisted result for a duplicate acceptance" do
    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"run_uid":"run-uid","status":"streaming","accepted":false,"session":{"uid":"session-uid"},"user_message":{"uid":"message-uid","chat_session_uid":"session-uid"}})
      )
    end)

    assert {:ok, %{"accepted" => false, "status" => "streaming"}} =
             BoardChatRunClient.accept("access-token", "project-uid", @command,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "cancels only a matching persisted task through both auth layers" do
    task_id = @command["task_id"]

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "POST"
      assert conn.request_path == "/auth/socket/board/project-uid/chat/cancel"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"task_id" => task_id}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{run_uid: "run-uid", status: "cancelled", task_id: task_id})
      )
    end)

    assert {:ok, "run-uid"} =
             BoardChatRunClient.cancel("access-token", "project-uid", task_id,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "cancellation rejects a mismatched task or missing internal secret" do
    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"run_uid":"run-uid","status":"cancelled","task_id":"other"})
      )
    end)

    assert {:error, :unavailable} =
             BoardChatRunClient.cancel("access-token", "project-uid", @command["task_id"],
               plug: {Req.Test, __MODULE__}
             )

    Application.put_env(:langboard_socket, :internal_api_secret, "")

    assert {:error, :unavailable} =
             BoardChatRunClient.cancel("access-token", "project-uid", @command["task_id"],
               plug: {Req.Test, __MODULE__}
             )
  end

  test "fails closed when the internal secret is not configured" do
    Application.put_env(:langboard_socket, :internal_api_secret, "")

    assert {:error, :unavailable} =
             BoardChatRunClient.accept("access-token", "project-uid", @command,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "maps denial, conflict, and malformed responses without accepting work" do
    for {status, body, expected} <- [
          {400, "{}", :invalid_data},
          {401, "{}", :unauthorized},
          {403, "{}", :forbidden},
          {409, "{}", :conflict},
          {422, "{}", :invalid_data},
          {500, "{}", :unavailable},
          {200, ~s({"run_uid":"run-uid","accepted":true}), :unavailable},
          {200,
           ~s({"run_uid":"run-uid","status":"accepted","accepted":true,"session":{"uid":"session-uid"},"user_message":{"uid":"message-uid","chat_session_uid":"other-session"}}),
           :unavailable}
        ] do
      Req.Test.expect(__MODULE__, fn conn -> Plug.Conn.send_resp(conn, status, body) end)

      assert {:error, ^expected} =
               BoardChatRunClient.accept("access-token", "project-uid", @command,
                 plug: {Req.Test, __MODULE__}
               )
    end
  end

  test "starts only the claimed run and receives a server-owned Graph request" do
    graph_request = %{
      session_id: "session-uid",
      thread_id: "thread-id",
      input_value: "Summarize this card",
      tweaks: %{LangboardCalledVariablesComponent: %{app_api_token: "one-time-token"}}
    }

    documents = ["card:123456789ab:description"]

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "POST"
      assert conn.request_path == "/auth/socket/board/project-uid/chat/runs/a%2Fb/start"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"active_document_names" => documents}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{
          run_uid: "a/b",
          attempt: 1,
          graph_request: graph_request,
          ai_message: %{
            uid: "ai-message-uid",
            chat_session_uid: "session-uid",
            message: %{content: ""}
          }
        })
      )
    end)

    assert {:ok, %{run_uid: "a/b", attempt: 1, graph_request: request, ai_message: ai_message}} =
             BoardChatRunClient.start("access-token", "project-uid", "a/b", documents,
               plug: {Req.Test, __MODULE__}
             )

    assert request["tweaks"]["LangboardCalledVariablesComponent"]["app_api_token"] ==
             "one-time-token"

    assert ai_message["uid"] == "ai-message-uid"
  end

  test "start rejects missing Graph identity or internal secret" do
    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"run_uid":"run-uid","attempt":1,"graph_request":{"session_id":"session","thread_id":"thread","tweaks":{}}})
      )
    end)

    assert {:error, :unavailable} =
             BoardChatRunClient.start("access-token", "project-uid", "run-uid", [],
               plug: {Req.Test, __MODULE__}
             )

    Application.put_env(:langboard_socket, :internal_api_secret, "")

    assert {:error, :unavailable} =
             BoardChatRunClient.start("access-token", "project-uid", "run-uid", [],
               plug: {Req.Test, __MODULE__}
             )
  end

  test "start accepts a server-owned Langflow request without a Graph identity" do
    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{
          run_uid: "run-uid",
          attempt: 1,
          langflow_request: %{
            session_id: "session-uid",
            thread_id: "thread-id",
            url: "https://langflow.example.test/api/v1/run/flow?stream=true",
            api_key: "server-only-key",
            request_body: %{session_id: "session-uid", input_value: "question"}
          },
          ai_message: %{uid: "ai-message-uid", chat_session_uid: "session-uid"}
        })
      )
    end)

    assert {:ok, %{langflow_request: request, attempt: 1}} =
             BoardChatRunClient.start("access-token", "project-uid", "run-uid", [],
               plug: {Req.Test, __MODULE__}
             )

    assert request["api_key"] == "server-only-key"
    assert request["request_body"]["input_value"] == "question"
  end

  test "start rejects Langflow body and message identities from another session" do
    for {body_session, message_session} <- [
          {"other-session", "session-uid"},
          {"session-uid", "other-session"}
        ] do
      Req.Test.expect(__MODULE__, fn conn ->
        conn
        |> Plug.Conn.put_resp_content_type("application/json")
        |> Plug.Conn.send_resp(
          200,
          Jason.encode!(%{
            run_uid: "run-uid",
            attempt: 1,
            langflow_request: %{
              session_id: "session-uid",
              thread_id: "thread-id",
              url: "https://langflow.example.test/api/v1/run/flow?stream=true",
              api_key: "server-only-key",
              request_body: %{session_id: body_session}
            },
            ai_message: %{uid: "ai-message-uid", chat_session_uid: message_session}
          })
        )
      end)

      assert {:error, :unavailable} =
               BoardChatRunClient.start("access-token", "project-uid", "run-uid", [],
                 plug: {Req.Test, __MODULE__}
               )
    end
  end

  test "lists accepted runs with the internal secret and no user bearer" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "GET"
      assert conn.request_path == "/auth/socket/board/chat/runs/accepted"
      assert conn.query_string == "limit=10"
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"runs":[{"run_uid":"run-uid","project_uid":"project-uid","scope_table":"card","scope_uid":"card-uid"}]})
      )
    end)

    assert {:ok, [%{"run_uid" => "run-uid"}]} =
             BoardChatRunClient.list_accepted(10, plug: {Req.Test, __MODULE__})
  end

  test "accepted-run scanning sends a bounded cursor without a user bearer" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "GET"
      assert conn.request_path == "/auth/socket/board/chat/runs/accepted"
      assert conn.query_string == "limit=10&after_run_uid=a%2Fb"
      assert Plug.Conn.get_req_header(conn, "authorization") == []

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"runs":[]}))
    end)

    assert {:ok, []} =
             BoardChatRunClient.list_accepted(10,
               after_run_uid: "a/b",
               plug: {Req.Test, __MODULE__}
             )

    assert {:error, :invalid_data} =
             BoardChatRunClient.list_accepted(10,
               after_run_uid: 123,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "accepted-run scanning fails closed for malformed scope or missing secret" do
    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"runs":[{"run_uid":"run-uid","project_uid":"project-uid","scope_table":"unknown","scope_uid":null}]})
      )
    end)

    assert {:error, :unavailable} =
             BoardChatRunClient.list_accepted(10, plug: {Req.Test, __MODULE__})

    Application.put_env(:langboard_socket, :internal_api_secret, "")

    assert {:error, :unavailable} =
             BoardChatRunClient.list_accepted(10, plug: {Req.Test, __MODULE__})
  end

  test "recovers an accepted run without a user bearer" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "POST"
      assert conn.request_path == "/auth/socket/board/project-uid/chat/runs/run-uid/recover-start"
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"active_document_names" => []}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"run_uid":"run-uid","attempt":1,"graph_request":{"session_id":"session-uid","thread_id":"thread-id","tweaks":{"LangboardCalledVariablesComponent":{"app_api_token":"one-time-token"}}},"ai_message":{"uid":"ai-message-uid","chat_session_uid":"session-uid"}})
      )
    end)

    assert {:ok, %{run_uid: "run-uid", attempt: 1}} =
             BoardChatRunClient.recover_start("project-uid", "run-uid", [],
               plug: {Req.Test, __MODULE__}
             )
  end

  test "finishes a claimed run through the internal secret without a user bearer" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "POST"
      assert conn.request_path == "/auth/socket/board/project-uid/chat/runs/a%2Fb/finish"
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)

      assert Jason.decode!(body) == %{
               "attempt" => 1,
               "status" => "completed",
               "output_text" => "Graph answer",
               "error_message" => nil
             }

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"run_uid":"a/b","attempt":1,"status":"completed"}))
    end)

    assert :ok =
             BoardChatRunClient.finish("project-uid", "a/b", 1, "completed", "Graph answer", nil,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "finish rejects stale attempts, malformed responses, and missing secret" do
    Req.Test.expect(__MODULE__, fn conn -> Plug.Conn.send_resp(conn, 409, "{}") end)

    assert {:error, :conflict} =
             BoardChatRunClient.finish("project-uid", "run-uid", 1, "completed", "", nil,
               plug: {Req.Test, __MODULE__}
             )

    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"run_uid":"other","attempt":1,"status":"completed"}))
    end)

    assert {:error, :unavailable} =
             BoardChatRunClient.finish("project-uid", "run-uid", 1, "completed", "", nil,
               plug: {Req.Test, __MODULE__}
             )

    Application.put_env(:langboard_socket, :internal_api_secret, "")

    assert {:error, :unavailable} =
             BoardChatRunClient.finish("project-uid", "run-uid", 1, "completed", "", nil,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "renews the current attempt without a user bearer" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/board/project-uid/chat/runs/run-uid/lease"
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"attempt" => 2}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"run_uid":"run-uid","attempt":2,"status":"streaming"}))
    end)

    assert :ok =
             BoardChatRunClient.renew_lease("project-uid", "run-uid", 2,
               plug: {Req.Test, __MODULE__}
             )

    assert {:error, :invalid_data} = BoardChatRunClient.renew_lease("project-uid", "run-uid", 0)
  end

  test "renews only a resuming attempt through the same fenced lease endpoint" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/board/project-uid/chat/runs/run-uid/lease"
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"attempt" => 2}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"run_uid":"run-uid","attempt":2,"status":"resuming"}))
    end)

    assert :ok =
             BoardChatRunClient.renew_resume_lease("project-uid", "run-uid", 2,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "pauses a claimed Graph run and returns only the persisted interrupt" do
    interrupt = %{"id" => "graph-interrupt", "value" => %{"type" => "approval_request"}}

    saved = %{
      "id" => "graph-interrupt",
      "value" => %{"type" => "approval_request", "approval_uid" => "approval-uid"}
    }

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/board/project-uid/chat/runs/run-uid/pause"
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)

      assert Jason.decode!(body) == %{
               "attempt" => 2,
               "output_text" => "Partial",
               "interrupt" => interrupt
             }

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{
          run_uid: "run-uid",
          attempt: 2,
          status: "awaiting_approval",
          interrupt: saved
        })
      )
    end)

    assert {:ok, ^saved} =
             BoardChatRunClient.pause("project-uid", "run-uid", 2, "Partial", interrupt,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "pause rejects a stale attempt or mismatched acknowledgement" do
    interrupt = %{"type" => "instruction_request"}
    Req.Test.expect(__MODULE__, fn conn -> Plug.Conn.send_resp(conn, 409, "{}") end)

    assert {:error, :conflict} =
             BoardChatRunClient.pause("project-uid", "run-uid", 1, "", interrupt,
               plug: {Req.Test, __MODULE__}
             )

    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"run_uid":"other","attempt":1,"status":"awaiting_approval","interrupt":{}})
      )
    end)

    assert {:error, :unavailable} =
             BoardChatRunClient.pause("project-uid", "run-uid", 1, "", interrupt,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "claims a Graph resume with both auth layers and validates the decision" do
    command = %{
      "message_uid" => "message-uid",
      "thread_id" => "graph-thread",
      "session_id" => "session-uid",
      "approval_uid" => "approval-uid",
      "resume" => %{"approved" => true, "rejected" => false}
    }

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/board/project-uid/chat/resume/claim"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == command

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{
          run_uid: "run-uid",
          attempt: 2,
          thread_id: "graph-thread",
          session_id: "session-uid",
          resume: %{
            approved: true,
            rejected: false,
            app_api_token: "private-graph-token",
            api_permission_level: "full_access"
          }
        })
      )
    end)

    assert {:ok, %{run_uid: "run-uid", attempt: 2, resume: resume}} =
             BoardChatRunClient.claim_resume("access-token", "project-uid", command,
               plug: {Req.Test, __MODULE__}
             )

    assert resume["app_api_token"] == "private-graph-token"
  end

  test "resume claim rejects malformed decisions and missing approval tokens" do
    decision = %{"approved" => true, "rejected" => false}

    command = %{
      "thread_id" => "graph-thread",
      "session_id" => "session-uid",
      "resume" => decision
    }

    invalid_resumes =
      [nil, false, [], "invalid", %{"approved" => false, "rejected" => true}] ++
        Enum.map([nil, "", false, 0, [], %{}], &Map.put(decision, "app_api_token", &1))

    for resume <- invalid_resumes do
      Req.Test.expect(__MODULE__, fn conn ->
        Req.Test.json(conn, %{
          run_uid: "run-uid",
          attempt: 2,
          thread_id: "graph-thread",
          session_id: "session-uid",
          resume: resume
        })
      end)

      assert {:error, :unavailable} =
               BoardChatRunClient.claim_resume("access-token", "project-uid", command,
                 plug: {Req.Test, __MODULE__}
               )
    end
  end

  test "a matching rejection does not require a tool execution token" do
    decision = %{"approved" => false, "rejected" => true, "reason" => "Not authorized"}

    command = %{
      "thread_id" => "graph-thread",
      "session_id" => "session-uid",
      "resume" => decision
    }

    Req.Test.expect(__MODULE__, fn conn ->
      Req.Test.json(conn, %{
        run_uid: "run-uid",
        attempt: 2,
        thread_id: "graph-thread",
        session_id: "session-uid",
        resume: decision
      })
    end)

    assert {:ok, %{resume: ^decision}} =
             BoardChatRunClient.claim_resume("access-token", "project-uid", command,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "resume claim fails closed on a stale response or missing secret" do
    command = %{
      "message_uid" => "message-uid",
      "thread_id" => "graph-thread",
      "session_id" => "session-uid",
      "resume" => %{"approved" => true, "rejected" => false}
    }

    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"run_uid":"run-uid","attempt":2,"thread_id":"other","session_id":"session-uid","resume":{"approved":true,"rejected":false,"app_api_token":"token"}})
      )
    end)

    assert {:error, :unavailable} =
             BoardChatRunClient.claim_resume("access-token", "project-uid", command,
               plug: {Req.Test, __MODULE__}
             )

    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"run_uid":"run-uid","attempt":2,"thread_id":"graph-thread","session_id":"session-uid","resume":{"approved":true,"rejected":false,"instruction":"unexpected","app_api_token":"token"}})
      )
    end)

    assert {:error, :unavailable} =
             BoardChatRunClient.claim_resume("access-token", "project-uid", command,
               plug: {Req.Test, __MODULE__}
             )

    Application.put_env(:langboard_socket, :internal_api_secret, "")

    assert {:error, :unavailable} =
             BoardChatRunClient.claim_resume("access-token", "project-uid", command,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "persists a Graph resume result before accepting its chat messages" do
    graph_result = %{response_text: "Graph answer", interrupt: nil}

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path ==
               "/auth/socket/board/project-uid/chat/runs/run-uid/resume/result"

      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)

      assert Jason.decode!(body) == %{
               "attempt" => 2,
               "thread_id" => "graph-thread",
               "session_id" => "session-uid",
               "response_text" => "Graph answer",
               "interrupt" => nil
             }

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{
          run_uid: "run-uid",
          attempt: 2,
          status: "completed",
          newly_applied: true,
          original_message: %{uid: "original-uid", chat_session_uid: "session-uid"},
          resumed_message: %{uid: "resumed-uid", chat_session_uid: "session-uid"}
        })
      )
    end)

    assert {:ok, %{status: "completed", newly_applied: true, resumed_message: resumed}} =
             BoardChatRunClient.complete_resume(
               "project-uid",
               "run-uid",
               2,
               "graph-thread",
               "session-uid",
               graph_result,
               plug: {Req.Test, __MODULE__}
             )

    assert resumed["uid"] == "resumed-uid"
  end

  test "resume result rejects a missing persisted interrupt or invalid input" do
    interrupt = %{
      "id" => "next",
      "value" => %{"thread_id" => "graph-thread", "session_id" => "session-uid"}
    }

    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{
          run_uid: "run-uid",
          attempt: 2,
          status: "awaiting_approval",
          newly_applied: true,
          original_message: %{uid: "original-uid", chat_session_uid: "session-uid"},
          resumed_message: %{uid: "resumed-uid", chat_session_uid: "session-uid"}
        })
      )
    end)

    assert {:error, :unavailable} =
             BoardChatRunClient.complete_resume(
               "project-uid",
               "run-uid",
               2,
               "graph-thread",
               "session-uid",
               %{response_text: "Partial", interrupt: interrupt},
               plug: {Req.Test, __MODULE__}
             )

    assert {:error, :invalid_data} =
             BoardChatRunClient.complete_resume(
               "project-uid",
               "run-uid",
               2,
               "graph-thread",
               "session-uid",
               %{response_text: "Partial"}
             )
  end
end
