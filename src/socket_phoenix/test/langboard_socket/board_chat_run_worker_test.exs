defmodule LangboardSocket.BoardChatRunWorkerTest do
  use ExUnit.Case

  alias LangboardSocket.BoardChatRunWorker
  alias LangboardSocket.LangflowStreamClient

  defmodule RunClient do
    def accept(_token, _project_uid, command) do
      send(Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid), {
        :accepted_command,
        command
      })

      Application.fetch_env!(:langboard_socket, :board_chat_worker_test_accept)
    end

    def start(_token, _project_uid, _run_uid, documents) do
      send(
        Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid),
        {:start_documents, documents}
      )

      Application.fetch_env!(:langboard_socket, :board_chat_worker_test_start)
    end

    def recover_start(project_uid, run_uid, documents) do
      send(Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid), {
        :recovered_start,
        project_uid,
        run_uid,
        documents
      })

      Application.fetch_env!(:langboard_socket, :board_chat_worker_test_start)
    end

    def renew_lease(project_uid, run_uid, attempt) do
      send(Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid), {
        :renewed,
        project_uid,
        run_uid,
        attempt
      })

      Application.get_env(:langboard_socket, :board_chat_worker_test_renew_result, :ok)
    end

    def finish(project_uid, run_uid, attempt, status, content, error) do
      send(Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid), {
        :finished,
        project_uid,
        run_uid,
        attempt,
        status,
        content,
        error
      })

      Application.get_env(:langboard_socket, :board_chat_worker_test_finish_result, :ok)
    end

    def pause(project_uid, run_uid, attempt, content, interrupt) do
      send(Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid), {
        :paused,
        project_uid,
        run_uid,
        attempt,
        content,
        interrupt
      })

      Application.get_env(
        :langboard_socket,
        :board_chat_worker_test_pause_result,
        {:ok, %{"value" => %{"type" => "approval_request", "approval_uid" => "approval-uid"}}}
      )
    end
  end

  defmodule GraphClient do
    def stream(_session_id, _request, on_event) do
      send(Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid), {
        :graph_started,
        self()
      })

      case Application.fetch_env!(:langboard_socket, :board_chat_worker_test_events) do
        :crash ->
          raise "Graph task crashed"

        :wait ->
          receive do
            :release ->
              :ok = on_event.({:token, "Graph answer"})
              :ok = on_event.(:end)
              :ok
          end

        events ->
          Enum.each(events, fn event -> :ok = on_event.(event) end)
          :ok
      end
    end
  end

  defmodule BackpressureGraphClient do
    def stream(_session_id, _request, on_event) do
      parent = Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid)
      send(parent, {:graph_started, self()})

      if Application.get_env(:langboard_socket, :board_chat_worker_test_events) == :wait do
        receive do
          :release -> :ok
        end
      end

      result = on_event.({:token, "Graph answer"})
      send(parent, {:graph_callback_result, result})
      result
    end
  end

  defmodule LangflowClient do
    def stream(session_id, request, on_event) do
      send(Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid), {
        :langflow_started,
        session_id,
        request
      })

      :ok = on_event.({:token, "Langflow answer"})
      :ok = on_event.(:end)
      :ok
    end
  end

  defmodule ActiveDocuments do
    def collect(project_uid, scope_table, scope_uid) do
      send(Application.fetch_env!(:langboard_socket, :board_chat_worker_test_pid), {
        :collect_documents,
        project_uid,
        scope_table,
        scope_uid
      })

      Application.fetch_env!(:langboard_socket, :board_chat_worker_test_documents)
    end
  end

  setup do
    timeout = Application.fetch_env!(:langboard_socket, :graph_timeout_ms)
    max_queue = Application.fetch_env!(:langboard_socket, :socket_max_outbound_queue_messages)
    Application.put_env(:langboard_socket, :board_chat_worker_test_pid, self())

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_accept,
      {:ok,
       %{
         "run_uid" => "run-uid",
         "status" => "accepted",
         "accepted" => true,
         "session" => %{"uid" => "session-uid"},
         "user_message" => %{"uid" => "user-message-uid", "chat_session_uid" => "session-uid"}
       }}
    )

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_start,
      {:ok,
       %{
         attempt: 1,
         graph_request: %{"session_id" => "session-uid"},
         ai_message: %{"uid" => "ai-message-uid"}
       }}
    )

    on_exit(fn ->
      Application.put_env(:langboard_socket, :graph_timeout_ms, timeout)
      Application.put_env(:langboard_socket, :socket_max_outbound_queue_messages, max_queue)
      Application.delete_env(:langboard_socket, :board_chat_worker_test_pid)
      Application.delete_env(:langboard_socket, :board_chat_worker_test_start)
      Application.delete_env(:langboard_socket, :board_chat_worker_test_events)
      Application.delete_env(:langboard_socket, :board_chat_worker_test_renew_result)
      Application.delete_env(:langboard_socket, :board_chat_worker_test_pause_result)
      Application.delete_env(:langboard_socket, :board_chat_worker_test_finish_result)
      Application.delete_env(:langboard_socket, :board_chat_worker_test_documents)
      Application.delete_env(:langboard_socket, :board_chat_worker_test_accept)
    end)

    :ok
  end

  test "persists a complete Graph answer before announcing success" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [
      {:token, "Graph answer"},
      :end
    ])

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:board_chat_run_event, "run-uid", :start,
                    %{ai_message: %{"uid" => "ai-message-uid"}}}

    assert_receive {:board_chat_run_event, "run-uid", :buffer,
                    %{uid: "ai-message-uid", message: %{content: "Graph answer"}}}

    assert_receive {:finished, "project-uid", "run-uid", 1, "completed", "Graph answer", nil}

    assert_receive {:board_chat_run_event, "run-uid", :end,
                    %{uid: "ai-message-uid", status: :success}}

    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
  end

  test "a Langflow run uses its external stream client and persists the same durable result" do
    request = %{"session_id" => "session-uid", "url" => "https://langflow.example.test/run"}

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_start,
      {:ok,
       %{
         attempt: 1,
         langflow_request: request,
         ai_message: %{"uid" => "ai-message-uid"}
       }}
    )

    worker = start_worker(langflow_client: LangflowClient)
    monitor = Process.monitor(worker)

    assert_receive {:langflow_started, "session-uid", ^request}

    assert_receive {:board_chat_run_event, "run-uid", :buffer,
                    %{uid: "ai-message-uid", message: %{content: "Langflow answer"}}}

    assert_receive {:finished, "project-uid", "run-uid", 1, "completed", "Langflow answer", nil}
    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :success}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    refute_receive {:graph_started, _pid}
  end

  test "a Langflow HTTP stream finishes through the durable run worker" do
    test_pid = self()

    url =
      start_langflow_server(fn conn, _opts ->
        {:ok, body, conn} = Plug.Conn.read_body(conn)

        send(
          test_pid,
          {:langflow_http_request, conn.request_path, Plug.Conn.get_req_header(conn, "x-api-key"),
           Jason.decode!(body)}
        )

        conn = Plug.Conn.send_chunked(conn, 200)

        {:ok, conn} =
          Plug.Conn.chunk(conn, langflow_frame("token", %{"token" => true, "chunk" => "draft"}))

        {:ok, conn} =
          Plug.Conn.chunk(
            conn,
            langflow_frame("add_message", %{"sender" => "AI", "text" => "final"})
          )

        {:ok, conn} = Plug.Conn.chunk(conn, langflow_frame("end", %{}))
        conn
      end)

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_start,
      {:ok,
       %{
         attempt: 1,
         langflow_request: %{
           "session_id" => "session-uid",
           "url" => url <> "/api/v1/run/flow?stream=true",
           "api_key" => "server-key",
           "request_body" => %{"session_id" => "session-uid", "input_value" => "question"}
         },
         ai_message: %{"uid" => "ai-message-uid"}
       }}
    )

    worker = start_worker(langflow_client: LangflowStreamClient)
    monitor = Process.monitor(worker)

    assert_receive {:langflow_http_request, "/api/v1/run/flow", ["server-key"],
                    %{"session_id" => "session-uid", "input_value" => "question"}},
                   2_000

    assert_receive {:board_chat_run_event, "run-uid", :buffer,
                    %{uid: "ai-message-uid", message: %{content: "final"}}}

    assert_receive {:finished, "project-uid", "run-uid", 1, "completed", "final", nil}
    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :success}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    refute_receive {:graph_started, _pid}
  end

  test "a Langflow HTTP error frame cannot finish a partial answer as success" do
    url =
      start_langflow_server(fn conn, _opts ->
        conn = Plug.Conn.send_chunked(conn, 200)

        {:ok, conn} =
          Plug.Conn.chunk(conn, langflow_frame("token", %{"token" => true, "chunk" => "partial"}))

        {:ok, conn} =
          Plug.Conn.chunk(conn, langflow_frame("error", %{"message" => "upstream failed"}))

        conn
      end)

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_start,
      {:ok,
       %{
         attempt: 1,
         langflow_request: %{
           "session_id" => "session-uid",
           "url" => url <> "/api/v1/run/flow?stream=true",
           "api_key" => "server-key",
           "request_body" => %{"session_id" => "session-uid"}
         },
         ai_message: %{"uid" => "ai-message-uid"}
       }}
    )

    worker = start_worker(langflow_client: LangflowStreamClient)
    monitor = Process.monitor(worker)

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Langflow streaming failed"},
                   2_000

    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :failed}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    refute_receive {:finished, _project, _run, _attempt, "completed", _content, _error}
  end

  test "an approval interrupt is published only after the pause is persisted" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [
      {:token, "Partial answer"},
      {:interrupt, %{"type" => "approval_request"}},
      :end
    ])

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:paused, "project-uid", "run-uid", 1, "Partial answer",
                    %{"type" => "approval_request"}}

    assert_receive {:board_chat_run_event, "run-uid", :buffer,
                    %{interrupt: %{"value" => %{"approval_uid" => "approval-uid"}}}}

    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :success}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    refute_receive {:finished, _project, _run, _attempt, _status, _content, _error}
  end

  test "a failed pause never announces a successful approval interrupt" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [
      {:interrupt, %{"type" => "approval_request"}},
      :end
    ])

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_pause_result,
      {:error, :unavailable}
    )

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:paused, "project-uid", "run-uid", 1, "", _interrupt}

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Graph interruption could not be persisted"}

    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :failed}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    refute_receive {:board_chat_run_event, "run-uid", :buffer, %{interrupt: _interrupt}}
  end

  test "a failed completion acknowledgment leaves the persisted result uncertain" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [
      {:token, "Graph answer"},
      :end
    ])

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_finish_result,
      {:error, :unavailable}
    )

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:finished, "project-uid", "run-uid", 1, "completed", "Graph answer", nil}
    assert_receive {:board_chat_run_event, "run-uid", :result_unknown, %{}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:board_chat_run_event, "run-uid", :end, _data}
  end

  test "a failed pause and failed fallback remain uncertain" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [
      {:interrupt, %{"type" => "approval_request"}},
      :end
    ])

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_pause_result,
      {:error, :unavailable}
    )

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_finish_result,
      {:error, :unavailable}
    )

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:paused, "project-uid", "run-uid", 1, "", _interrupt}

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Graph interruption could not be persisted"}

    assert_receive {:board_chat_run_event, "run-uid", :result_unknown, %{}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:board_chat_run_event, "run-uid", :end, _data}
  end

  test "multiple interrupts cannot create an ambiguous pending approval" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [
      {:interrupt, %{"id" => "first"}},
      {:interrupt, %{"id" => "second"}},
      :end
    ])

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Graph streaming failed"}

    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :failed}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    refute_receive {:paused, _project, _run, _attempt, _content, _interrupt}
  end

  test "an empty Graph response is not persisted as a successful answer" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [:end])
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Graph streaming failed"}

    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :failed}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
  end

  test "a Graph error after a partial answer cannot be announced as success" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [
      {:token, "Partial answer"},
      {:error, "Graph unavailable"}
    ])

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Graph streaming failed"}

    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :failed}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
  end

  test "a Graph task crash is marked failed" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, :crash)
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Graph worker exited before completion"}

    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :failed}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
  end

  test "a full receiver queue stops Graph input without dropping the terminal result" do
    Application.put_env(:langboard_socket, :socket_max_outbound_queue_messages, 2)
    parent = self()

    receiver =
      spawn(fn ->
        receive do
          :release -> :ok
        end

        for _ <- 1..5 do
          receive do
            message -> send(parent, {:receiver_message, message})
          end
        end
      end)

    on_exit(fn -> Process.exit(receiver, :kill) end)
    send(receiver, :padding)
    send(receiver, :padding)

    worker = start_worker(receiver: receiver, graph_client: BackpressureGraphClient)
    monitor = Process.monitor(worker)

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Graph streaming failed"}

    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    send(receiver, :release)

    assert_receive {:receiver_message, :padding}
    assert_receive {:receiver_message, :padding}

    assert_receive {:receiver_message,
                    {:board_chat_run_event, "run-uid", :accepted, %{run_uid: "run-uid"}}}

    assert_receive {:receiver_message,
                    {:board_chat_run_event, "run-uid", :start,
                     %{ai_message: %{"uid" => "ai-message-uid"}}}}

    assert_receive {:receiver_message,
                    {:board_chat_run_event, "run-uid", :end,
                     %{uid: "ai-message-uid", status: :failed}}}
  end

  test "a full worker queue rejects Graph input even without a socket receiver" do
    Application.put_env(:langboard_socket, :socket_max_outbound_queue_messages, 2)
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, :wait)
    worker = start_worker(receiver: nil, graph_client: BackpressureGraphClient)
    monitor = Process.monitor(worker)
    assert_receive {:graph_started, graph_pid}

    :ok = :sys.suspend(worker)

    try do
      send(worker, :padding)
      send(worker, :padding)
      send(graph_pid, :release)
      assert_receive {:graph_callback_result, {:error, :backpressure}}
      refute_receive {:finished, _, _, _, _, _, _}
    after
      :sys.resume(worker)
    end

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Graph streaming failed"}

    assert_receive {:DOWN, ^monitor, :process, ^worker, :normal}
  end

  test "renews the claimed attempt while the Graph request is active" do
    Application.put_env(:langboard_socket, :graph_timeout_ms, 4_000)
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, :wait)
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:graph_started, graph_pid}
    assert_receive {:renewed, "project-uid", "run-uid", 1}, 1_500
    send(graph_pid, :release)
    assert_receive {:finished, "project-uid", "run-uid", 1, "completed", "Graph answer", nil}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
  end

  test "a disconnected socket does not abort an accepted Graph run" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, :wait)

    receiver =
      spawn(fn ->
        receive do
          :stop -> :ok
        end
      end)

    worker = start_worker(receiver: receiver)
    monitor = Process.monitor(worker)
    assert_receive {:graph_started, graph_pid}

    Process.exit(receiver, :kill)
    send(graph_pid, :release)

    assert_receive {:finished, "project-uid", "run-uid", 1, "completed", "Graph answer", nil}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
  end

  test "a persisted cancellation stops the active Graph task" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, :wait)
    worker = start_worker()
    monitor = Process.monitor(worker)
    assert_receive {:graph_started, graph_pid}
    graph_monitor = Process.monitor(graph_pid)

    assert :ok =
             Phoenix.PubSub.broadcast(
               LangboardSocket.PubSub,
               BoardChatRunWorker.cancel_topic("run-uid"),
               {:board_chat_run_cancelled, "run-uid"}
             )

    assert_receive {:board_chat_run_event, "run-uid", :cancelled, %{}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    assert_receive {:DOWN, ^graph_monitor, :process, ^graph_pid, _reason}
    refute_receive {:finished, _project, _run, _attempt, _status, _content, _error}
  end

  test "a rejected start cannot launch a Graph task" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_start, {:error, :conflict})
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:board_chat_run_event, "run-uid", :start_failed, %{reason: :conflict}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    refute_receive {:graph_started, _pid}
  end

  test "recovered work uses the persisted scope and finishes without a socket receiver" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_documents, {:ok, []})
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, :wait)

    worker =
      start_worker(
        recovery_run: %{
          "run_uid" => "run-uid",
          "scope_table" => "card",
          "scope_uid" => "card-uid"
        },
        command: nil,
        token: nil,
        receiver: nil,
        active_documents_client: ActiveDocuments
      )

    monitor = Process.monitor(worker)
    assert_receive {:collect_documents, "project-uid", "card", "card-uid"}
    assert_receive {:recovered_start, "project-uid", "run-uid", []}
    assert_receive {:graph_started, graph_pid}
    send(graph_pid, :release)
    assert_receive {:finished, "project-uid", "run-uid", 1, "completed", "Graph answer", nil}
    assert_receive {:DOWN, ^monitor, :process, ^worker, :normal}
    refute_receive {:board_chat_run_event, "run-uid", _event, _data}
    refute_receive {:accepted_command, _command}
  end

  test "a competing recovery claim cannot launch a second Graph task" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_start, {:error, :conflict})

    worker =
      start_worker(
        recovery_run: %{"run_uid" => "run-uid", "scope_table" => "project"},
        command: nil,
        token: nil,
        receiver: nil
      )

    monitor = Process.monitor(worker)
    assert_receive {:recovered_start, "project-uid", "run-uid", []}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    refute_receive {:graph_started, _pid}
  end

  test "an acceptance failure cannot claim or start a Graph run" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_accept, {:error, :unavailable})
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:board_chat_run_event, "run-uid", :accept_failed, %{reason: :unavailable}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:start_documents, _documents}
    refute_receive {:graph_started, _pid}
  end

  test "a completed duplicate is not executed again" do
    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_accept,
      {:ok,
       %{
         "run_uid" => "run-uid",
         "status" => "completed",
         "accepted" => false,
         "session" => %{"uid" => "session-uid"},
         "user_message" => %{"uid" => "user-message-uid", "chat_session_uid" => "session-uid"}
       }}
    )

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:board_chat_run_event, "run-uid", :already_started,
                    %{status: "completed", run_uid: "run-uid"}}

    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:start_documents, _documents}
    refute_receive {:graph_started, _pid}
  end

  test "an accepted duplicate still competes for the fenced start" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [:end])

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_accept,
      {:ok,
       %{
         "run_uid" => "run-uid",
         "status" => "accepted",
         "accepted" => false,
         "session" => %{"uid" => "session-uid"},
         "user_message" => %{"uid" => "user-message-uid", "chat_session_uid" => "session-uid"}
       }}
    )

    worker = start_worker()
    monitor = Process.monitor(worker)
    assert_receive {:board_chat_run_event, "run-uid", :accepted, %{accepted: false}}
    assert_receive {:start_documents, []}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
  end

  test "passes only the selected scope's live documents to the run start" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, [:end])

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_documents,
      {:ok, ["card:card-uid:description"]}
    )

    worker =
      start_worker(
        command: %{"task_id" => "run-uid", "scope_table" => "card", "scope_uid" => "card-uid"},
        active_documents_client: ActiveDocuments
      )

    monitor = Process.monitor(worker)
    assert_receive {:collect_documents, "project-uid", "card", "card-uid"}
    assert_receive {:start_documents, ["card:card-uid:description"]}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
  end

  test "does not claim a run when scoped editor state cannot be collected" do
    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_documents,
      {:error, :unavailable}
    )

    worker =
      start_worker(
        command: %{"task_id" => "run-uid", "scope_table" => "card", "scope_uid" => "card-uid"},
        active_documents_client: ActiveDocuments
      )

    monitor = Process.monitor(worker)
    assert_receive {:board_chat_run_event, "run-uid", :start_failed, %{reason: :unavailable}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:start_documents, _documents}
  end

  test "a full Graph supervisor closes the claimed attempt as failed" do
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, :wait)
    supervisor = start_supervised!({Task.Supervisor, max_children: 1})

    {:ok, occupying_task} =
      Task.Supervisor.start_child(supervisor, fn ->
        receive do
          :release -> :ok
        end
      end)

    worker = start_worker(graph_supervisor: supervisor)
    monitor = Process.monitor(worker)

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Graph worker capacity is unavailable"}

    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :failed}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
    refute_receive {:graph_started, _pid}
    send(occupying_task, :release)
  end

  test "lost lease stops the Graph task without claiming success" do
    Application.put_env(:langboard_socket, :graph_timeout_ms, 4_000)
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, :wait)

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_renew_result,
      {:error, :conflict}
    )

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:graph_started, _graph_pid}
    assert_receive {:renewed, "project-uid", "run-uid", 1}, 1_500
    assert_receive {:board_chat_run_event, "run-uid", :lease_lost, %{}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, :normal}
    refute_receive {:finished, _project_uid, _run_uid, _attempt, "completed", _content, _error}
  end

  test "permanent lease authorization failure fails the run and stops Graph" do
    Application.put_env(:langboard_socket, :graph_timeout_ms, 4_000)
    Application.put_env(:langboard_socket, :board_chat_worker_test_events, :wait)

    Application.put_env(
      :langboard_socket,
      :board_chat_worker_test_renew_result,
      {:error, :forbidden}
    )

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:graph_started, graph_pid}
    graph_monitor = Process.monitor(graph_pid)
    assert_receive {:renewed, "project-uid", "run-uid", 1}, 1_500

    assert_receive {:finished, "project-uid", "run-uid", 1, "failed", "",
                    "Board chat access was revoked"}

    assert_receive {:board_chat_run_event, "run-uid", :end, %{status: :failed}}
    assert_receive {:DOWN, ^monitor, :process, ^worker, :normal}
    assert_receive {:DOWN, ^graph_monitor, :process, ^graph_pid, _reason}
  end

  defp start_worker(options \\ []) do
    worker_options =
      Keyword.merge(
        [
          token: "user-token",
          project_uid: "project-uid",
          command: %{"task_id" => "run-uid", "scope_table" => "project"},
          receiver: self(),
          run_client: RunClient,
          graph_client: GraphClient
        ],
        options
      )

    {:ok, worker} =
      DynamicSupervisor.start_child(
        LangboardSocket.BoardChatRunSupervisor,
        {BoardChatRunWorker, worker_options}
      )

    worker
  end

  defp start_langflow_server(plug) do
    server =
      start_supervised!(
        {Bandit, plug: plug, scheme: :http, ip: {127, 0, 0, 1}, port: 0, startup_log: false}
      )

    {:ok, {{127, 0, 0, 1}, port}} = ThousandIsland.listener_info(server)
    "http://127.0.0.1:#{port}"
  end

  defp langflow_frame(event, data),
    do: Jason.encode!(%{"event" => event, "data" => data}) <> "\n\n"
end
