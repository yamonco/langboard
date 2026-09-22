defmodule LangboardSocketWeb.EditorSyncHandlerTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.EditorDocument
  alias LangboardSocket.EditorSyncFrame
  alias LangboardSocket.EditorSyncStorage
  alias LangboardSocketWeb.EditorSyncHandler
  alias LangboardSocketWeb.SocketUpgrade

  @node_update Base.decode64!(
                 "AQb4rNGRAQAEAQV0aXRsZQZCZWZvcmUHAQtkZXNjcmlwdGlvbgMBcAcA+KzRkQEGBgYA+KzRkQEHBGJvbGQEdHJ1ZYT4rNGRAQgEUmljaIb4rNGRAQwEYm9sZARudWxsAA=="
               )

  setup do
    directory =
      Path.join(
        System.tmp_dir!(),
        "langboard-editor-handler-#{System.unique_integer([:positive])}"
      )

    name = "card:test-#{System.unique_integer([:positive])}:description"

    on_exit(fn ->
      case :global.whereis_name({EditorDocument, name}) do
        server when is_pid(server) ->
          DynamicSupervisor.terminate_child(LangboardSocket.EditorDocumentSupervisor, server)

        :undefined ->
          :ok
      end

      File.rm_rf!(directory)
    end)

    %{directory: directory, name: name}
  end

  test "drain sends the service restart close code", %{directory: directory} do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})
    assert {:stop, :normal, 1012, ^state} = EditorSyncHandler.handle_info(:socket_drain, state)
  end

  test "drain rejects an editor connection that already passed the upgrade check", %{
    directory: directory
  } do
    on_exit(fn -> LangboardSocket.RuntimeStatus.reset() end)
    :ok = LangboardSocket.RuntimeStatus.begin_drain()

    assert {:stop, :normal, 1012, _state} =
             EditorSyncHandler.init({"test-token", directory, 1024, 30_000})
  end

  test "the editor WebSocket upgrade rejects an incomplete cluster", %{directory: directory} do
    previous_enabled = Application.fetch_env!(:langboard_socket, :editor_sync_enabled)
    previous_directory = Application.fetch_env!(:langboard_socket, :editor_sync_directory)
    previous_nodes = Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_enabled, previous_enabled)
      Application.put_env(:langboard_socket, :editor_sync_directory, previous_directory)
      Application.put_env(:langboard_socket, :editor_sync_expected_nodes, previous_nodes)
    end)

    Application.put_env(:langboard_socket, :editor_sync_enabled, true)
    Application.put_env(:langboard_socket, :editor_sync_directory, directory)
    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, 2)

    conn =
      :get
      |> Plug.Test.conn("/editor-sync")
      |> Plug.Conn.put_req_header("upgrade", "websocket")
      |> SocketUpgrade.call([])

    assert conn.status == 503
    assert conn.halted
  end

  test "authenticates a document and acknowledges only a persisted update", %{
    directory: directory,
    name: name
  } do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})

    assert {:push, [auth, sync, awareness], joined} =
             EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    assert {:binary, authenticated} = auth
    assert {:ok, ^name, <<2, 2, 10, "read-write">>} = EditorSyncFrame.decode(authenticated, 1024)
    assert {:binary, sync_frame} = sync
    assert {:ok, ^name, sync_message} = EditorSyncFrame.decode(sync_frame, 1024)
    assert {:ok, {:sync, {:sync_step1, _vector}}} = Yex.Sync.message_decode(sync_message)
    assert {:binary, awareness_frame} = awareness
    assert {:ok, ^name, awareness_message} = EditorSyncFrame.decode(awareness_frame, 1024)
    assert {:ok, {:awareness, _update}} = Yex.Sync.message_decode(awareness_message)
    refute inspect(joined) =~ "test-token"
    assert Process.get(:authentication_calls, 0) == 0
    assert Process.get(:editor_authorization_calls) == 1

    message = Yex.Sync.message_encode!({:sync, {:sync_update, @node_update}})
    {:ok, frame} = EditorSyncFrame.encode(name, message)

    assert {:push, {:binary, status}, _state} =
             EditorSyncHandler.handle_in({frame, opcode: :binary}, joined)

    assert {:ok, ^name, <<8, 1>>} = EditorSyncFrame.decode(status, 1024)
    assert Process.get(:authentication_calls, 0) == 0
    assert Process.get(:editor_authorization_calls) == 2
    assert {:ok, saved} = EditorSyncStorage.load(name, directory)
    doc = Yex.Doc.new()
    assert :ok = Yex.apply_update(doc, saved)
    assert Yex.Text.to_string(Yex.Doc.get_text(doc, "title")) == "Before"
  end

  test "outbound telemetry includes encoded editor frames", %{directory: directory, name: name} do
    handler_id = {__MODULE__, self(), make_ref()}

    :ok =
      :telemetry.attach(
        handler_id,
        [:langboard_socket, :websocket, :outbound],
        fn _event, measurements, _metadata, owner ->
          send(owner, {:editor_outbound, measurements})
        end,
        self()
      )

    on_exit(fn -> :telemetry.detach(handler_id) end)

    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})

    assert {:push, frames, _joined} =
             EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    Enum.each(frames, fn {_opcode, payload} ->
      assert_receive {:editor_outbound, %{count: 1, bytes: bytes, queue_length: queue_length}}

      assert bytes == byte_size(payload)
      assert queue_length >= 0
    end)
  end

  test "a failed document write closes the socket without a saved acknowledgement", %{
    directory: directory,
    name: name
  } do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})

    assert {:push, _frames, joined} =
             EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    File.mkdir_p!(directory)
    blocked_directory = Path.join(directory, "not-a-directory")
    File.write!(blocked_directory, "unchanged")
    {server, _monitor} = Map.fetch!(joined.documents, name)
    :sys.replace_state(server, &%{&1 | directory: blocked_directory})

    message = Yex.Sync.message_encode!({:sync, {:sync_update, @node_update}})
    {:ok, frame} = EditorSyncFrame.encode(name, message)

    assert {:stop, :normal, 1011, ^joined} =
             EditorSyncHandler.handle_in({frame, opcode: :binary}, joined)

    assert File.read!(blocked_directory) == "unchanged"
    assert {:ok, nil} = EditorSyncStorage.load(name, directory)
  end

  test "a role downgrade keeps reads active and rejects later writes", %{
    directory: directory,
    name: name
  } do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})

    assert {:push, _frames, joined} =
             EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    Process.put(:editor_authorization_result, {:ok, "Verified Editor", false})
    message = Yex.Sync.message_encode!({:sync, {:sync_update, @node_update}})
    {:ok, frame} = EditorSyncFrame.encode(name, message)

    assert {:push, {:binary, status}, ^joined} =
             EditorSyncHandler.handle_in({frame, opcode: :binary}, joined)

    assert {:ok, ^name, <<8, 0>>} = EditorSyncFrame.decode(status, 1024)
    assert {:ok, nil} = EditorSyncStorage.load(name, directory)

    assert {:push, {:binary, peer_update}, ^joined} =
             EditorSyncHandler.handle_info({:editor_document_update, name, @node_update}, joined)

    assert {:ok, ^name, peer_message} = EditorSyncFrame.decode(peer_update, 1024)
    assert {:ok, {:sync, {:sync_update, @node_update}}} = Yex.Sync.message_decode(peer_message)
  end

  test "the query token permits the first sync frame before a token frame", %{
    directory: directory,
    name: name
  } do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})
    message = Yex.Sync.message_encode!({:sync, {:sync_step1, <<0>>}})
    {:ok, frame} = EditorSyncFrame.encode(name, message)

    assert {:push, frames, joined} = EditorSyncHandler.handle_in({frame, opcode: :binary}, state)
    assert length(frames) == 3
    assert Map.has_key?(joined.documents, name)
  end

  test "a query token authenticates an empty Hocuspocus token frame", %{
    directory: directory,
    name: name
  } do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})
    {:ok, empty_auth} = EditorSyncFrame.encode(name, <<2, 0, 0>>)

    assert {:push, [_authenticated, _sync, _awareness], joined} =
             EditorSyncHandler.handle_in({empty_auth, opcode: :binary}, state)

    assert Map.has_key?(joined.documents, name)

    {:ok, missing_token} = EditorSyncHandler.init({nil, directory, 1024, 30_000})

    assert {:stop, :normal, 4401, ^missing_token} =
             EditorSyncHandler.handle_in({empty_auth, opcode: :binary}, missing_token)
  end

  test "malformed awareness closes the connection with invalid data", %{
    directory: directory,
    name: name
  } do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})

    assert {:push, _frames, joined} =
             EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    message = Yex.Sync.message_encode!({:awareness, <<1, 0x80>>})
    {:ok, frame} = EditorSyncFrame.encode(name, message)

    assert {:stop, :normal, 1007, ^joined} =
             EditorSyncHandler.handle_in({frame, opcode: :binary}, joined)
  end

  test "denied and missing credentials cannot join a document", %{
    directory: directory,
    name: name
  } do
    Process.put(:editor_authorization_result, {:error, :forbidden})
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})

    assert {:stop, :normal, 4403, ^state} =
             EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    {:ok, no_token} = EditorSyncHandler.init({nil, directory, 1024, 30_000})
    message = Yex.Sync.message_encode!({:sync, {:sync_step1, <<0>>}})
    {:ok, frame} = EditorSyncFrame.encode(name, message)

    assert {:stop, :normal, 4401, ^no_token} =
             EditorSyncHandler.handle_in({frame, opcode: :binary}, no_token)
  end

  test "rich patch responses use the authenticated document owner and saved fanout", %{
    directory: directory,
    name: name
  } do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 4096, 30_000})

    {:push, _frames, joined} =
      EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    {:ok, server} = EditorDocument.active(name)
    task = Task.async(fn -> EditorDocument.request_rich_patch(server, "Updated") end)
    assert_receive {:editor_document_stateless, ^name, frame} = outbound
    assert {:push, {:binary, ^frame}, ^joined} = EditorSyncHandler.handle_info(outbound, joined)
    {:ok, ^name, message} = EditorSyncFrame.decode(frame, 4096)
    {:ok, payload} = EditorSyncFrame.decode_stateless(message)
    %{"request_id" => id} = Jason.decode!(payload)

    {:ok, response} =
      EditorSyncFrame.stateless(
        name,
        Jason.encode!(%{
          type: "rich_patch_prepared",
          request_id: id,
          update: Base.encode64(@node_update)
        })
      )

    assert {:ok, ^joined} = EditorSyncHandler.handle_in({response, opcode: :binary}, joined)
    assert :ok = Task.await(task)
    assert {:ok, saved} = EditorSyncStorage.load(name, directory)
    assert is_binary(saved)
    assert_receive {:editor_document_update, ^name, @node_update}
    assert {:ok, ^joined} = EditorSyncHandler.handle_in({response, opcode: :binary}, joined)
    refute_receive {:editor_document_update, ^name, _update}
    {:ok, malformed} = EditorSyncFrame.stateless(name, "{}")

    assert {:stop, :normal, 1007, ^joined} =
             EditorSyncHandler.handle_in({malformed, opcode: :binary}, joined)
  end

  test "revoked document access stops edits, peer updates, awareness, and idle connections", %{
    directory: directory,
    name: name
  } do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})

    assert {:push, _frames, joined} =
             EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    Process.put(:editor_authorization_result, {:error, :forbidden})
    message = Yex.Sync.message_encode!({:sync, {:sync_update, @node_update}})
    {:ok, frame} = EditorSyncFrame.encode(name, message)

    assert {:stop, :normal, 4403, ^joined} =
             EditorSyncHandler.handle_in({frame, opcode: :binary}, joined)

    assert {:stop, :normal, 4403, ^joined} =
             EditorSyncHandler.handle_info({:editor_document_update, name, @node_update}, joined)

    assert {:stop, :normal, 4403, ^joined} =
             EditorSyncHandler.handle_info({:editor_document_awareness, name, <<0>>}, joined)

    assert {:stop, :normal, 4403, ^joined} =
             EditorSyncHandler.handle_info({:editor_document_stateless, name, <<5, 0>>}, joined)

    {:ok, stateless} = EditorSyncFrame.stateless(name, "{}")

    assert {:stop, :normal, 4403, ^joined} =
             EditorSyncHandler.handle_in({stateless, opcode: :binary}, joined)

    assert {:stop, :normal, 4403, ^joined} = EditorSyncHandler.handle_info(:ping, joined)

    assert {:ok, nil} = EditorSyncStorage.load(name, directory)

    Process.put(:editor_authorization_result, {:error, :unauthorized})
    assert {:stop, :normal, 4401, ^joined} = EditorSyncHandler.handle_info(:ping, joined)

    Process.put(:editor_authorization_result, {:error, :expired_token})
    assert {:stop, :normal, 4401, ^joined} = EditorSyncHandler.handle_info(:ping, joined)

    Process.put(:editor_authorization_result, {:error, :unavailable})
    assert {:stop, :normal, 1011, ^joined} = EditorSyncHandler.handle_info(:ping, joined)
  end

  test "invalid auth frames and text frames are rejected", %{directory: directory, name: name} do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})
    {:ok, invalid_auth} = EditorSyncFrame.encode(name, <<2, 0, 3, "ab">>)

    assert {:stop, :normal, 1007, ^state} =
             EditorSyncHandler.handle_in({invalid_auth, opcode: :binary}, state)

    assert {:stop, :normal, 1003, ^state} =
             EditorSyncHandler.handle_in({"hello", opcode: :text}, state)
  end

  test "rejects outbound frames beyond the configured payload", %{
    directory: directory,
    name: name
  } do
    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})

    assert {:push, _frames, joined} =
             EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    oversized = %{joined | max_payload: 1}

    assert {:stop, :normal, 1009, ^oversized} =
             EditorSyncHandler.handle_info(
               {:editor_document_update, name, @node_update},
               oversized
             )
  end

  test "reports editor slow clients before closing a saturated connection", %{
    directory: directory,
    name: name
  } do
    previous_max_queue =
      Application.fetch_env!(:langboard_socket, :socket_max_outbound_queue_messages)

    Application.put_env(:langboard_socket, :socket_max_outbound_queue_messages, 1)

    handler_id = {__MODULE__, self(), make_ref()}

    :ok =
      :telemetry.attach(
        handler_id,
        [:langboard_socket, :websocket, :slow_client],
        fn _event, measurements, _metadata, owner ->
          send(owner, {:editor_slow_client, measurements})
        end,
        self()
      )

    on_exit(fn ->
      :telemetry.detach(handler_id)

      Application.put_env(
        :langboard_socket,
        :socket_max_outbound_queue_messages,
        previous_max_queue
      )
    end)

    {:ok, state} = EditorSyncHandler.init({"test-token", directory, 1024, 30_000})

    assert {:stop, :normal, 1013, stopped_state} =
             EditorSyncHandler.handle_in({auth_frame(name), opcode: :binary}, state)

    assert_receive {:editor_slow_client, %{count: 1, queue_length: queue_length}}
    assert queue_length >= 0
    assert :ok = EditorSyncHandler.terminate(:normal, stopped_state)
  end

  defp auth_frame(name) do
    {:ok, frame} = EditorSyncFrame.encode(name, <<2, 0, 10, "test-token">>)
    frame
  end
end
