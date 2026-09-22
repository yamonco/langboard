defmodule LangboardSocket.EditorRunWorkerTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.EditorRunWorker

  @task_id "0750a86b-6cd7-492c-b846-6104e3c4c7c9"

  defmodule RunClient do
    def accept(_token, command) do
      send(Application.fetch_env!(:langboard_socket, :editor_worker_test_pid), {:accept, command})

      if Application.get_env(:langboard_socket, :editor_worker_hold_accept, false) do
        receive do
          :release_accept -> :ok
        end
      end

      {:ok, %{"run_uid" => "run-uid", "status" => "accepted", "accepted" => true}}
    end

    def start(run_uid) do
      send(Application.fetch_env!(:langboard_socket, :editor_worker_test_pid), {:start, run_uid})

      {:ok,
       %{
         attempt: 1,
         graph_request: %{"session_id" => "session", "thread_id" => "thread"}
       }}
    end

    def finish(run_uid, attempt, status, output_text, error_message) do
      send(Application.fetch_env!(:langboard_socket, :editor_worker_test_pid), {
        :finish,
        run_uid,
        attempt,
        status,
        output_text,
        error_message
      })

      :ok
    end

    def pause(run_uid, attempt, output_text, interrupt) do
      send(Application.fetch_env!(:langboard_socket, :editor_worker_test_pid), {
        :pause,
        run_uid,
        attempt,
        output_text,
        interrupt
      })

      Application.get_env(:langboard_socket, :editor_worker_pause_result, {:ok, interrupt})
    end

    def renew_lease(_run_uid, _attempt) do
      Application.get_env(:langboard_socket, :editor_worker_lease_result, :ok)
    end

    def cancel(_token, project_uid, kind, task_id) do
      send(Application.fetch_env!(:langboard_socket, :editor_worker_test_pid), {
        :cancel,
        project_uid,
        kind,
        task_id
      })

      {:ok, "run-uid"}
    end
  end

  defmodule GraphClient do
    def stream(session_id, request, callback) do
      send(Application.fetch_env!(:langboard_socket, :editor_worker_test_pid), {
        :graph_started,
        session_id,
        request
      })

      if Application.get_env(:langboard_socket, :editor_worker_hold_graph, false) do
        receive do
          :release_graph -> :ok
        end
      end

      for event <- Application.fetch_env!(:langboard_socket, :editor_worker_graph_events) do
        :ok = callback.(event)
      end

      :ok = callback.(:end)
      :ok
    end
  end

  setup do
    previous = Application.get_env(:langboard_socket, :editor_worker_test_pid)
    previous_events = Application.get_env(:langboard_socket, :editor_worker_graph_events)
    previous_hold = Application.get_env(:langboard_socket, :editor_worker_hold_accept)
    previous_graph_hold = Application.get_env(:langboard_socket, :editor_worker_hold_graph)
    previous_lease_result = Application.get_env(:langboard_socket, :editor_worker_lease_result)
    previous_pause_result = Application.get_env(:langboard_socket, :editor_worker_pause_result)
    previous_max = Application.fetch_env!(:langboard_socket, :graph_stream_max_chunk_bytes)
    Application.put_env(:langboard_socket, :editor_worker_test_pid, self())
    Application.put_env(:langboard_socket, :editor_worker_graph_events, [])
    Application.put_env(:langboard_socket, :editor_worker_hold_accept, false)
    Application.put_env(:langboard_socket, :editor_worker_hold_graph, false)
    Application.put_env(:langboard_socket, :editor_worker_lease_result, :ok)
    Application.delete_env(:langboard_socket, :editor_worker_pause_result)

    on_exit(fn ->
      restore_env(:editor_worker_test_pid, previous)
      restore_env(:editor_worker_graph_events, previous_events)
      restore_env(:editor_worker_hold_accept, previous_hold)
      restore_env(:editor_worker_hold_graph, previous_graph_hold)
      restore_env(:editor_worker_lease_result, previous_lease_result)
      restore_env(:editor_worker_pause_result, previous_pause_result)
      Application.put_env(:langboard_socket, :graph_stream_max_chunk_bytes, previous_max)
    end)

    :ok
  end

  test "chat streams only new text and persists the final answer" do
    Application.put_env(:langboard_socket, :editor_worker_graph_events, [
      {:token, "Hello"},
      {:token, "Hello world"}
    ])

    pid = start_worker("editor_chat")
    assert_receive {:accept, %{"kind" => "editor_chat"}}
    assert_receive {:start, "run-uid"}
    assert_receive {:editor_run_event, @task_id, :start, %{}}
    assert_receive {:graph_started, "session", %{"thread_id" => "thread"}}
    assert_receive {:editor_run_event, @task_id, :buffer, %{message: "Hello"}}
    assert_receive {:editor_run_event, @task_id, :buffer, %{message: " world"}}
    assert_receive {:finish, "run-uid", 1, "completed", "Hello world", nil}

    assert_receive {:editor_run_event, @task_id, :end,
                    %{status: "completed", message: "Hello world"}}

    assert_down(pid)
  end

  test "copilot returns its final text without chat buffer events" do
    Application.put_env(:langboard_socket, :editor_worker_graph_events, [
      {:token, "Next"},
      {:token, " sentence"}
    ])

    pid = start_worker("editor_copilot")
    assert_receive {:finish, "run-uid", 1, "completed", "Next sentence", nil}

    assert_receive {:editor_run_event, @task_id, :end,
                    %{status: "completed", message: "Next sentence"}}

    refute_receive {:editor_run_event, @task_id, :buffer, _}
    assert_down(pid)
  end

  test "abort queued during acceptance cancels before Graph claim" do
    Application.put_env(:langboard_socket, :editor_worker_hold_accept, true)
    pid = start_worker("editor_chat")
    assert_receive {:accept, _command}
    send(pid, {:editor_abort_requested, @task_id})
    send(pid, :release_accept)
    assert_receive {:cancel, "project-uid", "editor_chat", @task_id}
    assert_receive {:editor_run_event, @task_id, :cancelled, %{}}
    refute_receive {:start, "run-uid"}
    assert_down(pid)
  end

  test "oversized output fails the run before delivering content" do
    Application.put_env(:langboard_socket, :graph_stream_max_chunk_bytes, 5)
    Application.put_env(:langboard_socket, :editor_worker_graph_events, [{:token, "Too long"}])
    pid = start_worker("editor_chat")

    assert_receive {:finish, "run-uid", 1, "failed", "",
                    "Editor AI output exceeded the configured limit"}

    assert_receive {:editor_run_event, @task_id, :end, %{status: "failed"}}
    refute_receive {:editor_run_event, @task_id, :buffer, _}
    assert_down(pid)
  end

  test "approval interrupts pause the durable editor run before reporting the result" do
    Application.put_env(:langboard_socket, :editor_worker_graph_events, [
      {:interrupt, %{"type" => "approval_request"}}
    ])

    pid = start_worker("editor_chat")
    assert_receive {:pause, "run-uid", 1, "", %{"type" => "approval_request"}}

    assert_receive {:editor_run_event, @task_id, :end,
                    %{status: "awaiting_approval", message: ""}}

    refute_receive {:finish, _, _, _, _, _}
    assert_down(pid)
  end

  test "a rejected pause cannot announce an editor approval" do
    Application.put_env(:langboard_socket, :editor_worker_graph_events, [
      {:interrupt, %{"type" => "approval_request"}}
    ])

    Application.put_env(:langboard_socket, :editor_worker_pause_result, {:error, :unavailable})

    pid = start_worker("editor_chat")
    assert_receive {:pause, "run-uid", 1, "", _interrupt}

    assert_receive {:finish, "run-uid", 1, "failed", "",
                    "Graph interruption could not be persisted"}

    assert_receive {:editor_run_event, @task_id, :end, %{status: "failed"}}
    assert_down(pid)
  end

  test "multiple editor interrupts cannot produce an ambiguous approval" do
    Application.put_env(:langboard_socket, :editor_worker_graph_events, [
      {:interrupt, %{"id" => "first"}},
      {:interrupt, %{"id" => "second"}}
    ])

    pid = start_worker("editor_chat")
    assert_receive {:finish, "run-uid", 1, "failed", "", "Graph streaming failed"}
    refute_receive {:pause, _, _, _, _}
    assert_down(pid)
  end

  test "an accepted run finishes after its browser receiver disconnects" do
    Application.put_env(:langboard_socket, :editor_worker_graph_events, [{:token, "Persisted"}])
    receiver = spawn(fn -> :ok end)
    reference = Process.monitor(receiver)
    assert_receive {:DOWN, ^reference, :process, ^receiver, reason}
    assert reason in [:normal, :noproc]

    pid = start_worker("editor_chat", receiver)
    assert_receive {:finish, "run-uid", 1, "completed", "Persisted", nil}
    assert_down(pid)
  end

  test "events and results from another task cannot mutate the active run" do
    Application.put_env(:langboard_socket, :editor_worker_hold_graph, true)

    Application.put_env(:langboard_socket, :editor_worker_graph_events, [
      {:token, "Actual answer"}
    ])

    pid = start_worker("editor_chat")
    assert_receive {:graph_started, "session", _request}
    before = :sys.get_state(pid)

    for event <- [{:token, "Stale answer"}, {:interrupt, %{}}, {:error, :stale}, :end] do
      send(pid, {:graph_event, self(), event})
    end

    send(pid, {:graph_result, self(), :ok})
    assert :sys.get_state(pid) == before
    refute_receive {:finish, _, _, _, _, _}
    refute_receive {:pause, _, _, _, _}
    refute_receive {:editor_run_event, @task_id, :buffer, _}

    send(before.graph_task.pid, :release_graph)
    assert_receive {:editor_run_event, @task_id, :buffer, %{message: "Actual answer"}}
    assert_receive {:finish, "run-uid", 1, "completed", "Actual answer", nil}
    assert_down(pid)
  end

  test "scope revocation stops the Graph task and fails the durable run" do
    Application.put_env(:langboard_socket, :editor_worker_hold_graph, true)
    Application.put_env(:langboard_socket, :editor_worker_lease_result, {:error, :forbidden})
    pid = start_worker("editor_chat")
    assert_receive {:graph_started, "session", _request}
    send(pid, :renew_lease)

    assert_receive {:finish, "run-uid", 1, "failed", "", "Editor AI scope access was revoked"}
    assert_receive {:editor_run_event, @task_id, :end, %{status: "failed"}}
    assert_down(pid)
  end

  test "abort during Graph streaming cancels the durable run and stops the Graph task" do
    Application.put_env(:langboard_socket, :editor_worker_hold_graph, true)
    pid = start_worker("editor_chat")
    assert_receive {:graph_started, "session", _request}
    send(pid, {:editor_abort_requested, @task_id})

    assert_receive {:cancel, "project-uid", "editor_chat", @task_id}
    assert_receive {:editor_run_event, @task_id, :cancelled, %{}}
    refute_receive {:finish, _, _, _, _, _}
    assert_down(pid)
  end

  test "Graph capacity exhaustion persists failure without announcing a started stream" do
    supervisor = start_supervised!({Task.Supervisor, max_children: 0})

    {:ok, pid} =
      EditorRunWorker.start_link(
        token: "access-token",
        receiver: self(),
        command: %{"task_id" => @task_id, "kind" => "editor_chat"},
        run_client: RunClient,
        graph_client: GraphClient,
        graph_supervisor: supervisor
      )

    assert_receive {:finish, "run-uid", 1, "failed", "", "Graph worker capacity is unavailable"}
    assert_receive {:editor_run_event, @task_id, :end, %{status: "failed"}}
    refute_receive {:editor_run_event, @task_id, :start, _data}
    refute_receive {:graph_started, _, _}
    assert_down(pid)
  end

  test "recovered acceptance starts the saved run without a browser token or receiver" do
    {:ok, pid} =
      EditorRunWorker.start_link(
        token: nil,
        receiver: nil,
        command: %{"task_id" => @task_id, "kind" => "editor_chat"},
        recovery_run: %{"run_uid" => "run-uid"},
        run_client: RunClient,
        graph_client: GraphClient
      )

    assert_receive {:start, "run-uid"}
    assert_receive {:finish, "run-uid", 1, "completed", "", nil}
    refute_receive {:accept, _command}
    assert_down(pid)
  end

  defp start_worker(kind, receiver \\ nil) do
    command = %{
      "task_id" => @task_id,
      "project_uid" => "project-uid",
      "kind" => kind
    }

    {:ok, pid} =
      EditorRunWorker.start_link(
        token: "access-token",
        command: command,
        receiver: receiver || self(),
        run_client: RunClient,
        graph_client: GraphClient
      )

    pid
  end

  defp assert_down(pid) do
    reference = Process.monitor(pid)
    assert_receive {:DOWN, ^reference, :process, ^pid, reason}
    assert reason in [:normal, :noproc]
  end

  defp restore_env(key, nil), do: Application.delete_env(:langboard_socket, key)
  defp restore_env(key, value), do: Application.put_env(:langboard_socket, key, value)
end
