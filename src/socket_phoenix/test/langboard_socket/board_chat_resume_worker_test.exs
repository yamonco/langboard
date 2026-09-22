defmodule LangboardSocket.BoardChatResumeWorkerTest do
  use ExUnit.Case

  alias LangboardSocket.BoardChatResumeWorker

  defmodule RunClient do
    def claim_resume(_token, _project_uid, _command) do
      Application.fetch_env!(:langboard_socket, :resume_worker_test_claim)
    end

    def complete_resume(project_uid, run_uid, attempt, thread_id, session_id, result) do
      send(Application.fetch_env!(:langboard_socket, :resume_worker_test_pid), {
        :completed,
        project_uid,
        run_uid,
        attempt,
        thread_id,
        session_id,
        result
      })

      Application.fetch_env!(:langboard_socket, :resume_worker_test_complete)
    end

    def renew_resume_lease(project_uid, run_uid, attempt) do
      send(Application.fetch_env!(:langboard_socket, :resume_worker_test_pid), {
        :renewed,
        project_uid,
        run_uid,
        attempt
      })

      Application.get_env(:langboard_socket, :resume_worker_test_renew, :ok)
    end
  end

  defmodule GraphClient do
    def resume(thread_id, session_id, decision) do
      send(Application.fetch_env!(:langboard_socket, :resume_worker_test_pid), {
        :graph_started,
        self(),
        thread_id,
        session_id,
        decision
      })

      case Application.fetch_env!(:langboard_socket, :resume_worker_test_graph) do
        :crash -> raise "Graph resume crashed"
        :wait -> receive do: (:release -> {:ok, %{response_text: "Answer", interrupt: nil}})
        result -> result
      end
    end
  end

  setup do
    timeout = Application.fetch_env!(:langboard_socket, :graph_timeout_ms)
    Application.put_env(:langboard_socket, :resume_worker_test_pid, self())

    Application.put_env(
      :langboard_socket,
      :resume_worker_test_claim,
      {:ok,
       %{
         run_uid: "run-uid",
         attempt: 2,
         thread_id: "thread-uid",
         session_id: "session-uid",
         resume: %{"approved" => false, "rejected" => true}
       }}
    )

    Application.put_env(
      :langboard_socket,
      :resume_worker_test_graph,
      {:ok, %{response_text: "Answer", interrupt: nil}}
    )

    Application.put_env(
      :langboard_socket,
      :resume_worker_test_complete,
      {:ok,
       %{
         original_message: %{"uid" => "original-uid", "message" => %{"content" => "Partial"}},
         resumed_message: %{"uid" => "resumed-uid", "message" => %{"content" => "Answer"}}
       }}
    )

    on_exit(fn ->
      Application.put_env(:langboard_socket, :graph_timeout_ms, timeout)

      for key <- [
            :resume_worker_test_pid,
            :resume_worker_test_claim,
            :resume_worker_test_graph,
            :resume_worker_test_complete,
            :resume_worker_test_renew
          ] do
        Application.delete_env(:langboard_socket, key)
      end
    end)

    :ok
  end

  test "emits only the persisted result after backend acknowledgement" do
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:graph_started, _pid, "thread-uid", "session-uid", %{"rejected" => true}}
    assert_receive {:completed, "project-uid", "run-uid", 2, "thread-uid", "session-uid", result}
    assert result.response_text == "Answer"

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :buffer,
                    %{uid: "original-uid"}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :end,
                    %{status: :success}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :start,
                    %{ai_message: %{"uid" => "resumed-uid"}}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :buffer,
                    %{uid: "resumed-uid"}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :end,
                    %{uid: "resumed-uid", status: :success}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :finished, %{}}
    assert_worker_stopped(worker, monitor)
  end

  test "emits a persisted follow-up interrupt from the new AI message" do
    interrupt = %{"value" => %{"type" => "approval_request", "thread_id" => "thread-uid"}}

    Application.put_env(
      :langboard_socket,
      :resume_worker_test_graph,
      {:ok, %{response_text: "Needs approval", interrupt: interrupt}}
    )

    Application.put_env(
      :langboard_socket,
      :resume_worker_test_complete,
      {:ok,
       %{
         original_message: %{"uid" => "original-uid", "message" => %{"content" => "Partial"}},
         resumed_message: %{
           "uid" => "resumed-uid",
           "message" => %{"content" => "Needs approval", "graph_interrupt" => interrupt}
         }
       }}
    )

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:completed, "project-uid", "run-uid", 2, _thread, _session,
                    %{interrupt: ^interrupt}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :buffer,
                    %{uid: "original-uid"}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :end,
                    %{status: :success}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :start,
                    %{ai_message: %{"uid" => "resumed-uid"}}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :buffer,
                    %{uid: "resumed-uid", message: %{"graph_interrupt" => ^interrupt}}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :end,
                    %{uid: "resumed-uid", status: :success}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :finished, %{}}
    assert_worker_stopped(worker, monitor)
  end

  test "does not invent a new AI message when the backend returns none" do
    Application.put_env(
      :langboard_socket,
      :resume_worker_test_complete,
      {:ok,
       %{
         original_message: %{"uid" => "original-uid", "message" => %{"content" => "Partial"}},
         resumed_message: nil
       }}
    )

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :buffer,
                    %{uid: "original-uid"}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :end,
                    %{uid: "original-uid"}}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :finished, %{}}
    assert_worker_stopped(worker, monitor)
    refute_receive {:board_chat_resume_event, "project-uid", "original-uid", :start, _event}
  end

  test "a rejected claim never starts Graph" do
    Application.put_env(:langboard_socket, :resume_worker_test_claim, {:error, :conflict})
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :claim_failed,
                    %{reason: :conflict}}

    assert_worker_stopped(worker, monitor)
    refute_receive {:graph_started, _pid, _thread, _session, _decision}
  end

  test "Graph failure does not acknowledge success" do
    Application.put_env(:langboard_socket, :resume_worker_test_graph, {:error, :unavailable})
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :result_unknown,
                    %{reason: :unavailable}}

    assert_worker_stopped(worker, monitor)
    refute_receive {:completed, _project, _run, _attempt, _thread, _session, _result}
  end

  test "Graph crash does not acknowledge success" do
    Application.put_env(:langboard_socket, :resume_worker_test_graph, :crash)
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :result_unknown,
                    %{reason: :graph_crash}}

    assert_worker_stopped(worker, monitor)
    refute_receive {:completed, _project, _run, _attempt, _thread, _session, _result}
  end

  test "failed persistence never emits a successful result" do
    Application.put_env(:langboard_socket, :resume_worker_test_complete, {:error, :unavailable})
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:completed, "project-uid", "run-uid", 2, _thread, _session, _result}

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :result_unknown,
                    %{reason: :unavailable}}

    assert_worker_stopped(worker, monitor)

    refute_receive {:board_chat_resume_event, "project-uid", "original-uid", :end,
                    %{status: :success}}
  end

  test "renews the lease while Graph is running" do
    Application.put_env(:langboard_socket, :graph_timeout_ms, 4_000)
    Application.put_env(:langboard_socket, :resume_worker_test_graph, :wait)
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:graph_started, graph_pid, _thread, _session, _decision}
    assert_receive {:renewed, "project-uid", "run-uid", 2}, 1_500
    send(graph_pid, :release)
    assert_receive {:completed, "project-uid", "run-uid", 2, _thread, _session, _result}
    assert_worker_stopped(worker, monitor)
  end

  test "lost lease stops Graph without persisting the result" do
    Application.put_env(:langboard_socket, :graph_timeout_ms, 4_000)
    Application.put_env(:langboard_socket, :resume_worker_test_graph, :wait)
    Application.put_env(:langboard_socket, :resume_worker_test_renew, {:error, :conflict})
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:graph_started, graph_pid, _thread, _session, _decision}
    graph_monitor = Process.monitor(graph_pid)
    assert_receive {:renewed, "project-uid", "run-uid", 2}, 1_500
    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :lease_lost, %{}}
    assert_worker_stopped(worker, monitor)
    assert_receive {:DOWN, ^graph_monitor, :process, ^graph_pid, _reason}
    refute_receive {:completed, _project, _run, _attempt, _thread, _session, _result}
  end

  test "permanent lease authorization failure stops Graph without persisting the result" do
    Application.put_env(:langboard_socket, :graph_timeout_ms, 4_000)
    Application.put_env(:langboard_socket, :resume_worker_test_graph, :wait)
    Application.put_env(:langboard_socket, :resume_worker_test_renew, {:error, :forbidden})

    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:graph_started, graph_pid, _thread, _session, _decision}
    graph_monitor = Process.monitor(graph_pid)
    assert_receive {:renewed, "project-uid", "run-uid", 2}, 1_500

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :result_unknown,
                    %{reason: :forbidden}}

    assert_worker_stopped(worker, monitor)
    assert_receive {:DOWN, ^graph_monitor, :process, ^graph_pid, _reason}
    refute_receive {:completed, _project, _run, _attempt, _thread, _session, _result}
  end

  test "reports unknown outcome without starting Graph when task capacity is exhausted" do
    supervisor = start_supervised!({Task.Supervisor, max_children: 0})
    worker = start_worker(graph_supervisor: supervisor)
    monitor = Process.monitor(worker)

    assert_receive {:board_chat_resume_event, "project-uid", "original-uid", :result_unknown,
                    %{reason: :capacity}}

    assert_worker_stopped(worker, monitor)
    refute_receive {:graph_started, _, _, _, _}
    refute_receive {:completed, _, _, _, _, _, _}
  end

  defp start_worker(options \\ []) do
    worker_options =
      Keyword.merge(
        [
          token: "user-token",
          project_uid: "project-uid",
          command: %{"message_uid" => "original-uid"},
          receiver: self(),
          run_client: RunClient,
          graph_client: GraphClient
        ],
        options
      )

    {:ok, worker} =
      DynamicSupervisor.start_child(
        LangboardSocket.BoardChatRunSupervisor,
        {BoardChatResumeWorker, worker_options}
      )

    worker
  end

  defp assert_worker_stopped(worker, monitor) do
    assert_receive {:DOWN, ^monitor, :process, ^worker, reason}
    assert reason in [:normal, :noproc]
  end
end
