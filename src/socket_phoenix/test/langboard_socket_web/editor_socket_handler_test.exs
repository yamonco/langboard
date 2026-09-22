defmodule LangboardSocketWeb.EditorSocketHandlerTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocketWeb.SocketHandler

  @task_id "123e4567-e89b-42d3-a456-426614174000"
  @project_uid "123456789ab"
  @card_uid "123456789ac"

  defmodule Worker do
    def child_spec(options) do
      %{id: __MODULE__, start: {__MODULE__, :start_link, [options]}, restart: :temporary}
    end

    def start_link(options) do
      Task.start_link(fn ->
        send(Application.fetch_env!(:langboard_socket, :editor_handler_test_pid), {
          :editor_worker_started,
          self(),
          options
        })

        loop()
      end)
    end

    defp loop do
      receive do
        {:editor_abort_requested, task_id} ->
          send(
            Application.fetch_env!(:langboard_socket, :editor_handler_test_pid),
            {:abort, task_id}
          )

          loop()

        :finish ->
          :ok
      end
    end
  end

  defmodule CancelClient do
    def cancel(token, project_uid, kind, task_id) do
      send(Application.fetch_env!(:langboard_socket, :editor_handler_test_pid), {
        :cancel_requested,
        token,
        project_uid,
        kind,
        task_id
      })

      {:ok, "run-uid"}
    end

    def status(token, project_uid, kind, task_id) do
      send(Application.fetch_env!(:langboard_socket, :editor_handler_test_pid), {
        :status_requested,
        token,
        project_uid,
        kind,
        task_id
      })

      {:ok,
       %{
         "run_uid" => "run-uid",
         "task_id" => task_id,
         "kind" => kind,
         "status" => "completed",
         "attempt" => 1,
         "output_text" => "Recovered",
         "error_message" => nil
       }}
    end
  end

  setup do
    previous_flag = Application.get_env(:langboard_socket, :editor_ai_enabled)
    previous_worker = Application.get_env(:langboard_socket, :editor_run_worker)
    previous_resume_worker = Application.get_env(:langboard_socket, :editor_resume_worker)
    previous_client = Application.get_env(:langboard_socket, :editor_run_client)
    Application.put_env(:langboard_socket, :editor_ai_enabled, false)
    Application.put_env(:langboard_socket, :editor_run_worker, Worker)
    Application.put_env(:langboard_socket, :editor_resume_worker, Worker)
    Application.put_env(:langboard_socket, :editor_run_client, CancelClient)
    Application.put_env(:langboard_socket, :editor_handler_test_pid, self())

    on_exit(fn ->
      restore_env(:editor_ai_enabled, previous_flag)
      restore_env(:editor_run_worker, previous_worker)
      restore_env(:editor_resume_worker, previous_resume_worker)
      restore_env(:editor_run_client, previous_client)
      Application.delete_env(:langboard_socket, :editor_handler_test_pid)
    end)

    :ok
  end

  test "editor commands remain disabled unless explicitly selected" do
    state = connected_state()
    assert {:ok, ^state} = SocketHandler.handle_in({chat_request(), opcode: :text}, state)
    assert {:ok, ^state} = SocketHandler.handle_in({resume_request(), opcode: :text}, state)
    refute_receive {:editor_worker_started, _, _}
  end

  test "editor approval resume is admitted only with a bounded decision and returns persisted outcome" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()
    request = resume_request()

    assert {:ok, pending} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:editor_worker_started, worker_pid, options}
    assert options[:token] == "access-token"
    assert options[:project_uid] == @project_uid
    assert options[:approval_uid] == @card_uid
    assert options[:decision] == %{"approved" => true, "rejected" => false}
    assert {:ok, ^pending} = SocketHandler.handle_in({request, opcode: :text}, pending)
    refute_receive {:editor_worker_started, _, _}

    assert {:push, {:text, frame}, completed} =
             SocketHandler.handle_info(
               {:editor_resume_event, @card_uid, :completed,
                %{status: "completed", output_text: "Done"}},
               pending
             )

    assert Jason.decode!(frame) == %{
             "event" => Contract.event!("editor_approval_resume_result"),
             "topic" => Contract.topic!("none"),
             "topic_id" => Contract.topic_id!("none"),
             "data" => %{
               "approval_uid" => @card_uid,
               "status" => "completed",
               "output_text" => "Done"
             }
           }

    stop_worker(worker_pid)

    assert {:ok, _state} =
             SocketHandler.handle_info(
               {:DOWN, completed.pending_editor_resumes[@card_uid].monitor, :process, worker_pid,
                :normal},
               completed
             )
  end

  test "editor approval resume rejects malformed decisions before admission" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()
    request = Jason.decode!(resume_request())
    invalid_data_code = Contract.close_code!("invalid_data")

    for invalid <- [
          put_in(request, ["data", "resume"], %{"approved" => true, "rejected" => true}),
          put_in(request, ["data", "resume"], %{"instruction" => "Run this"}),
          put_in(request, ["data", "resume"], %{
            "approved" => true,
            "rejected" => false,
            "app_api_token" => "forged"
          }),
          put_in(request, ["data", "approval_uid"], "bad"),
          put_in(request, ["topic"], Contract.topic!("board"))
        ] do
      assert {:stop, :normal, ^invalid_data_code, ^state} =
               SocketHandler.handle_in({Jason.encode!(invalid), opcode: :text}, state)
    end

    refute_receive {:editor_worker_started, _, _}
  end

  test "card chat validates scope, strips unrelated fields, and emits the legacy stream" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()
    request = chat_request()
    assert {:ok, pending} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:editor_worker_started, worker_pid, options}
    assert options[:token] == "access-token"

    assert options[:command] == %{
             "task_id" => @task_id,
             "project_uid" => @project_uid,
             "scope_uid" => @card_uid,
             "document_name" => "card:#{@card_uid}:description",
             "kind" => "editor_chat",
             "system" => "Instructions",
             "messages" => [%{"role" => "user", "content" => "Draft"}]
           }

    assert {:ok, ^pending} = SocketHandler.handle_in({request, opcode: :text}, pending)
    refute_receive {:editor_worker_started, _, _}

    assert {:push, {:text, start_frame}, started} =
             SocketHandler.handle_info({:editor_run_event, @task_id, :start, %{}}, pending)

    assert Jason.decode!(start_frame) == %{
             "event" => Contract.event!("editor_card_chat_stream") <> ":start",
             "topic" => Contract.topic!("none"),
             "topic_id" => Contract.topic_id!("none"),
             "data" => %{}
           }

    assert {:push, {:text, buffer_frame}, buffered} =
             SocketHandler.handle_info(
               {:editor_run_event, @task_id, :buffer, %{message: "Draft"}},
               started
             )

    assert Jason.decode!(buffer_frame)["data"] == %{"message" => "Draft"}

    assert {:push, {:text, end_frame}, ended} =
             SocketHandler.handle_info(
               {:editor_run_event, @task_id, :end, %{status: "completed", message: "Draft"}},
               buffered
             )

    assert Jason.decode!(end_frame)["event"] ==
             Contract.event!("editor_card_chat_stream") <> ":end"

    assert Jason.decode!(end_frame)["data"] == %{"message" => "Draft"}

    assert {:ok, ^ended} =
             SocketHandler.handle_info({:editor_run_event, @task_id, :failed, %{}}, ended)

    stop_worker(worker_pid)
  end

  test "a persisted editor approval ends chat without reporting a failed run" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)

    assert {:ok, pending} =
             SocketHandler.handle_in({chat_request(), opcode: :text}, connected_state())

    assert_receive {:editor_worker_started, worker_pid, _options}

    assert {:push, {:text, frame}, ended} =
             SocketHandler.handle_info(
               {:editor_run_event, @task_id, :end,
                %{status: "awaiting_approval", message: "Partial"}},
               pending
             )

    assert Jason.decode!(frame) == %{
             "event" => Contract.event!("editor_card_chat_stream") <> ":end",
             "topic" => Contract.topic!("none"),
             "topic_id" => Contract.topic_id!("none"),
             "data" => %{"status" => "awaiting_approval", "message" => "Partial"}
           }

    assert {:ok, ^ended} =
             SocketHandler.handle_info({:editor_run_event, @task_id, :failed, %{}}, ended)

    stop_worker(worker_pid)
  end

  test "wiki copilot uses the keyed receive event and a failed result is zero" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()
    wiki_uid = "123456789ad"

    request =
      Jason.encode!(%{
        event: Contract.event!("editor_wiki_copilot_send"),
        topic: Contract.topic!("none"),
        topic_id: Contract.topic_id!("none"),
        data: %{
          task_id: @task_id,
          project_uid: @project_uid,
          wiki_uid: wiki_uid,
          document_name: "wiki:#{wiki_uid}:content",
          system: "Instructions",
          prompt: "Continue"
        }
      })

    assert {:ok, pending} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:editor_worker_started, worker_pid, options}
    assert options[:command]["kind"] == "editor_copilot"
    assert options[:command]["scope_uid"] == wiki_uid

    assert {:ok, ^pending} =
             SocketHandler.handle_info({:editor_run_event, @task_id, :start, %{}}, pending)

    assert {:ok, ^pending} =
             SocketHandler.handle_info(
               {:editor_run_event, @task_id, :buffer, %{message: "Partial"}},
               pending
             )

    for {text, expected} <- [{"Completed", "Completed"}, {"", "0"}] do
      assert {:push, {:text, frame}, ended} =
               SocketHandler.handle_info(
                 {:editor_run_event, @task_id, :end, %{status: "completed", message: text}},
                 pending
               )

      assert Jason.decode!(frame)["data"] == %{"text" => expected}

      assert Jason.decode!(frame)["event"] ==
               Contract.event!("editor_wiki_copilot_receive") <> ":" <> @task_id

      assert {:ok, ^ended} =
               SocketHandler.handle_info({:editor_run_event, @task_id, :failed, %{}}, ended)
    end

    assert {:push, {:text, response}, _ended} =
             SocketHandler.handle_info(
               {:editor_run_event, @task_id, :failed, %{reason: :unavailable}},
               pending
             )

    assert Jason.decode!(response) == %{
             "event" => Contract.event!("editor_wiki_copilot_receive") <> ":" <> @task_id,
             "topic" => Contract.topic!("none"),
             "topic_id" => Contract.topic_id!("none"),
             "data" => %{"text" => "0"}
           }

    stop_worker(worker_pid)
  end

  test "editor status requests return the durable run result" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()

    request =
      Jason.encode!(%{
        event: Contract.event!("editor_ai_status"),
        topic: Contract.topic!("none"),
        topic_id: Contract.topic_id!("none"),
        data: %{task_id: @task_id, project_uid: @project_uid, kind: "editor_chat"}
      })

    assert {:ok, pending} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:status_requested, "access-token", @project_uid, "editor_chat", @task_id}
    [{worker_pid, monitor_ref}] = Map.values(pending.pending_editor_statuses)

    assert {:push, {:text, frame}, completed} =
             SocketHandler.handle_info(
               {:editor_status, @task_id, worker_pid,
                {:ok,
                 %{
                   "run_uid" => "run-uid",
                   "task_id" => @task_id,
                   "kind" => "editor_chat",
                   "status" => "completed",
                   "attempt" => 1,
                   "output_text" => "Recovered",
                   "error_message" => nil
                 }}},
               pending
             )

    assert Jason.decode!(frame) == %{
             "event" => Contract.event!("editor_ai_status_result"),
             "topic" => Contract.topic!("none"),
             "topic_id" => Contract.topic_id!("none"),
             "data" => %{
               "run_uid" => "run-uid",
               "task_id" => @task_id,
               "kind" => "editor_chat",
               "status" => "completed",
               "attempt" => 1,
               "output_text" => "Recovered",
               "error_message" => nil
             }
           }

    assert completed.pending_editor_statuses == %{}
    refute Process.alive?(worker_pid)
    refute Map.has_key?(completed.pending_editor_statuses, @task_id)
    refute_received {:DOWN, ^monitor_ref, :process, ^worker_pid, _reason}
  end

  test "wrong topic, foreign document, and malformed input close before worker admission" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()
    request = Jason.decode!(chat_request())
    invalid_data_code = Contract.close_code!("invalid_data")

    for invalid <- [
          put_in(request, ["topic"], "board"),
          put_in(request, ["data", "document_name"], "card:123456789zz:description"),
          put_in(request, ["data", "document_name"], "wiki:#{@card_uid}:description"),
          put_in(request, ["data", "document_name"], nil),
          put_in(request, ["data", "document_name"], 42),
          put_in(request, ["data", "document_name"], ""),
          put_in(
            request,
            ["data", "document_name"],
            "card:#{@card_uid}:" <> String.duplicate("a", 513)
          ),
          put_in(request, ["data", "messages"], [%{"role" => "tool", "content" => "No"}]),
          put_in(request, ["data", "task_id"], "short"),
          put_in(request, ["data", "file_path"], "/tmp/private")
        ] do
      assert {:stop, :normal, ^invalid_data_code, ^state} =
               SocketHandler.handle_in({Jason.encode!(invalid), opcode: :text}, state)
    end

    refute_receive {:editor_worker_started, _, _}
  end

  test "abort is sent to the matching worker and rejects a different project" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()
    assert {:ok, pending} = SocketHandler.handle_in({chat_request(), opcode: :text}, state)
    assert_receive {:editor_worker_started, worker_pid, _options}

    abort_request =
      Jason.encode!(%{
        event: Contract.event!("editor_card_chat_abort"),
        topic: Contract.topic!("none"),
        topic_id: Contract.topic_id!("none"),
        data: %{task_id: @task_id, project_uid: @project_uid}
      })

    assert {:ok, ^pending} = SocketHandler.handle_in({abort_request, opcode: :text}, pending)
    assert_receive {:abort, @task_id}
    foreign = put_in(Jason.decode!(abort_request), ["data", "project_uid"], "123456789zz")
    invalid_data_code = Contract.close_code!("invalid_data")

    assert {:stop, :normal, ^invalid_data_code, ^pending} =
             SocketHandler.handle_in({Jason.encode!(foreign), opcode: :text}, pending)

    stop_worker(worker_pid)
  end

  test "abort of a missing run refuses admission at the command limit" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    previous_limit = Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands)
    Application.put_env(:langboard_socket, :socket_max_in_flight_commands, 1)
    on_exit(fn -> restore_env(:socket_max_in_flight_commands, previous_limit) end)
    state = connected_state()
    full = %{state | pending_editor_cancels: %{make_ref() => {self(), make_ref()}}}
    close_code = Contract.close_code!("try_again_later")

    assert {:stop, :normal, ^close_code, ^full} =
             SocketHandler.handle_in({abort_request(), opcode: :text}, full)

    refute_receive {:cancel_requested, _, _, _, _}
  end

  test "abort of a missing run tracks the API request until it finishes" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()

    assert {:ok, pending} = SocketHandler.handle_in({abort_request(), opcode: :text}, state)
    assert_receive {:cancel_requested, "access-token", @project_uid, "editor_chat", @task_id}

    assert_receive {:editor_cancel, reference, worker_pid, @task_id, {:ok, "run-uid"}} = message

    assert Map.has_key?(pending.pending_editor_cancels, reference)

    assert {:push, {:text, frame}, completed} = SocketHandler.handle_info(message, pending)
    assert Jason.decode!(frame)["event"] == Contract.event!("editor_ai_status_result")
    assert Jason.decode!(frame)["data"]["task_id"] == @task_id
    assert Jason.decode!(frame)["data"]["status"] == "cancelled"
    refute Map.has_key?(completed.pending_editor_cancels, reference)
    refute Process.alive?(worker_pid)
    assert {:ok, ^completed} = SocketHandler.handle_info(message, completed)
  end

  test "legacy UI editor commands may omit the none topic identity" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()
    request = chat_request() |> Jason.decode!() |> Map.delete("topic_id") |> Jason.encode!()

    assert {:ok, pending} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:editor_worker_started, worker_pid, _options}
    assert Map.has_key?(pending.pending_editor_runs, @task_id)
    stop_worker(worker_pid)
  end

  test "an explicit invalid none topic identity is not normalized" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()

    request =
      chat_request() |> Jason.decode!() |> Map.put("topic_id", "foreign") |> Jason.encode!()

    close_code = Contract.close_code!("invalid_data")

    assert {:stop, :normal, ^close_code, ^state} =
             SocketHandler.handle_in({request, opcode: :text}, state)

    refute_receive {:editor_worker_started, _, _}
  end

  test "cancel failure reports lookup failure rather than a cancelled run" do
    state = connected_state()
    reference = make_ref()
    monitor = Process.monitor(self())
    pending = %{state | pending_editor_cancels: %{reference => {self(), monitor}}}
    result = {:error, :unavailable}

    assert {:ok, ^pending} =
             SocketHandler.handle_info(
               {:editor_cancel, reference, spawn(fn -> :ok end), @task_id, result},
               pending
             )

    assert {:push, {:text, frame}, completed} =
             SocketHandler.handle_info(
               {:editor_cancel, reference, self(), @task_id, result},
               pending
             )

    assert Jason.decode!(frame)["data"] == %{
             "task_id" => @task_id,
             "status" => "error",
             "error_code" => "unavailable"
           }

    assert completed.pending_editor_cancels == %{}
  end

  test "worker exit without a terminal result sends a failed chat stream" do
    Application.put_env(:langboard_socket, :editor_ai_enabled, true)
    state = connected_state()
    assert {:ok, pending} = SocketHandler.handle_in({chat_request(), opcode: :text}, state)
    assert_receive {:editor_worker_started, worker_pid, _options}
    send(worker_pid, :finish)
    assert_receive {:DOWN, reference, :process, ^worker_pid, :normal}

    assert {:push, {:text, failed_frame}, _state} =
             SocketHandler.handle_info({:DOWN, reference, :process, worker_pid, :normal}, pending)

    assert Jason.decode!(failed_frame)["data"]["status"] == "failed"
  end

  defp connected_state do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 2048, 30_000, 32})

    state
  end

  defp chat_request do
    Jason.encode!(%{
      event: Contract.event!("editor_card_chat_send"),
      topic: Contract.topic!("none"),
      topic_id: Contract.topic_id!("none"),
      data: %{
        task_id: @task_id,
        project_uid: @project_uid,
        card_uid: @card_uid,
        document_name: "card:#{@card_uid}:description",
        system: "Instructions",
        messages: [%{role: "user", content: "Draft", ignored: "value"}],
        ignored: "value"
      }
    })
  end

  defp abort_request do
    Jason.encode!(%{
      event: Contract.event!("editor_card_chat_abort"),
      topic: Contract.topic!("none"),
      topic_id: Contract.topic_id!("none"),
      data: %{task_id: @task_id, project_uid: @project_uid}
    })
  end

  defp resume_request do
    Jason.encode!(%{
      event: Contract.event!("editor_approval_resume"),
      topic: Contract.topic!("none"),
      topic_id: Contract.topic_id!("none"),
      data: %{
        project_uid: @project_uid,
        approval_uid: @card_uid,
        resume: %{approved: true, rejected: false}
      }
    })
  end

  defp stop_worker(pid) do
    send(pid, :finish)
    assert_receive {:DOWN, _reference, :process, ^pid, :normal}
  end

  defp restore_env(key, nil), do: Application.delete_env(:langboard_socket, key)
  defp restore_env(key, value), do: Application.put_env(:langboard_socket, key, value)
end
