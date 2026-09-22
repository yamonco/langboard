defmodule LangboardSocket.EditorResumeWorkerTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.EditorResumeWorker

  defmodule RunClient do
    def claim_resume(_token, _project_uid, _approval_uid, _decision) do
      Application.fetch_env!(:langboard_socket, :editor_resume_test_claim)
    end

    def complete_resume(run_uid, attempt, thread_id, session_id, result) do
      send(Application.fetch_env!(:langboard_socket, :editor_resume_test_pid), {
        :result_posted,
        run_uid,
        attempt,
        thread_id,
        session_id,
        result
      })

      Application.fetch_env!(:langboard_socket, :editor_resume_test_result)
    end

    def renew_resume_lease(run_uid, attempt) do
      send(Application.fetch_env!(:langboard_socket, :editor_resume_test_pid), {
        :lease_renewed,
        run_uid,
        attempt
      })

      Application.get_env(:langboard_socket, :editor_resume_test_lease, :ok)
    end

    def finish(run_uid, attempt, status, output_text, error_message) do
      send(Application.fetch_env!(:langboard_socket, :editor_resume_test_pid), {
        :run_finished,
        run_uid,
        attempt,
        status,
        output_text,
        error_message
      })

      Application.get_env(:langboard_socket, :editor_resume_test_finish, :ok)
    end
  end

  defmodule GraphClient do
    def resume(thread_id, session_id, decision) do
      send(Application.fetch_env!(:langboard_socket, :editor_resume_test_pid), {
        :graph_started,
        self(),
        thread_id,
        session_id,
        decision
      })

      case Application.fetch_env!(:langboard_socket, :editor_resume_test_graph) do
        :wait -> receive do: (:release -> {:ok, %{response_text: "Done", interrupt: nil}})
        result -> result
      end
    end
  end

  setup do
    Application.put_env(:langboard_socket, :editor_resume_test_pid, self())

    Application.put_env(
      :langboard_socket,
      :editor_resume_test_claim,
      {:ok,
       %{
         run_uid: "run-uid",
         attempt: 2,
         thread_id: "thread-uid",
         session_id: "session-uid",
         resume: %{"approved" => true, "rejected" => false, "app_api_token" => "token"}
       }}
    )

    Application.put_env(
      :langboard_socket,
      :editor_resume_test_graph,
      {:ok, %{response_text: "Done", interrupt: nil}}
    )

    Application.put_env(
      :langboard_socket,
      :editor_resume_test_result,
      {:ok, %{status: "completed", newly_applied: true, output_text: "Done"}}
    )

    on_exit(fn ->
      for key <- [
            :editor_resume_test_pid,
            :editor_resume_test_claim,
            :editor_resume_test_graph,
            :editor_resume_test_result,
            :editor_resume_test_lease,
            :editor_resume_test_finish
          ] do
        Application.delete_env(:langboard_socket, key)
      end
    end)

    :ok
  end

  test "publishes only the result acknowledged by the API" do
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:graph_started, _pid, "thread-uid", "session-uid",
                    %{"app_api_token" => "token"}}

    assert_receive {:result_posted, "run-uid", 2, "thread-uid", "session-uid",
                    %{response_text: "Done"}}

    assert_receive {:editor_resume_event, "approval-uid", :completed,
                    %{status: "completed", output_text: "Done"}}

    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
  end

  test "a rejected claim never starts Graph" do
    Application.put_env(:langboard_socket, :editor_resume_test_claim, {:error, :conflict})
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:editor_resume_event, "approval-uid", :claim_failed, :conflict}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:graph_started, _, _, _, _}
  end

  test "does not publish success after a Graph or persistence failure" do
    Application.put_env(:langboard_socket, :editor_resume_test_graph, {:error, :unavailable})
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:editor_resume_event, "approval-uid", :result_unknown, :unavailable}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:result_posted, _, _, _, _, _}

    Application.put_env(
      :langboard_socket,
      :editor_resume_test_graph,
      {:ok, %{response_text: "Done", interrupt: nil}}
    )

    Application.put_env(:langboard_socket, :editor_resume_test_result, {:error, :unavailable})
    worker = start_worker()
    monitor = Process.monitor(worker)

    assert_receive {:result_posted, "run-uid", 2, _, _, _}
    assert_receive {:editor_resume_event, "approval-uid", :result_unknown, :unavailable}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:editor_resume_event, "approval-uid", :completed, _}
  end

  test "renews the claimed attempt while Graph is running" do
    Application.put_env(:langboard_socket, :editor_resume_test_graph, :wait)
    worker = start_worker()
    monitor = Process.monitor(worker)
    assert_receive {:graph_started, graph_pid, _, _, _}
    send(worker, :renew_lease)
    assert_receive {:lease_renewed, "run-uid", 2}
    send(graph_pid, :release)
    assert_receive {:editor_resume_event, "approval-uid", :completed, _}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
  end

  test "fails a resumed run when its editor scope is revoked" do
    Application.put_env(:langboard_socket, :editor_resume_test_graph, :wait)
    Application.put_env(:langboard_socket, :editor_resume_test_lease, {:error, :forbidden})
    worker = start_worker()
    monitor = Process.monitor(worker)
    assert_receive {:graph_started, _graph_pid, _, _, _}

    send(worker, :renew_lease)

    assert_receive {:lease_renewed, "run-uid", 2}

    assert_receive {:run_finished, "run-uid", 2, "failed", "",
                    "Editor AI scope access was revoked"}

    assert_receive {:editor_resume_event, "approval-uid", :result_unknown, :forbidden}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:result_posted, _, _, _, _, _}
  end

  test "reports unknown outcome without starting Graph when task capacity is exhausted" do
    supervisor = start_supervised!({Task.Supervisor, max_children: 0})
    worker = start_worker(graph_supervisor: supervisor)
    monitor = Process.monitor(worker)

    assert_receive {:editor_resume_event, "approval-uid", :result_unknown, :capacity}
    assert_receive {:DOWN, ^monitor, :process, ^worker, _reason}
    refute_receive {:graph_started, _, _, _, _}
    refute_receive {:result_posted, _, _, _, _, _}
  end

  defp start_worker(options \\ []) do
    {:ok, pid} =
      EditorResumeWorker.start_link(
        Keyword.merge(
          [
            token: "approver-token",
            project_uid: "project-uid",
            approval_uid: "approval-uid",
            decision: %{"approved" => true, "rejected" => false},
            receiver: self(),
            run_client: RunClient,
            graph_client: GraphClient
          ],
          options
        )
      )

    pid
  end
end
