defmodule LangboardSocketWeb.SocketHandlerTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.BoardChatRunWorker
  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocketWeb.SocketHandler

  @send_task_id "123e4567-e89b-42d3-a456-426614174000"

  test "command DOWN requires matching worker and monitor and preserves other registries" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "test-user"}, "token", 1024, 30_000, 100})

    monitor = make_ref()
    cancel_key = make_ref()
    other_monitor = make_ref()

    pending = %{
      state
      | pending_editor_cancels: %{cancel_key => {self(), monitor}},
        pending_bot_status: %{"board" => {self(), other_monitor}},
        pending_chat_availability: %{"board" => {self(), other_monitor}},
        pending_notifications: %{make_ref() => {self(), other_monitor}},
        pending_ollama: %{make_ref() => {self(), other_monitor}}
    }

    assert {:ok, ^pending} =
             SocketHandler.handle_info({:DOWN, make_ref(), :process, self(), :killed}, pending)

    other_worker = spawn(fn -> :ok end)

    assert {:ok, ^pending} =
             SocketHandler.handle_info({:DOWN, monitor, :process, other_worker, :killed}, pending)

    assert {:ok, cleared} =
             SocketHandler.handle_info({:DOWN, monitor, :process, self(), :killed}, pending)

    assert cleared == %{pending | pending_editor_cancels: %{}}

    assert {:ok, ^cleared} =
             SocketHandler.handle_info({:DOWN, monitor, :process, self(), :killed}, cleared)
  end

  test "drain sends the service restart close code" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "test-user"}, "token", 1024, 30_000, 100})

    assert {:stop, :normal, 1012, ^state} = SocketHandler.handle_info(:socket_drain, state)
    assert :ok = SocketHandler.terminate(:normal, state)
  end

  test "drain rejects a socket that already passed the upgrade check" do
    on_exit(fn -> LangboardSocket.RuntimeStatus.reset() end)
    :ok = LangboardSocket.RuntimeStatus.begin_drain()

    assert {:stop, :normal, 1012, state} =
             SocketHandler.init({{:ok, "test-user"}, "token", 1024, 30_000, 100})

    assert :ok = SocketHandler.terminate(:normal, state)
  end

  defmodule SendWorker do
    def child_spec(options) do
      %{id: __MODULE__, start: {__MODULE__, :start_link, [options]}, restart: :temporary}
    end

    def start_link(options) do
      Task.start_link(fn ->
        send(Application.fetch_env!(:langboard_socket, :send_handler_test_pid), {
          :send_worker_started,
          self(),
          options
        })

        receive do
          :finish -> :ok
        end
      end)
    end
  end

  defmodule CancelClient do
    def cancel(token, project_uid, task_id) do
      send(Application.fetch_env!(:langboard_socket, :cancel_handler_test_pid), {
        :cancel_requested,
        token,
        project_uid,
        task_id
      })

      case Application.fetch_env!(:langboard_socket, :cancel_handler_test_result) do
        :wait ->
          receive do
            :release -> {:ok, "run-uid"}
          end

        result ->
          result
      end
    end
  end

  defmodule ResumeWorker do
    def child_spec(options) do
      %{id: __MODULE__, start: {__MODULE__, :start_link, [options]}, restart: :temporary}
    end

    def start_link(options) do
      Task.start_link(fn ->
        send(Application.fetch_env!(:langboard_socket, :resume_handler_test_pid), {
          :resume_worker_started,
          self(),
          options
        })

        receive do
          :finish -> :ok
        end
      end)
    end
  end

  setup do
    previous_send_flag = Application.get_env(:langboard_socket, :board_chat_send_enabled)
    previous_send_worker = Application.get_env(:langboard_socket, :board_chat_run_worker)
    previous_cancel_client = Application.get_env(:langboard_socket, :board_chat_run_client)
    previous_resume_flag = Application.get_env(:langboard_socket, :board_chat_resume_enabled)
    previous_resume_worker = Application.get_env(:langboard_socket, :board_chat_resume_worker)
    Application.put_env(:langboard_socket, :board_chat_send_enabled, false)
    Application.put_env(:langboard_socket, :board_chat_run_worker, SendWorker)
    Application.put_env(:langboard_socket, :send_handler_test_pid, self())
    Application.put_env(:langboard_socket, :board_chat_run_client, CancelClient)
    Application.put_env(:langboard_socket, :cancel_handler_test_pid, self())
    Application.put_env(:langboard_socket, :cancel_handler_test_result, {:ok, "run-uid"})
    Application.put_env(:langboard_socket, :board_chat_resume_enabled, false)
    Application.put_env(:langboard_socket, :board_chat_resume_worker, ResumeWorker)
    Application.put_env(:langboard_socket, :resume_handler_test_pid, self())
    Application.put_env(:langboard_socket, :notification_test_owner, self())
    Application.put_env(:langboard_socket, :chat_availability_test_owner, self())
    Application.put_env(:langboard_socket, :ollama_test_owner, self())

    on_exit(fn ->
      restore_env(:board_chat_send_enabled, previous_send_flag)
      restore_env(:board_chat_run_worker, previous_send_worker)
      Application.delete_env(:langboard_socket, :send_handler_test_pid)
      restore_env(:board_chat_run_client, previous_cancel_client)
      Application.delete_env(:langboard_socket, :cancel_handler_test_pid)
      Application.delete_env(:langboard_socket, :cancel_handler_test_result)
      restore_env(:board_chat_resume_enabled, previous_resume_flag)
      restore_env(:board_chat_resume_worker, previous_resume_worker)
      Application.delete_env(:langboard_socket, :resume_handler_test_pid)
      Application.delete_env(:langboard_socket, :notification_test_owner)
      Application.delete_env(:langboard_socket, :chat_availability_test_owner)
      Application.delete_env(:langboard_socket, :ollama_test_owner)
    end)

    :ok
  end

  test "authenticated clients receive the existing automatic subscription acknowledgements" do
    assert {:push, messages, state} =
             SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    decoded = Enum.map(messages, fn {:text, payload} -> Jason.decode!(payload) end)

    assert %{
             "event" => Contract.event!("subscribed"),
             "topic" => Contract.topic!("global"),
             "topic_id" => [Contract.topic_id!("global")]
           } in decoded

    assert %{
             "event" => Contract.event!("subscribed"),
             "topic" => Contract.topic!("user_private"),
             "topic_id" => ["user-uid"]
           } in decoded

    assert MapSet.size(state.subscriptions) == 2
    refute inspect(state) =~ "access-token"
  end

  test "outbound telemetry includes bootstrap and direct protocol frames" do
    handler_id = {__MODULE__, self(), make_ref()}

    :ok =
      :telemetry.attach(
        handler_id,
        [:langboard_socket, :websocket, :outbound],
        fn _event, measurements, _metadata, owner ->
          send(owner, {:socket_outbound, measurements})
        end,
        self()
      )

    on_exit(fn -> :telemetry.detach(handler_id) end)

    assert {:push, bootstrap, state} =
             SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    Enum.each(bootstrap, &assert_outbound_telemetry/1)

    subscribe = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: "board-uid"})
    assert {:push, subscribed, state} = SocketHandler.handle_in({subscribe, opcode: :text}, state)
    assert_outbound_telemetry(subscribed)

    unsubscribe =
      Jason.encode!(%{event: "unsubscribe", topic: "board", topic_id: "board-uid"})

    assert {:push, unsubscribed, state} =
             SocketHandler.handle_in({unsubscribe, opcode: :text}, state)

    assert_outbound_telemetry(unsubscribed)

    assert {:push, empty, ^state} = SocketHandler.handle_in({"", opcode: :text}, state)
    assert_outbound_telemetry(empty)

    assert {:push, ping, ^state} = SocketHandler.handle_info(:ping, state)
    assert_outbound_telemetry(ping)
  end

  test "unauthorized clients close with the legacy code" do
    assert {:stop, :normal, 3000, _state} =
             SocketHandler.init({{:error, :unauthorized}, nil, 1024, 30_000, 32})
  end

  test "expired clients close with the refresh code instead of signing out" do
    assert {:stop, :normal, 3001, _state} =
             SocketHandler.init({{:error, :expired_token}, "expired", 1024, 30_000, 32})
  end

  test "heartbeat rechecks authentication without changing subscriptions" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    assert {:push, {:ping, ""}, ^state} = SocketHandler.handle_info(:ping, state)

    for {reason, code} <- [expired_token: 3001, unauthorized: 3000, unavailable: 1011] do
      Process.put(:authentication_result, {:error, reason})
      assert {:stop, :normal, ^code, ^state} = SocketHandler.handle_info(:ping, state)
    end
  end

  test "broker fanout rechecks current access and revokes only the denied subscription" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    payload = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: "board-uid"})
    {:push, _response, state} = SocketHandler.handle_in({payload, opcode: :text}, state)

    event = %{
      "event" => "changed",
      "topic" => "board",
      "topic_id" => "board-uid",
      "data" => %{"secret" => true}
    }

    Process.put(:authorization_result, {:ok, []})

    assert {:push, messages, next_state} =
             SocketHandler.handle_info({:socket_event, event}, state)

    assert Enum.map(messages, fn {:text, payload} -> Jason.decode!(payload) end) == [
             %{
               "event" => "subscription:revoked",
               "topic" => "board",
               "topic_id" => "board-uid",
               "data" => %{}
             },
             %{"event" => "unsubscribed", "topic" => "board", "topic_id" => ["board-uid"]}
           ]

    refute MapSet.member?(next_state.subscriptions, {"board", "board-uid"})
    assert MapSet.member?(next_state.subscriptions, {"user_private", "user-uid"})
    assert {:ok, ^next_state} = SocketHandler.handle_info({:socket_event, event}, next_state)

    Phoenix.PubSub.broadcast(
      LangboardSocket.PubSub,
      LangboardSocket.SubscriptionTopic.name("board", "board-uid"),
      :revoked_probe
    )

    refute_receive :revoked_probe
  end

  test "broker fanout fails closed on invalid or expired credentials and backend failure" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    event = %{"event" => "changed", "topic" => "user_private", "topic_id" => "user-uid"}

    for {reason, code} <- [expired_token: 3001, unauthorized: 3000, unavailable: 1011] do
      Process.put(:authorization_result, {:error, reason})

      assert {:stop, :normal, ^code, ^state} =
               SocketHandler.handle_info({:socket_event, event}, state)
    end
  end

  test "malformed JSON is ignored and empty payloads are echoed" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    assert {:ok, ^state} = SocketHandler.handle_in({"not-json", opcode: :text}, state)
    assert {:push, {:text, ""}, ^state} = SocketHandler.handle_in({"", opcode: :text}, state)
  end

  test "oversized messages close with message-too-big" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 3, 30_000, 32})

    assert {:stop, :normal, 1009, ^state} =
             SocketHandler.handle_in({"four", opcode: :text}, state)
  end

  test "authorized subscriptions are accepted through the API boundary" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    payload = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: "board-uid"})

    assert {:push, {:text, response}, next_state} =
             SocketHandler.handle_in({payload, opcode: :text}, state)

    assert Jason.decode!(response) == %{
             "event" => "subscribed",
             "topic" => "board",
             "topic_id" => ["board-uid"]
           }

    assert MapSet.member?(next_state.subscriptions, {"board", "board-uid"})
  end

  test "denied subscriptions return an empty acknowledgement" do
    Process.put(:authorization_result, {:ok, []})

    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    payload = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: "denied"})

    assert {:push, {:text, response}, ^state} =
             SocketHandler.handle_in({payload, opcode: :text}, state)

    assert Jason.decode!(response)["topic_id"] == []
  end

  test "subscription batches and topic IDs are bounded before authorization" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    oversized_batch =
      Jason.encode!(%{
        event: "subscribe",
        topic: "board",
        topic_id: Enum.map(1..65, &"board-#{&1}")
      })

    assert {:stop, :normal, invalid_data, ^state} =
             SocketHandler.handle_in({oversized_batch, opcode: :text}, state)

    assert invalid_data == Contract.close_code!("invalid_data")

    oversized_id =
      Jason.encode!(%{
        event: "unsubscribe",
        topic: "board",
        topic_id: String.duplicate("x", 129)
      })

    assert {:stop, :normal, ^invalid_data, ^state} =
             SocketHandler.handle_in({oversized_id, opcode: :text}, state)
  end

  test "broker fanout preserves the payload for a current subscription" do
    state = subscribed_board_state("board-uid")

    payload = %{
      "topic" => "board",
      "topic_id" => "board-uid",
      "event" => "changed",
      "data" => %{}
    }

    assert {:push, {:text, response}, ^state} =
             SocketHandler.handle_info({:socket_event, payload}, state)

    assert Jason.decode!(response) == payload
  end

  test "subscription reauthorization removes rejected IDs but preserves other subscriptions" do
    state = subscribed_board_state("revoked-board")
    request = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: "other-board"})
    {:push, _ack, state} = SocketHandler.handle_in({request, opcode: :text}, state)
    Process.put(:authorization_result, {:ok, ["allowed-board"]})

    request =
      Jason.encode!(%{
        event: "subscribe",
        topic: "board",
        topic_id: ["revoked-board", "allowed-board"]
      })

    assert {:push, {:text, response}, next_state} =
             SocketHandler.handle_in({request, opcode: :text}, state)

    assert Jason.decode!(response)["topic_id"] == ["allowed-board"]

    assert MapSet.equal?(
             next_state.subscriptions,
             MapSet.new([
               {"global", "all"},
               {"user_private", "user-uid"},
               {"board", "other-board"},
               {"board", "allowed-board"}
             ])
           )

    payload = %{"topic" => "board", "topic_id" => "revoked-board", "event" => "changed"}
    assert {:ok, ^next_state} = SocketHandler.handle_info({:socket_event, payload}, next_state)

    Phoenix.PubSub.broadcast(
      LangboardSocket.PubSub,
      LangboardSocket.SubscriptionTopic.name("board", "revoked-board"),
      {:socket_event, payload}
    )

    refute_receive {:socket_event, ^payload}
  end

  test "broker fanout ignores unsubscribed topics and malformed routing fields" do
    state = subscribed_board_state("board-uid")

    for payload <- [
          %{"topic" => "board", "topic_id" => "another-board", "event" => "changed"},
          %{"topic" => "board_card", "topic_id" => "board-uid", "event" => "changed"},
          %{"topic" => "board", "topic_id" => ["board-uid"], "event" => "changed"},
          %{"event" => "changed"}
        ] do
      assert {:ok, ^state} = SocketHandler.handle_info({:socket_event, payload}, state)
    end
  end

  test "queued broker fanout is ignored after unsubscribe and resumes after rejoin" do
    state = subscribed_board_state("board-uid")

    payload = %{
      "topic" => "board",
      "topic_id" => "board-uid",
      "event" => "changed",
      "data" => %{}
    }

    unsubscribe = Jason.encode!(%{event: "unsubscribe", topic: "board", topic_id: "board-uid"})

    assert {:push, {:text, _ack}, unsubscribed} =
             SocketHandler.handle_in({unsubscribe, opcode: :text}, state)

    assert {:ok, ^unsubscribed} =
             SocketHandler.handle_info({:socket_event, payload}, unsubscribed)

    subscribe = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: "board-uid"})

    assert {:push, {:text, _ack}, rejoined} =
             SocketHandler.handle_in({subscribe, opcode: :text}, unsubscribed)

    assert {:push, {:text, response}, ^rejoined} =
             SocketHandler.handle_info({:socket_event, payload}, rejoined)

    assert Jason.decode!(response) == payload
  end

  test "automatic private and global subscriptions still receive broker fanout" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    for {topic, topic_id} <- state.subscriptions do
      payload = %{"topic" => topic, "topic_id" => topic_id, "event" => "changed", "data" => %{}}

      assert {:push, {:text, response}, ^state} =
               SocketHandler.handle_info({:socket_event, payload}, state)

      assert Jason.decode!(response) == payload
    end
  end

  test "revoked authentication closes the connection with the legacy code" do
    Process.put(:authorization_result, {:error, :unauthorized})

    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    payload = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: "board-uid"})

    assert {:stop, :normal, 3000, ^state} =
             SocketHandler.handle_in({payload, opcode: :text}, state)
  end

  test "authorization backend failure closes with internal error" do
    Process.put(:authorization_result, {:error, :unavailable})

    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    payload = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: "board-uid"})

    assert {:stop, :normal, 1011, ^state} =
             SocketHandler.handle_in({payload, opcode: :text}, state)
  end

  test "a subscribed board receives its authorized bot status map" do
    state = subscribed_board_state("board-uid")
    request = bot_status_request("board-uid")

    assert {:ok, pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:bot_status_map, "board-uid", worker_pid, {:ok, _status_map}} = message, 1_000

    assert {:push, {:text, response}, completed_state} =
             SocketHandler.handle_info(message, pending_state)

    assert Jason.decode!(response) == %{
             "event" => Contract.event!("board_bot_status_map"),
             "topic" => Contract.topic!("board"),
             "topic_id" => "board-uid",
             "data" => %{
               "bot_status_map" => %{
                 "project_column" => %{"column-uid" => ["bot-uid"]},
                 "card" => %{}
               }
             }
           }

    refute Map.has_key?(completed_state.pending_bot_status, "board-uid")
    refute Process.alive?(worker_pid)
  end

  test "bot status commands reject missing subscriptions and revoke stale authorization" do
    {:push, _messages, unsubscribed_state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    assert {:stop, :normal, 3003, ^unsubscribed_state} =
             SocketHandler.handle_in(
               {bot_status_request("board-uid"), opcode: :text},
               unsubscribed_state
             )

    subscribed_state = subscribed_board_state("board-uid")
    Process.put(:authorization_result, {:ok, []})

    SocketHandler.handle_in(
      {bot_status_request("board-uid"), opcode: :text},
      subscribed_state
    )
    |> assert_board_subscription_revoked("board-uid")
  end

  test "duplicate in-flight requests share a single bounded worker" do
    topic_id = "hold:board-uid"
    state = subscribed_board_state(topic_id)
    request = bot_status_request(topic_id)

    assert {:ok, pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)

    assert {:ok, ^pending_state} =
             SocketHandler.handle_in({request, opcode: :text}, pending_state)

    assert map_size(pending_state.pending_bot_status) == 1

    {worker_pid, _monitor_ref} = Map.fetch!(pending_state.pending_bot_status, topic_id)
    send(worker_pid, :release)
    assert_receive {:bot_status_map, ^topic_id, ^worker_pid, {:ok, _status_map}} = message
    assert {:push, {:text, _response}, _state} = SocketHandler.handle_info(message, pending_state)
  end

  test "unsubscribing cancels a pending lookup and ignores its late result" do
    topic_id = "hold:board-uid"
    state = subscribed_board_state(topic_id)

    assert {:ok, pending_state} =
             SocketHandler.handle_in({bot_status_request(topic_id), opcode: :text}, state)

    {worker_pid, _monitor_ref} = Map.fetch!(pending_state.pending_bot_status, topic_id)
    unsubscribe = Jason.encode!(%{event: "unsubscribe", topic: "board", topic_id: topic_id})

    assert {:push, {:text, _response}, unsubscribed_state} =
             SocketHandler.handle_in({unsubscribe, opcode: :text}, pending_state)

    refute Map.has_key?(unsubscribed_state.pending_bot_status, topic_id)
    refute Process.alive?(worker_pid)

    stale_result = {:bot_status_map, topic_id, worker_pid, {:ok, %{}}}

    assert {:ok, ^unsubscribed_state} =
             SocketHandler.handle_info(stale_result, unsubscribed_state)
  end

  test "a failed lookup returns the legacy null result" do
    topic_id = "fail:board-uid"
    state = subscribed_board_state(topic_id)

    assert {:ok, pending_state} =
             SocketHandler.handle_in({bot_status_request(topic_id), opcode: :text}, state)

    assert_receive {:bot_status_map, ^topic_id, _worker_pid, {:error, :unavailable}} = message
    assert {:push, {:text, response}, _state} = SocketHandler.handle_info(message, pending_state)
    assert get_in(Jason.decode!(response), ["data", "bot_status_map"]) == nil
  end

  test "revoked access during a lookup cannot receive the result" do
    topic_id = "hold:board-uid"
    state = subscribed_board_state(topic_id)

    assert {:ok, pending_state} =
             SocketHandler.handle_in({bot_status_request(topic_id), opcode: :text}, state)

    {worker_pid, _monitor_ref} = Map.fetch!(pending_state.pending_bot_status, topic_id)
    Process.put(:authorization_result, {:ok, []})
    send(worker_pid, :release)

    assert_receive {:bot_status_map, ^topic_id, ^worker_pid, {:ok, _status_map}} = message

    SocketHandler.handle_info(message, pending_state)
    |> assert_board_subscription_revoked(topic_id)
  end

  test "the command supervisor rejects work beyond its configured limit" do
    limit = Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands)

    {:push, _messages, initial_state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    full_state =
      Enum.reduce(1..limit, initial_state, fn index, state ->
        topic_id = "hold:#{index}"
        subscribe = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: topic_id})

        {:push, {:text, _response}, subscribed_state} =
          SocketHandler.handle_in({subscribe, opcode: :text}, state)

        {:ok, pending_state} =
          SocketHandler.handle_in(
            {bot_status_request(topic_id), opcode: :text},
            subscribed_state
          )

        pending_state
      end)

    assert map_size(full_state.pending_bot_status) == limit

    overflow_id = "hold:overflow"
    subscribe = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: overflow_id})

    {:push, {:text, _response}, subscribed_state} =
      SocketHandler.handle_in({subscribe, opcode: :text}, full_state)

    assert {:stop, :normal, 1013, ^subscribed_state} =
             SocketHandler.handle_in(
               {bot_status_request(overflow_id), opcode: :text},
               subscribed_state
             )

    assert :ok = SocketHandler.terminate(:normal, subscribed_state)

    Enum.each(subscribed_state.pending_bot_status, fn {_topic_id, {worker_pid, _monitor_ref}} ->
      refute Process.alive?(worker_pid)
    end)
  end

  test "the in-flight limit also bounds notification and Ollama commands" do
    limit = Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands)

    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    full_state = %{
      state
      | pending_bot_status:
          Map.new(1..limit, fn index -> {"occupied:#{index}", {self(), make_ref()}} end)
    }

    notification = notification_request("notification_delete", "aBc12345678")

    assert {:stop, :normal, 1013, ^full_state} =
             SocketHandler.handle_in({notification, opcode: :text}, full_state)

    refute_receive {:notification_request, _, _, _, _}

    subscribed = subscribed_ollama_state()

    full_ollama_state = %{
      subscribed
      | pending_ollama: Map.new(1..limit, fn _index -> {make_ref(), {self(), make_ref()}} end)
    }

    assert {:stop, :normal, 1013, ^full_ollama_state} =
             SocketHandler.handle_in(
               {ollama_request("ollama_delete_model", %{"model" => "source"}), opcode: :text},
               full_ollama_state
             )

    refute_receive {:ollama_request, _, _, _, _}
  end

  test "a crashed lookup releases the pending slot" do
    topic_id = "crash:board-uid"
    state = subscribed_board_state(topic_id)

    assert {:ok, pending_state} =
             SocketHandler.handle_in({bot_status_request(topic_id), opcode: :text}, state)

    assert_receive {:DOWN, _monitor_ref, :process, _worker_pid, _reason} = message

    assert {:push, {:text, response}, completed_state} =
             SocketHandler.handle_info(message, pending_state)

    assert get_in(Jason.decode!(response), ["data", "bot_status_map"]) == nil
    refute Map.has_key?(completed_state.pending_bot_status, topic_id)
  end

  test "an authorized board receives the existing chat availability frame" do
    state = subscribed_board_state("board-uid")

    assert {:ok, pending_state} =
             SocketHandler.handle_in(
               {chat_availability_request("board-uid"), opcode: :text},
               state
             )

    assert_receive {:chat_availability_request, worker_pid, "access-token", "board-uid"}
    assert_receive {:chat_availability, "board-uid", ^worker_pid, {:ok, data}} = message

    assert {:push, {:text, response}, completed_state} =
             SocketHandler.handle_info(message, pending_state)

    assert Jason.decode!(response) == %{
             "event" => Contract.event!("board_chat_available"),
             "topic" => "board",
             "topic_id" => "board-uid",
             "data" => data
           }

    assert data["available"] == true
    assert data["bot"]["display_name"] == "Project Assistant"
    assert completed_state.pending_chat_availability == %{}
  end

  test "a board without a configured bot receives unavailable with null bot" do
    state = subscribed_board_state("missing:board-uid")

    assert {:ok, pending_state} =
             SocketHandler.handle_in(
               {chat_availability_request("missing:board-uid"), opcode: :text},
               state
             )

    assert_receive {:chat_availability, "missing:board-uid", _worker_pid, {:ok, _data}} =
                     message

    assert {:push, {:text, response}, _state} =
             SocketHandler.handle_info(message, pending_state)

    assert Jason.decode!(response)["data"] == %{"available" => false, "bot" => nil}
  end

  test "chat availability rejects missing subscriptions and revokes stale authorization" do
    {:push, _messages, unsubscribed_state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    assert {:stop, :normal, 3003, ^unsubscribed_state} =
             SocketHandler.handle_in(
               {chat_availability_request("board-uid"), opcode: :text},
               unsubscribed_state
             )

    subscribed_state = subscribed_board_state("board-uid")
    Process.put(:authorization_result, {:ok, []})

    SocketHandler.handle_in(
      {chat_availability_request("board-uid"), opcode: :text},
      subscribed_state
    )
    |> assert_board_subscription_revoked("board-uid")
  end

  test "duplicate availability requests share one worker and unsubscribe cancels it" do
    topic_id = "hold:board-uid"
    state = subscribed_board_state(topic_id)
    request = chat_availability_request(topic_id)

    assert {:ok, pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:chat_availability_request, worker_pid, "access-token", ^topic_id}

    assert {:ok, ^pending_state} =
             SocketHandler.handle_in({request, opcode: :text}, pending_state)

    assert map_size(pending_state.pending_chat_availability) == 1

    unsubscribe = Jason.encode!(%{event: "unsubscribe", topic: "board", topic_id: topic_id})

    assert {:push, {:text, _response}, unsubscribed_state} =
             SocketHandler.handle_in({unsubscribe, opcode: :text}, pending_state)

    refute Process.alive?(worker_pid)
    assert unsubscribed_state.pending_chat_availability == %{}

    stale =
      {:chat_availability, topic_id, worker_pid, {:ok, %{"available" => true, "bot" => %{}}}}

    assert {:ok, ^unsubscribed_state} = SocketHandler.handle_info(stale, unsubscribed_state)
  end

  test "revoked access before availability completion cannot receive a result" do
    topic_id = "hold:board-uid"
    state = subscribed_board_state(topic_id)

    assert {:ok, pending_state} =
             SocketHandler.handle_in({chat_availability_request(topic_id), opcode: :text}, state)

    assert_receive {:chat_availability_request, worker_pid, "access-token", ^topic_id}
    Process.put(:authorization_result, {:ok, []})
    send(worker_pid, :release)
    assert_receive {:chat_availability, ^topic_id, ^worker_pid, {:ok, _data}} = message

    SocketHandler.handle_info(message, pending_state)
    |> assert_board_subscription_revoked(topic_id)
  end

  test "availability backend failure and worker crash close without a false success frame" do
    for topic_id <- ["fail:board-uid", "crash:board-uid"] do
      state = subscribed_board_state(topic_id)

      assert {:ok, pending_state} =
               SocketHandler.handle_in(
                 {chat_availability_request(topic_id), opcode: :text},
                 state
               )

      message =
        receive do
          {:chat_availability, ^topic_id, _worker_pid, {:error, :unavailable}} = result ->
            result

          {:DOWN, _monitor_ref, :process, _worker_pid, _reason} = result ->
            result
        end

      assert {:stop, :normal, 1011, completed_state} =
               SocketHandler.handle_info(message, pending_state)

      assert completed_state.pending_chat_availability == %{}
    end
  end

  test "disconnect cancels an outstanding availability lookup" do
    topic_id = "hold:board-uid"
    state = subscribed_board_state(topic_id)

    assert {:ok, pending_state} =
             SocketHandler.handle_in({chat_availability_request(topic_id), opcode: :text}, state)

    assert_receive {:chat_availability_request, worker_pid, "access-token", ^topic_id}
    assert :ok = SocketHandler.terminate(:normal, pending_state)
    refute Process.alive?(worker_pid)
  end

  test "chat send remains disabled by default" do
    state = subscribed_board_state("board-uid")

    assert {:ok, ^state} =
             SocketHandler.handle_in({chat_send_request("board-uid"), opcode: :text}, state)

    refute_receive {:send_worker_started, _worker_pid, _options}
  end

  test "all editor commands are ignored while the editor feature is disabled" do
    previous = Application.get_env(:langboard_socket, :editor_ai_enabled)
    Application.put_env(:langboard_socket, :editor_ai_enabled, false)
    on_exit(fn -> restore_env(:editor_ai_enabled, previous) end)

    {:push, _messages, state} =
      SocketHandler.init({{:ok, "test-user"}, "token", 1024, 30_000, 100})

    for event <- [
          "editor_ai_status",
          "editor_approval_resume",
          "editor_card_chat_send",
          "editor_card_copilot_send",
          "editor_wiki_chat_send",
          "editor_wiki_copilot_send",
          "editor_card_chat_abort",
          "editor_card_copilot_abort",
          "editor_wiki_chat_abort",
          "editor_wiki_copilot_abort"
        ] do
      request = Jason.encode!(%{event: Contract.event!(event)})
      assert {:ok, ^state} = SocketHandler.handle_in({request, opcode: :text}, state)
    end
  end

  test "chat send forwards persisted acceptance before its stream and starts once" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    state = subscribed_board_state("board-uid")
    request = chat_send_request("board-uid")

    assert {:ok, pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:send_worker_started, worker_pid, options}
    assert options[:token] == "access-token"
    assert options[:project_uid] == "board-uid"
    assert options[:command]["task_id"] == @send_task_id
    assert options[:command]["api_permission_level"] == "read"
    assert options[:receiver] == self()
    refute inspect(pending_state) =~ "access-token"

    assert {:ok, ^pending_state} =
             SocketHandler.handle_in({request, opcode: :text}, pending_state)

    refute_receive {:send_worker_started, _duplicate_worker, _options}

    accepted =
      {:board_chat_run_event, @send_task_id, :accepted,
       %{
         session: %{"uid" => "session-uid"},
         user_message: %{"uid" => "user-message-uid"}
       }}

    assert {:push, frames, ^pending_state} = SocketHandler.handle_info(accepted, pending_state)
    [session_frame, sent_frame] = Enum.map(frames, fn {:text, frame} -> Jason.decode!(frame) end)
    assert session_frame["event"] == "board:chat:session"
    assert session_frame["data"] == %{"session" => %{"uid" => "session-uid"}}
    assert sent_frame["event"] == "board:chat:sent"
    assert sent_frame["data"] == %{"user_message" => %{"uid" => "user-message-uid"}}

    start =
      {:board_chat_run_event, @send_task_id, :start, %{ai_message: %{"uid" => "ai-message-uid"}}}

    assert {:push, {:text, start_frame}, ^pending_state} =
             SocketHandler.handle_info(start, pending_state)

    assert Jason.decode!(start_frame)["event"] == "board:chat:stream:start"

    finish =
      {:board_chat_run_event, @send_task_id, :end, %{uid: "ai-message-uid", status: :success}}

    assert {:push, {:text, finish_frame}, finished_state} =
             SocketHandler.handle_info(finish, pending_state)

    assert Jason.decode!(finish_frame)["data"]["status"] == "success"
    assert {:ok, ^finished_state} = SocketHandler.handle_info(finish, finished_state)
    assert {:ok, ^finished_state} = SocketHandler.handle_info(start, finished_state)
    assert {:push, ^frames, ^finished_state} = SocketHandler.handle_info(accepted, finished_state)

    Process.put(:authorization_result, {:ok, []})

    assert {:stop, :normal, 3003, ^finished_state} =
             SocketHandler.handle_info(accepted, finished_state)

    Process.delete(:authorization_result)
    send(worker_pid, :finish)
    assert_receive {:DOWN, _reference, :process, ^worker_pid, :normal} = down
    assert {:ok, completed_state} = SocketHandler.handle_info(down, finished_state)
    assert completed_state.pending_chat_sends == %{}
  end

  test "chat send forwards a server-owned attachment token without accepting a file path" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    state = subscribed_board_state("board-uid")
    token = String.duplicate("a", 32)

    request =
      Jason.encode!(%{
        event: Contract.event!("board_chat_send"),
        topic: Contract.topic!("board"),
        topic_id: "board-uid",
        data: %{message: "", task_id: @send_task_id, file_token: token}
      })

    assert {:ok, _pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:send_worker_started, worker_pid, options}
    assert options[:command]["message"] == ""
    assert options[:command]["file_token"] == token

    send(worker_pid, :finish)
  end

  test "a competing run claim asks the client to reconcile instead of treating the send as lost" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    state = subscribed_board_state("board-uid")

    assert {:ok, pending} =
             SocketHandler.handle_in({chat_send_request("board-uid"), opcode: :text}, state)

    assert_receive {:send_worker_started, worker_pid, _options}

    conflict = {:board_chat_run_event, @send_task_id, :start_failed, %{reason: :conflict}}
    assert {:push, {:text, frame}, reconciled} = SocketHandler.handle_info(conflict, pending)
    assert Jason.decode!(frame)["event"] == Contract.event!("board_chat_send_failed")

    assert Jason.decode!(frame)["data"] == %{
             "task_id" => @send_task_id,
             "already_started" => true
           }

    send(worker_pid, :finish)
    assert_receive {:DOWN, _reference, :process, ^worker_pid, :normal} = down
    assert {:ok, completed} = SocketHandler.handle_info(down, reconciled)
    assert completed.pending_chat_sends == %{}
  end

  test "chat send rejects invalid or revoked requests before dispatch" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)

    {:push, _messages, unsubscribed} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    assert {:stop, :normal, 3003, ^unsubscribed} =
             SocketHandler.handle_in(
               {chat_send_request("board-uid"), opcode: :text},
               unsubscribed
             )

    state = subscribed_board_state("board-uid")

    invalid_task =
      Jason.encode!(%{
        event: "board:chat:send",
        topic: "board",
        topic_id: "board-uid",
        data: %{message: "hello", task_id: "invalid"}
      })

    assert {:stop, :normal, 4001, ^state} =
             SocketHandler.handle_in({invalid_task, opcode: :text}, state)

    attached =
      Jason.encode!(%{
        event: "board:chat:send",
        topic: "board",
        topic_id: "board-uid",
        data: %{message: "hello", task_id: @send_task_id, file_path: "private-upload"}
      })

    assert {:stop, :normal, 4001, ^state} =
             SocketHandler.handle_in({attached, opcode: :text}, state)

    Process.put(:authorization_result, {:ok, []})

    assert {:stop, :normal, 3003, ^state} =
             SocketHandler.handle_in({chat_send_request("board-uid"), opcode: :text}, state)

    Process.delete(:authorization_result)
    refute_receive {:send_worker_started, _worker_pid, _options}
  end

  test "chat send rejects invalid content and scope combinations before dispatch" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    state = %{subscribed_board_state("board-uid") | max_payload: 131_072}
    request = Jason.decode!(chat_send_request("board-uid"))
    invalid_code = Contract.close_code!("invalid_data")

    for changes <- [
          %{"message" => nil},
          %{"message" => 1},
          %{"message" => ""},
          %{"message" => String.duplicate("a", 65_537)},
          %{"file_token" => "short"},
          %{"file_token" => 123},
          %{"scope_table" => "project", "scope_uid" => "123456789ab"},
          %{"scope_table" => "card"},
          %{"scope_table" => "project_column", "scope_uid" => "bad"},
          %{"scope_table" => "project_wiki", "scope_uid" => nil},
          %{"scope_table" => "unknown", "scope_uid" => "123456789ab"}
        ] do
      invalid = Map.update!(request, "data", &Map.merge(&1, changes))

      assert {:stop, :normal, ^invalid_code, ^state} =
               SocketHandler.handle_in({Jason.encode!(invalid), opcode: :text}, state)
    end

    refute_receive {:send_worker_started, _, _}
  end

  test "chat send reports a worker loss once and ignores events after unsubscribe" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    state = subscribed_board_state("board-uid")

    assert {:ok, pending_state} =
             SocketHandler.handle_in({chat_send_request("board-uid"), opcode: :text}, state)

    assert_receive {:send_worker_started, worker_pid, _options}

    assert {:ok, ^pending_state} =
             SocketHandler.handle_info(
               {:board_chat_run_event, "another-task", :end, %{uid: "other", status: :success}},
               pending_state
             )

    Process.exit(worker_pid, :kill)
    assert_receive {:DOWN, _reference, :process, ^worker_pid, :killed} = down

    assert {:push, {:text, frame}, completed_state} =
             SocketHandler.handle_info(down, pending_state)

    assert Jason.decode!(frame)["data"] == %{
             "task_id" => @send_task_id,
             "already_started" => false
           }

    assert completed_state.pending_chat_sends == %{}

    assert {:ok, second_pending} =
             SocketHandler.handle_in(
               {chat_send_request("board-uid"), opcode: :text},
               completed_state
             )

    assert_receive {:send_worker_started, second_worker, _options}
    unsubscribe = Jason.encode!(%{event: "unsubscribe", topic: "board", topic_id: "board-uid"})

    assert {:push, {:text, _response}, unsubscribed} =
             SocketHandler.handle_in({unsubscribe, opcode: :text}, second_pending)

    assert {:ok, ^unsubscribed} =
             SocketHandler.handle_info(
               {:board_chat_run_event, @send_task_id, :end, %{uid: "ai", status: :success}},
               unsubscribed
             )

    send(second_worker, :finish)
    assert_receive {:DOWN, _reference, :process, ^second_worker, :normal} = second_down
    assert {:ok, done} = SocketHandler.handle_info(second_down, unsubscribed)
    assert done.pending_chat_sends == %{}
  end

  test "chat cancellation is disabled until send is enabled" do
    state = subscribed_board_state("board-uid")

    assert {:ok, ^state} =
             SocketHandler.handle_in({chat_cancel_request("board-uid"), opcode: :text}, state)

    refute_receive {:cancel_requested, _token, _project_uid, _task_id}
  end

  test "chat cancellation acknowledges only a persisted matching run" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    state = subscribed_board_state("board-uid")

    :ok =
      Phoenix.PubSub.subscribe(LangboardSocket.PubSub, BoardChatRunWorker.cancel_topic("run-uid"))

    request = chat_cancel_request("board-uid")

    assert {:ok, pending} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert {:ok, ^pending} = SocketHandler.handle_in({request, opcode: :text}, pending)
    assert_receive {:cancel_requested, "access-token", "board-uid", @send_task_id}
    refute_receive {:cancel_requested, _token, _project_uid, _task_id}
    assert_receive {:board_chat_run_cancelled, "run-uid"}

    assert_receive {:board_chat_cancel_result, @send_task_id, _worker_pid, {:ok, "run-uid"}} =
                     result

    assert {:push, {:text, frame}, completed} = SocketHandler.handle_info(result, pending)

    assert Jason.decode!(frame) == %{
             "event" => Contract.event!("task_aborted"),
             "topic" => Contract.topic!("global"),
             "topic_id" => Contract.topic_id!("global"),
             "data" => %{"task_id" => @send_task_id}
           }

    assert completed.pending_chat_cancels == %{}
  end

  test "chat cancellation rejects invalid and unauthorized requests before API work" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    state = subscribed_board_state("board-uid")

    invalid =
      Jason.encode!(%{
        event: "board:chat:cancel",
        topic: "board",
        topic_id: "board-uid",
        data: %{task_id: "invalid"}
      })

    assert {:stop, :normal, 4001, ^state} =
             SocketHandler.handle_in({invalid, opcode: :text}, state)

    Process.put(:authorization_result, {:ok, []})

    assert {:stop, :normal, 3003, ^state} =
             SocketHandler.handle_in({chat_cancel_request("board-uid"), opcode: :text}, state)

    Process.delete(:authorization_result)
    refute_receive {:cancel_requested, _token, _project_uid, _task_id}
  end

  test "chat cancellation failure never emits an aborted acknowledgement" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    Application.put_env(:langboard_socket, :cancel_handler_test_result, {:error, :conflict})
    state = subscribed_board_state("board-uid")

    assert {:ok, pending} =
             SocketHandler.handle_in({chat_cancel_request("board-uid"), opcode: :text}, state)

    assert_receive {:board_chat_cancel_result, @send_task_id, _worker_pid, {:error, :conflict}} =
                     result

    assert {:push, {:text, frame}, completed} = SocketHandler.handle_info(result, pending)
    assert Jason.decode!(frame)["event"] == Contract.event!("board_chat_send_failed")
    assert completed.pending_chat_cancels == %{}
  end

  test "an accepted cancellation continues after the socket closes" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    Application.put_env(:langboard_socket, :cancel_handler_test_result, :wait)
    state = subscribed_board_state("board-uid")

    :ok =
      Phoenix.PubSub.subscribe(LangboardSocket.PubSub, BoardChatRunWorker.cancel_topic("run-uid"))

    assert {:ok, pending} =
             SocketHandler.handle_in({chat_cancel_request("board-uid"), opcode: :text}, state)

    assert_receive {:cancel_requested, "access-token", "board-uid", @send_task_id}

    {"board-uid", worker_pid, _monitor_ref} =
      Map.fetch!(pending.pending_chat_cancels, @send_task_id)

    assert :ok = SocketHandler.terminate(:normal, pending)
    assert Process.alive?(worker_pid)
    send(worker_pid, :release)
    assert_receive {:board_chat_run_cancelled, "run-uid"}
  end

  test "a remote cancellation ends an in-flight send without a false send failure" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    state = subscribed_board_state("board-uid")

    assert {:ok, pending} =
             SocketHandler.handle_in({chat_send_request("board-uid"), opcode: :text}, state)

    assert_receive {:send_worker_started, worker_pid, _options}

    cancelled = {:board_chat_run_event, @send_task_id, :cancelled, %{}}
    assert {:push, {:text, frame}, finished} = SocketHandler.handle_info(cancelled, pending)
    assert Jason.decode!(frame)["event"] == Contract.event!("task_aborted")

    send(worker_pid, :finish)
    assert_receive {:DOWN, _reference, :process, ^worker_pid, :normal} = down
    assert {:ok, completed} = SocketHandler.handle_info(down, finished)
    assert completed.pending_chat_sends == %{}
  end

  test "cancel acknowledgement drops later tokens but keeps the accepted user message" do
    Application.put_env(:langboard_socket, :board_chat_send_enabled, true)
    state = subscribed_board_state("board-uid")

    assert {:ok, sending} =
             SocketHandler.handle_in({chat_send_request("board-uid"), opcode: :text}, state)

    assert_receive {:send_worker_started, worker_pid, _options}

    assert {:ok, cancelling} =
             SocketHandler.handle_in({chat_cancel_request("board-uid"), opcode: :text}, sending)

    assert_receive {:board_chat_cancel_result, @send_task_id, _cancel_pid, {:ok, "run-uid"}} =
                     result

    assert {:push, {:text, aborted_frame}, acknowledged} =
             SocketHandler.handle_info(result, cancelling)

    assert Jason.decode!(aborted_frame)["event"] == Contract.event!("task_aborted")

    token =
      {:board_chat_run_event, @send_task_id, :buffer,
       %{uid: "ai-message", message: %{content: "late"}}}

    assert {:ok, ^acknowledged} = SocketHandler.handle_info(token, acknowledged)

    assert {:ok, ^acknowledged} =
             SocketHandler.handle_info(
               {:board_chat_run_event, @send_task_id, :cancelled, %{}},
               acknowledged
             )

    accepted =
      {:board_chat_run_event, @send_task_id, :accepted,
       %{session: %{"uid" => "session-uid"}, user_message: %{"uid" => "user-message-uid"}}}

    assert {:push, frames, ^acknowledged} = SocketHandler.handle_info(accepted, acknowledged)

    assert Enum.map(frames, fn {:text, frame} -> Jason.decode!(frame)["event"] end) == [
             Contract.event!("board_chat_session"),
             Contract.event!("board_chat_sent")
           ]

    send(worker_pid, :finish)
    assert_receive {:DOWN, _reference, :process, ^worker_pid, :normal} = down
    assert {:ok, completed} = SocketHandler.handle_info(down, acknowledged)
    assert completed.pending_chat_sends == %{}
  end

  test "chat resume remains disabled by default" do
    state = subscribed_board_state("board-uid")
    request = chat_resume_request("board-uid")

    assert {:ok, ^state} = SocketHandler.handle_in({request, opcode: :text}, state)
    refute_receive {:resume_worker_started, _worker_pid, _options}
  end

  test "authorized chat resume starts one supervised worker and forwards persisted stream frames" do
    Application.put_env(:langboard_socket, :board_chat_resume_enabled, true)
    state = subscribed_board_state("board-uid")
    request = chat_resume_request("board-uid")

    assert {:ok, pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:resume_worker_started, worker_pid, options}
    assert options[:token] == "access-token"
    assert options[:project_uid] == "board-uid"
    assert options[:command]["message_uid"] == "12345678901"
    assert options[:receiver] == self()
    refute inspect(pending_state) =~ "access-token"

    assert {:ok, ^pending_state} =
             SocketHandler.handle_in({request, opcode: :text}, pending_state)

    refute_receive {:resume_worker_started, _duplicate_pid, _options}

    message =
      {:board_chat_resume_event, "board-uid", "12345678901", :buffer,
       %{uid: "12345678901", message: %{"content" => "Persisted"}}}

    assert {:push, {:text, response}, ^pending_state} =
             SocketHandler.handle_info(message, pending_state)

    assert Jason.decode!(response) == %{
             "event" => "board:chat:stream:buffer",
             "topic" => "board",
             "topic_id" => "board-uid",
             "data" => %{"uid" => "12345678901", "message" => %{"content" => "Persisted"}}
           }

    finished = {:board_chat_resume_event, "board-uid", "12345678901", :finished, %{}}
    assert {:ok, finished_state} = SocketHandler.handle_info(finished, pending_state)

    send(worker_pid, :finish)
    assert_receive {:DOWN, _reference, :process, ^worker_pid, :normal} = down
    assert {:ok, completed_state} = SocketHandler.handle_info(down, finished_state)
    assert completed_state.pending_chat_resumes == %{}
  end

  test "chat resume checks membership, rejects malformed input, and reports claim failures" do
    Application.put_env(:langboard_socket, :board_chat_resume_enabled, true)

    {:push, _messages, unsubscribed} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    assert {:stop, :normal, 3003, ^unsubscribed} =
             SocketHandler.handle_in(
               {chat_resume_request("board-uid"), opcode: :text},
               unsubscribed
             )

    subscribed = subscribed_board_state("board-uid")

    malformed =
      Jason.encode!(%{
        event: "board:chat:resume",
        topic: "board",
        topic_id: "board-uid",
        data: %{}
      })

    assert {:stop, :normal, 4001, ^subscribed} =
             SocketHandler.handle_in({malformed, opcode: :text}, subscribed)

    Process.put(:authorization_result, {:ok, []})

    assert {:stop, :normal, 3003, ^subscribed} =
             SocketHandler.handle_in(
               {chat_resume_request("board-uid"), opcode: :text},
               subscribed
             )

    Process.delete(:authorization_result)

    assert {:ok, pending_state} =
             SocketHandler.handle_in(
               {chat_resume_request("board-uid"), opcode: :text},
               subscribed
             )

    assert_receive {:resume_worker_started, worker_pid, _options}

    claim_failed =
      {:board_chat_resume_event, "board-uid", "12345678901", :claim_failed, %{reason: :conflict}}

    assert {:push, {:text, response}, failed_state} =
             SocketHandler.handle_info(claim_failed, pending_state)

    assert Jason.decode!(response)["data"] == %{
             "uid" => "12345678901",
             "resume_error_code" => 4001
           }

    Process.put(:authorization_result, {:ok, []})

    assert {:stop, :normal, 3003, _state} =
             SocketHandler.handle_info(claim_failed, pending_state)

    send(worker_pid, :finish)
    assert_receive {:DOWN, _reference, :process, ^worker_pid, :normal} = down
    assert {:ok, completed_state} = SocketHandler.handle_info(down, failed_state)
    assert completed_state.pending_chat_resumes == %{}
  end

  test "chat resume does not forward a result after board unsubscribe" do
    Application.put_env(:langboard_socket, :board_chat_resume_enabled, true)
    state = subscribed_board_state("board-uid")

    assert {:ok, pending_state} =
             SocketHandler.handle_in({chat_resume_request("board-uid"), opcode: :text}, state)

    assert_receive {:resume_worker_started, worker_pid, _options}
    unsubscribe = Jason.encode!(%{event: "unsubscribe", topic: "board", topic_id: "board-uid"})

    assert {:push, {:text, _response}, unsubscribed} =
             SocketHandler.handle_in({unsubscribe, opcode: :text}, pending_state)

    assert Process.alive?(worker_pid)

    event =
      {:board_chat_resume_event, "board-uid", "12345678901", :end,
       %{uid: "12345678901", status: :success}}

    assert {:ok, ^unsubscribed} = SocketHandler.handle_info(event, unsubscribed)
    send(worker_pid, :finish)
    assert_receive {:DOWN, _reference, :process, ^worker_pid, :normal} = down
    assert {:ok, completed_state} = SocketHandler.handle_info(down, unsubscribed)
    assert completed_state.pending_chat_resumes == %{}
  end

  test "a crashed resume worker reports an error for its own board only" do
    Application.put_env(:langboard_socket, :board_chat_resume_enabled, true)
    state = subscribed_board_state("board-uid")

    assert {:ok, pending_state} =
             SocketHandler.handle_in({chat_resume_request("board-uid"), opcode: :text}, state)

    assert_receive {:resume_worker_started, worker_pid, _options}

    wrong_board =
      {:board_chat_resume_event, "other-board", "12345678901", :end,
       %{uid: "12345678901", status: :success}}

    assert {:ok, ^pending_state} = SocketHandler.handle_info(wrong_board, pending_state)

    Process.exit(worker_pid, :kill)
    assert_receive {:DOWN, _reference, :process, ^worker_pid, :killed} = down

    assert {:push, {:text, response}, completed_state} =
             SocketHandler.handle_info(down, pending_state)

    assert Jason.decode!(response)["data"] == %{
             "uid" => "12345678901",
             "resume_error_code" => 1011
           }

    assert completed_state.pending_chat_resumes == %{}
  end

  test "notification commands use the current token and leave no response frame" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    request = notification_request("notification_read", "aBc12345678")
    assert {:ok, pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:notification_request, worker_pid, "access-token", :read, "aBc12345678"}
    assert_receive {:notification_command, reference, ^worker_pid, :ok} = message
    assert {:ok, completed_state} = SocketHandler.handle_info(message, pending_state)
    refute Map.has_key?(completed_state.pending_notifications, reference)
    refute inspect(completed_state) =~ "access-token"
  end

  test "notification commands reject forged topics and missing UIDs" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    forged =
      Jason.encode!(%{
        event: Contract.event!("notification_read"),
        topic: "board",
        data: %{uid: "uid"}
      })

    missing_uid = notification_request("notification_read", nil)
    malformed_uid = notification_request("notification_read", "../../etc/passwd")

    forged_topic_id =
      Jason.encode!(%{
        event: Contract.event!("notification_read_all"),
        topic: Contract.topic!("none"),
        topic_id: "other"
      })

    assert {:stop, :normal, 3003, ^state} =
             SocketHandler.handle_in({forged, opcode: :text}, state)

    assert {:stop, :normal, 4001, ^state} =
             SocketHandler.handle_in({missing_uid, opcode: :text}, state)

    assert {:stop, :normal, 4001, ^state} =
             SocketHandler.handle_in({malformed_uid, opcode: :text}, state)

    assert {:stop, :normal, 3003, ^state} =
             SocketHandler.handle_in({forged_topic_id, opcode: :text}, state)
  end

  test "bulk notification commands preserve the existing no-topic-ID envelope" do
    for {event_name, action} <- [
          {"notification_read_all", :read_all},
          {"notification_delete_all", :delete_all}
        ] do
      {:push, _messages, state} =
        SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

      assert {:ok, pending_state} =
               SocketHandler.handle_in(
                 {notification_request(event_name, nil), opcode: :text},
                 state
               )

      assert_receive {:notification_request, worker_pid, "access-token", ^action, nil}
      assert_receive {:notification_command, _reference, ^worker_pid, :ok} = message
      assert {:ok, _completed_state} = SocketHandler.handle_info(message, pending_state)
    end
  end

  test "a failed notification command closes instead of silently accepting it" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    request = notification_request("notification_delete", "fail0000000")
    assert {:ok, pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)

    assert_receive {:notification_command, _reference, _worker_pid, {:error, :unavailable}} =
                     message

    assert {:stop, :normal, 1011, _state} = SocketHandler.handle_info(message, pending_state)
  end

  test "disconnect does not cancel an accepted notification write" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    request = notification_request("notification_delete", "hold0000000")
    assert {:ok, pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:notification_request, worker_pid, "access-token", :delete, "hold0000000"}

    assert :ok = SocketHandler.terminate(:normal, pending_state)
    assert Process.alive?(worker_pid)
    send(worker_pid, :release)
    assert_receive {:notification_command, _reference, ^worker_pid, :ok}
  end

  test "a crashed notification worker closes the socket and releases its slot" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    request = notification_request("notification_delete", "crash000000")
    assert {:ok, pending_state} = SocketHandler.handle_in({request, opcode: :text}, state)
    assert_receive {:DOWN, _monitor_ref, :process, _worker_pid, _reason} = message

    assert {:stop, :normal, 1011, completed_state} =
             SocketHandler.handle_info(message, pending_state)

    assert completed_state.pending_notifications == %{}
  end

  test "Ollama model commands call the authenticated API without a success frame" do
    for {event_name, action, data} <- [
          {"ollama_copy_model", :copy, %{"model" => "source", "copy_to" => "copy"}},
          {"ollama_delete_model", :delete, %{"model" => "source"}},
          {"ollama_pull_model", :pull, %{"model" => "source"}}
        ] do
      state = subscribed_ollama_state()

      assert {:ok, pending_state} =
               SocketHandler.handle_in({ollama_request(event_name, data), opcode: :text}, state)

      assert_receive {:ollama_request, worker_pid, "access-token", ^action, ^data}
      assert_receive {:ollama_command, reference, ^worker_pid, :ok} = message
      assert {:ok, completed_state} = SocketHandler.handle_info(message, pending_state)
      refute Map.has_key?(completed_state.pending_ollama, reference)
    end
  end

  test "Ollama commands reject forged topics, missing subscriptions, and revoked access" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    request = ollama_request("ollama_delete_model", %{"model" => "source"})

    assert {:stop, :normal, 3003, ^state} =
             SocketHandler.handle_in({request, opcode: :text}, state)

    subscribed = subscribed_ollama_state()
    Process.put(:authorization_result, {:ok, []})

    assert {:stop, :normal, 3003, ^subscribed} =
             SocketHandler.handle_in({request, opcode: :text}, subscribed)

    Process.delete(:authorization_result)

    forged =
      Jason.encode!(%{
        event: Contract.event!("ollama_delete_model"),
        topic: "board",
        topic_id: "all",
        data: %{model: "source"}
      })

    assert {:stop, :normal, 3003, ^subscribed} =
             SocketHandler.handle_in({forged, opcode: :text}, subscribed)
  end

  test "Ollama commands reject malformed model data and report API failure" do
    state = subscribed_ollama_state()

    assert {:stop, :normal, 4001, ^state} =
             SocketHandler.handle_in(
               {ollama_request("ollama_copy_model", %{"model" => "source"}), opcode: :text},
               state
             )

    assert {:ok, pending_state} =
             SocketHandler.handle_in(
               {ollama_request("ollama_delete_model", %{"model" => "fail"}), opcode: :text},
               state
             )

    assert_receive {:ollama_command, _reference, _worker_pid, {:error, :unavailable}} = message

    assert {:stop, :normal, 1011, completed_state} =
             SocketHandler.handle_info(message, pending_state)

    assert completed_state.pending_ollama == %{}
  end

  test "board and Ollama commands preserve authorization failure codes before dispatch" do
    board = subscribed_board_state("board-uid")
    ollama = subscribed_ollama_state()

    for {reason, code} <- [
          {:expired_token, Contract.close_code!("expired_token")},
          {:unauthorized, Contract.close_code!("unauthorized")},
          {:unavailable, Contract.close_code!("internal_error")}
        ] do
      Process.put(:authorization_result, {:error, reason})

      assert {:stop, :normal, ^code, ^board} =
               SocketHandler.handle_in(
                 {chat_availability_request("board-uid"), opcode: :text},
                 board
               )

      assert {:stop, :normal, ^code, ^ollama} =
               SocketHandler.handle_in(
                 {ollama_request("ollama_delete_model", %{"model" => "source"}), opcode: :text},
                 ollama
               )
    end

    refute_receive {:chat_availability_request, _, _, _}
    refute_receive {:ollama_request, _, _, _, _}
  end

  test "disconnect does not cancel an already forwarded Ollama mutation" do
    state = subscribed_ollama_state()

    assert {:ok, pending_state} =
             SocketHandler.handle_in(
               {ollama_request("ollama_delete_model", %{"model" => "hold"}), opcode: :text},
               state
             )

    assert_receive {:ollama_request, worker_pid, "access-token", :delete, %{"model" => "hold"}}
    assert :ok = SocketHandler.terminate(:normal, pending_state)
    assert Process.alive?(worker_pid)
    send(worker_pid, :release)
    assert_receive {:ollama_command, _reference, ^worker_pid, :ok}
  end

  test "unknown and malformed command envelopes leave connection state unchanged" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    for data <- [nil, [], 42, %{}, %{"event" => "unknown"}, %{"event" => []}, %{"event" => %{}}] do
      assert {:ok, ^state} =
               SocketHandler.handle_in({Jason.encode!(data), opcode: :text}, state)
    end

    assert {:ok, ^state} = SocketHandler.handle_in({"{invalid", opcode: :text}, state)
  end

  test "ping keeps the legacy heartbeat interval" do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    assert {:push, {:ping, ""}, ^state} = SocketHandler.handle_info(:ping, state)
  end

  test "slow clients close when their outbound mailbox reaches the configured bound" do
    parent = self()

    spawn_link(fn ->
      {:push, _messages, state} =
        SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 1})

      send(self(), :queued_message)
      payload = %{"topic" => "user_private", "topic_id" => "user-uid", "event" => "changed"}

      send(
        parent,
        {:slow_client_result, SocketHandler.handle_info({:socket_event, payload}, state)}
      )
    end)

    assert_receive {:slow_client_result, {:stop, :normal, 1013, %SocketHandler.State{}}}
  end

  defp subscribed_board_state(topic_id) do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    request = Jason.encode!(%{event: "subscribe", topic: "board", topic_id: topic_id})

    {:push, {:text, _response}, subscribed_state} =
      SocketHandler.handle_in({request, opcode: :text}, state)

    subscribed_state
  end

  defp assert_outbound_telemetry({_opcode, payload}) do
    assert_receive {:socket_outbound, %{count: 1, bytes: bytes, queue_length: queue_length}}

    assert bytes == byte_size(payload)
    assert queue_length >= 0
  end

  defp assert_board_subscription_revoked(result, topic_id) do
    assert {:push, messages, state} = result

    assert Enum.map(messages, fn {:text, payload} -> Jason.decode!(payload) end) == [
             %{
               "event" => Contract.event!("subscription_revoked"),
               "topic" => Contract.topic!("board"),
               "topic_id" => topic_id,
               "data" => %{}
             },
             %{
               "event" => Contract.event!("unsubscribed"),
               "topic" => Contract.topic!("board"),
               "topic_id" => [topic_id]
             }
           ]

    refute MapSet.member?(state.subscriptions, {Contract.topic!("board"), topic_id})
    state
  end

  defp bot_status_request(topic_id) do
    Jason.encode!(%{
      event: Contract.event!("board_bot_status_map"),
      topic: Contract.topic!("board"),
      topic_id: topic_id
    })
  end

  defp chat_availability_request(topic_id) do
    Jason.encode!(%{
      event: Contract.event!("board_chat_available"),
      topic: Contract.topic!("board"),
      topic_id: topic_id
    })
  end

  defp chat_send_request(topic_id) do
    Jason.encode!(%{
      event: Contract.event!("board_chat_send"),
      topic: Contract.topic!("board"),
      topic_id: topic_id,
      data: %{message: "Summarize this card", task_id: @send_task_id}
    })
  end

  defp chat_cancel_request(topic_id) do
    Jason.encode!(%{
      event: Contract.event!("board_chat_cancel"),
      topic: Contract.topic!("board"),
      topic_id: topic_id,
      data: %{task_id: @send_task_id}
    })
  end

  defp chat_resume_request(topic_id) do
    Jason.encode!(%{
      event: Contract.event!("board_chat_resume"),
      topic: Contract.topic!("board"),
      topic_id: topic_id,
      data: %{
        message_uid: "12345678901",
        thread_id: "thread-uid",
        session_id: "session-uid",
        resume: %{approved: false, rejected: true}
      }
    })
  end

  defp restore_env(key, nil), do: Application.delete_env(:langboard_socket, key)
  defp restore_env(key, value), do: Application.put_env(:langboard_socket, key, value)

  defp notification_request(event_name, uid) do
    data = if uid, do: %{uid: uid}, else: %{}

    Jason.encode!(%{
      event: Contract.event!(event_name),
      topic: Contract.topic!("none"),
      data: data
    })
  end

  defp subscribed_ollama_state do
    {:push, _messages, state} =
      SocketHandler.init({{:ok, "user-uid"}, "access-token", 1024, 30_000, 32})

    request = Jason.encode!(%{event: "subscribe", topic: "ollama_manager", topic_id: "all"})

    {:push, {:text, _response}, subscribed_state} =
      SocketHandler.handle_in({request, opcode: :text}, state)

    subscribed_state
  end

  defp ollama_request(event_name, data) do
    Jason.encode!(%{
      event: Contract.event!(event_name),
      topic: Contract.topic!("ollama_manager"),
      topic_id: Contract.topic_id!("global"),
      data: data
    })
  end
end
