defmodule LangboardSocket.EditorRunClientTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.EditorRunClient

  @secret String.duplicate("s", 32)
  @task_id "0750a86b-6cd7-492c-b846-6104e3c4c7c9"
  @command %{
    "project_uid" => "123456789ab",
    "scope_uid" => "123456789ac",
    "document_name" => "card:123456789ac:description",
    "task_id" => @task_id,
    "kind" => "editor_chat",
    "system" => "Instructions",
    "messages" => [%{"role" => "user", "content" => "Draft"}]
  }

  setup do
    previous = Application.fetch_env!(:langboard_socket, :internal_api_secret)
    Application.put_env(:langboard_socket, :internal_api_secret, @secret)
    on_exit(fn -> Application.put_env(:langboard_socket, :internal_api_secret, previous) end)
    :ok
  end

  test "rejects empty and non-binary credentials and identities before HTTP dispatch" do
    options = [plug: {Req.Test, __MODULE__}]

    for invalid <- [nil, "", 0, false, [], %{}] do
      assert {:error, :invalid_data} = EditorRunClient.accept(invalid, @command, options)
      assert {:error, :invalid_data} = EditorRunClient.start(invalid, options)

      assert {:error, :invalid_data} =
               EditorRunClient.cancel("access-token", invalid, "editor_chat", @task_id, options)

      assert {:error, :invalid_data} =
               EditorRunClient.status(
                 "access-token",
                 "project-uid",
                 "editor_chat",
                 invalid,
                 options
               )
    end
  end

  test "acceptance sends the bounded editor command with both credentials" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-ai/runs"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == @command

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"run_uid":"run-uid","status":"accepted","accepted":true}))
    end)

    assert {:ok, %{"run_uid" => "run-uid", "accepted" => true}} =
             EditorRunClient.accept("access-token", @command, plug: {Req.Test, __MODULE__})
  end

  test "start requires a server-owned Graph request and no browser token" do
    request = %{
      session_id: "session",
      thread_id: "thread",
      input_value: "user: Draft",
      tweaks: %{LangboardCalledVariablesComponent: %{app_api_token: "graph-token"}}
    }

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-ai/runs/a%2Fb/start"
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{run_uid: "a/b", attempt: 1, graph_request: request})
      )
    end)

    assert {:ok, %{attempt: 1, graph_request: %{"session_id" => "session"}}} =
             EditorRunClient.start("a/b", plug: {Req.Test, __MODULE__})

    Req.Test.expect(__MODULE__, fn conn ->
      Plug.Conn.send_resp(conn, 200, ~s({"run_uid":"a/b","attempt":1,"graph_request":{}}))
    end)

    assert {:error, :unavailable} = EditorRunClient.start("a/b", plug: {Req.Test, __MODULE__})
  end

  test "cancel checks the server task identity and finish is attempt fenced" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-ai/cancel"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
      {:ok, body, conn} = Plug.Conn.read_body(conn)

      assert Jason.decode!(body) == %{
               "project_uid" => "project-uid",
               "kind" => "editor_chat",
               "task_id" => @task_id
             }

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{run_uid: "run-uid", status: "cancelled", task_id: @task_id})
      )
    end)

    assert {:ok, "run-uid"} =
             EditorRunClient.cancel("access-token", "project-uid", "editor_chat", @task_id,
               plug: {Req.Test, __MODULE__}
             )

    Req.Test.expect(__MODULE__, fn conn ->
      Plug.Conn.send_resp(
        conn,
        200,
        ~s({"run_uid":"run-uid","status":"cancelled","task_id":"other"})
      )
    end)

    assert {:error, :unavailable} =
             EditorRunClient.cancel("access-token", "project-uid", "editor_chat", @task_id,
               plug: {Req.Test, __MODULE__}
             )

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-ai/runs/run-uid/finish"
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body)["attempt"] == 2

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"run_uid":"run-uid","attempt":2,"status":"completed"}))
    end)

    assert :ok =
             EditorRunClient.finish("run-uid", 2, "completed", "Done", nil,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "status reads the fenced editor run with the user bearer" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "POST"
      assert conn.request_path == "/auth/socket/editor-ai/status"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)

      assert Jason.decode!(body) == %{
               "project_uid" => "project-uid",
               "kind" => "editor_chat",
               "task_id" => @task_id
             }

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{
          run_uid: "run-uid",
          task_id: @task_id,
          kind: "editor_chat",
          status: "completed",
          attempt: 1,
          output_text: "Done",
          error_message: nil
        })
      )
    end)

    assert {:ok, %{"status" => "completed", "output_text" => "Done"}} =
             EditorRunClient.status("access-token", "project-uid", "editor_chat", @task_id,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "pause is internal-only and requires a persisted interrupt response" do
    interrupt = %{"value" => %{"type" => "approval_request"}}

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-ai/runs/run-uid/pause"
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
          interrupt: interrupt
        })
      )
    end)

    assert {:ok, ^interrupt} =
             EditorRunClient.pause("run-uid", 2, "Partial", interrupt,
               plug: {Req.Test, __MODULE__}
             )

    Req.Test.expect(__MODULE__, fn conn ->
      Plug.Conn.send_resp(
        conn,
        200,
        ~s({"run_uid":"run-uid","attempt":2,"status":"awaiting_approval"})
      )
    end)

    assert {:error, :unavailable} =
             EditorRunClient.pause("run-uid", 2, "", interrupt, plug: {Req.Test, __MODULE__})

    assert {:error, :invalid_data} = EditorRunClient.pause("run-uid", 0, "", interrupt)
  end

  test "editor approval claim uses the approver token and returns the server-owned resume" do
    decision = %{"approved" => true, "rejected" => false}

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-ai/approvals/approval-uid/claim"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer approver-token"]
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"project_uid" => "project-uid", "resume" => decision}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{
          run_uid: "run-uid",
          attempt: 2,
          thread_id: "thread-uid",
          session_id: "session-uid",
          resume: Map.put(decision, "app_api_token", "one-time-token")
        })
      )
    end)

    assert {:ok, %{run_uid: "run-uid", resume: %{"app_api_token" => "one-time-token"}}} =
             EditorRunClient.claim_resume(
               "approver-token",
               "project-uid",
               "approval-uid",
               decision,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "editor approval claim rejects a changed decision or missing approval token" do
    decision = %{"approved" => true, "rejected" => false}

    for resume <- [
          %{"approved" => false, "rejected" => true, "app_api_token" => "token"},
          %{"approved" => true, "rejected" => false}
        ] do
      Req.Test.expect(__MODULE__, fn conn ->
        conn
        |> Plug.Conn.put_resp_content_type("application/json")
        |> Plug.Conn.send_resp(
          200,
          Jason.encode!(%{
            run_uid: "run-uid",
            attempt: 2,
            thread_id: "thread-uid",
            session_id: "session-uid",
            resume: resume
          })
        )
      end)

      assert {:error, :unavailable} =
               EditorRunClient.claim_resume(
                 "approver-token",
                 "project-uid",
                 "approval-uid",
                 decision,
                 plug: {Req.Test, __MODULE__}
               )
    end
  end

  test "editor approval result and lease use internal authentication only" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-ai/runs/run-uid/resume/result"
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]
      {:ok, body, conn} = Plug.Conn.read_body(conn)

      assert Jason.decode!(body) == %{
               "attempt" => 2,
               "thread_id" => "thread-uid",
               "session_id" => "session-uid",
               "response_text" => "Done",
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
          output_text: "Done"
        })
      )
    end)

    assert {:ok, %{status: "completed", output_text: "Done"}} =
             EditorRunClient.complete_resume(
               "run-uid",
               2,
               "thread-uid",
               "session-uid",
               %{response_text: "Done", interrupt: nil},
               plug: {Req.Test, __MODULE__}
             )

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-ai/runs/run-uid/resume/lease"
      assert Plug.Conn.get_req_header(conn, "authorization") == []

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"run_uid":"run-uid","attempt":2,"status":"resuming"}))
    end)

    assert :ok = EditorRunClient.renew_resume_lease("run-uid", 2, plug: {Req.Test, __MODULE__})
  end

  test "denial, stale attempt, missing secret, and malformed success fail closed" do
    for {status, expected} <- [
          {400, :invalid_data},
          {401, :unauthorized},
          {403, :forbidden},
          {409, :conflict},
          {500, :unavailable}
        ] do
      Req.Test.expect(__MODULE__, fn conn -> Plug.Conn.send_resp(conn, status, "{}") end)

      assert {:error, ^expected} =
               EditorRunClient.accept("token", @command, plug: {Req.Test, __MODULE__})
    end

    Req.Test.expect(__MODULE__, fn conn ->
      Plug.Conn.send_resp(conn, 200, ~s({"run_uid":"run-uid","status":"accepted"}))
    end)

    assert {:error, :unavailable} =
             EditorRunClient.accept("token", @command, plug: {Req.Test, __MODULE__})

    Application.put_env(:langboard_socket, :internal_api_secret, "")
    assert {:error, :unavailable} = EditorRunClient.accept("token", @command)
  end

  test "accepted recovery list is internal-only and rejects malformed rows" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-ai/runs/accepted"
      assert conn.query_string == "limit=2&after_run_uid=previous"
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@secret]

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{
          runs: [
            %{run_uid: "next", project_uid: "project", task_id: @task_id, kind: "editor_chat"}
          ]
        })
      )
    end)

    assert {:ok, [%{"run_uid" => "next"}]} =
             EditorRunClient.list_accepted(2,
               after_run_uid: "previous",
               plug: {Req.Test, __MODULE__}
             )

    Req.Test.expect(__MODULE__, fn conn ->
      Plug.Conn.send_resp(conn, 200, ~s({"runs":[{"run_uid":"next","kind":"board_chat"}]}))
    end)

    assert {:error, :unavailable} =
             EditorRunClient.list_accepted(2, plug: {Req.Test, __MODULE__})

    assert {:error, :invalid_data} = EditorRunClient.list_accepted(101)
    assert {:error, :invalid_data} = EditorRunClient.list_accepted(1, after_run_uid: "")
  end
end
