defmodule LangboardSocket.EditorDocumentTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.EditorDocument
  alias LangboardSocket.EditorSyncStorage

  @awareness_frame Base.decode64!(
                     "GGNhcmQ6Zml4dHVyZTpkZXNjcmlwdGlvbgE1AZIhATB7InVzZXIiOnsibmFtZSI6IkVkaXRvciJ9LCJjdXJzb3IiOnsiYW5jaG9yIjoyfX0="
                   )

  setup do
    directory =
      Path.join(
        System.tmp_dir!(),
        "langboard-editor-document-#{System.unique_integer([:positive])}"
      )

    name = "card:test-#{System.unique_integer([:positive])}:description"
    on_exit(fn -> File.rm_rf!(directory) end)
    %{directory: directory, name: name}
  end

  test "lists only active documents for an exact type and entity without truncating", %{
    directory: directory
  } do
    entity_uid = "test-#{System.unique_integer([:positive])}"

    scoped_names = [
      "card:#{entity_uid}",
      "card:#{entity_uid}:description",
      "card:#{entity_uid}:title"
    ]

    names =
      scoped_names ++ ["card:#{entity_uid}x:description", "wiki:#{entity_uid}:content"]

    servers =
      Enum.map(names, fn name ->
        {:ok, server} = EditorDocument.ensure_started(name, directory)
        server
      end)

    on_exit(fn ->
      Enum.each(servers, fn server ->
        if Process.alive?(server),
          do: DynamicSupervisor.terminate_child(LangboardSocket.EditorDocumentSupervisor, server)
      end)
    end)

    assert {:ok, ^scoped_names} = EditorDocument.active_names("card", entity_uid, 3)
    assert {:error, :too_many_documents} = EditorDocument.active_names("card", entity_uid, 2)
    assert {:ok, []} = EditorDocument.active_names("card", "#{entity_uid}-missing", 2)

    [first | _rest] = servers

    assert :ok =
             DynamicSupervisor.terminate_child(LangboardSocket.EditorDocumentSupervisor, first)

    remaining_names = tl(scoped_names)
    assert {:ok, ^remaining_names} = EditorDocument.active_names("card", entity_uid, 2)
  end

  test "serializes concurrent clients and restores the saved Yjs state", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    client = self()
    peer = spawn(fn -> relay_messages(client) end)
    on_exit(fn -> Process.exit(peer, :kill) end)

    assert {:ok, [_sync, _awareness]} = EditorDocument.join(server, self())
    assert {:ok, [_sync, _awareness]} = EditorDocument.join(server, peer)

    update_a = text_update("a", "First")
    update_b = text_update("b", "Second")

    task_a = Task.async(fn -> EditorDocument.apply_update(server, client, update_a) end)
    task_b = Task.async(fn -> EditorDocument.apply_update(server, client, update_b) end)
    assert :ok = Task.await(task_a)
    assert :ok = Task.await(task_b)

    assert {:ok, saved} = EditorSyncStorage.load(name, directory)
    restored = Yex.Doc.new()
    assert :ok = Yex.apply_update(restored, saved)
    assert Yex.Text.to_string(Yex.Doc.get_text(restored, "a")) == "First"
    assert Yex.Text.to_string(Yex.Doc.get_text(restored, "b")) == "Second"

    monitor = Process.monitor(server)

    assert :ok =
             DynamicSupervisor.terminate_child(LangboardSocket.EditorDocumentSupervisor, server)

    assert_receive {:DOWN, ^monitor, :process, ^server, _reason}
    assert_owner_released(name)

    {:ok, reloaded} = EditorDocument.ensure_started(name, directory)
    assert {:ok, [_sync, _awareness]} = EditorDocument.join(reloaded, self())
    assert {:ok, reply} = EditorDocument.sync_step1(reloaded, self(), <<0>>)
    assert {:ok, {:sync, {:sync_step2, state}}} = Yex.Sync.message_decode(reply)
    replay = Yex.Doc.new()
    assert :ok = Yex.apply_update(replay, state)
    assert Yex.Text.to_string(Yex.Doc.get_text(replay, "a")) == "First"
    assert Yex.Text.to_string(Yex.Doc.get_text(replay, "b")) == "Second"
  end

  test "accepts one prepared patch, persists before replying, and ignores duplicate peers",
       context do
    %{directory: directory, name: name} = context
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    task = Task.async(fn -> EditorDocument.request_rich_patch(server, "After") end)
    {id, snapshot} = receive_rich_patch(name)
    assert Task.yield(task, 0) == nil
    assert {:error, :busy} = EditorDocument.request_rich_patch(server, "Another")
    update = prepared_update(snapshot, "After")
    assert :ok = EditorDocument.apply_rich_patch(server, self(), id, update)
    assert :ok = Task.await(task)
    assert {:ok, saved} = EditorSyncStorage.load(name, directory)

    assert :ok =
             EditorDocument.apply_rich_patch(
               server,
               self(),
               id,
               prepared_update(snapshot, "Duplicate")
             )

    assert {:ok, ^saved} = EditorSyncStorage.load(name, directory)
    assert {:ok, "After"} = EditorDocument.get_text(server, "content")
    assert :sys.get_state(server).rich_patch == nil
  end

  test "rejects a prepared patch after a concurrent delete even if the state vector is unchanged",
       context do
    %{directory: directory, name: name} = context
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert :ok = EditorDocument.replace_text(server, "content", "Before")
    task = Task.async(fn -> EditorDocument.request_rich_patch(server, "After") end)
    {id, snapshot} = receive_rich_patch(name)
    assert :ok = EditorDocument.replace_text(server, "content", "")

    assert :ok =
             EditorDocument.apply_rich_patch(
               server,
               self(),
               id,
               prepared_update(snapshot, "After")
             )

    assert {:error, :conflict} = Task.await(task)
    assert {:ok, ""} = EditorDocument.get_text(server, "content")
    assert :sys.get_state(server).rich_patch == nil
  end

  test "patch timeout and last editor departure release the pending request", context do
    %{directory: directory, name: name} = context
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert {:error, :inactive} = EditorDocument.request_rich_patch(server, "After")
    assert {:ok, _messages} = EditorDocument.join(server, self())
    task = Task.async(fn -> EditorDocument.request_rich_patch(server, "After") end)
    {id, snapshot} = receive_rich_patch(name)
    timer = :sys.get_state(server).rich_patch.timer
    send(server, {:timeout, timer, :rich_patch})
    assert {:error, :timeout} = Task.await(task)

    assert :ok =
             EditorDocument.apply_rich_patch(
               server,
               self(),
               id,
               prepared_update(snapshot, "Late")
             )

    assert {:ok, nil} = EditorSyncStorage.load(name, directory)
    next_task = Task.async(fn -> EditorDocument.request_rich_patch(server, "After") end)
    receive_rich_patch(name)
    assert :ok = EditorDocument.leave(server, self())
    assert {:error, :inactive} = Task.await(next_task)
    assert :sys.get_state(server).rich_patch == nil
  end

  test "patch preparation requires a joined editor and a bounded frame", context do
    %{directory: directory, name: name} = context
    {:ok, server} = EditorDocument.ensure_started(name, directory)

    assert {:error, :not_joined} =
             EditorDocument.apply_rich_patch(server, self(), "unknown", <<>>)

    assert {:ok, _messages} = EditorDocument.join(server, self())
    previous = Application.fetch_env!(:langboard_socket, :socket_max_payload_bytes)
    on_exit(fn -> Application.put_env(:langboard_socket, :socket_max_payload_bytes, previous) end)
    Application.put_env(:langboard_socket, :socket_max_payload_bytes, 256)

    assert {:error, :frame_too_large} =
             EditorDocument.request_rich_patch(server, String.duplicate("x", 256))

    assert :sys.get_state(server).rich_patch == nil
  end

  defp receive_rich_patch(name) do
    assert_receive {:editor_document_stateless, ^name, frame}
    assert {:ok, ^name, message} = LangboardSocket.EditorSyncFrame.decode(frame, 1_048_576)
    assert {:ok, payload} = LangboardSocket.EditorSyncFrame.decode_stateless(message)

    %{"type" => "rich_patch_prepare", "request_id" => id, "snapshot" => snapshot} =
      Jason.decode!(payload)

    {id, Base.decode64!(snapshot)}
  end

  test "a lost caller releases its patch and cannot leave a late writer", context do
    %{directory: directory, name: name} = context
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    caller = spawn(fn -> EditorDocument.request_rich_patch(server, "After") end)
    {id, snapshot} = receive_rich_patch(name)
    pending = :sys.get_state(server).rich_patch
    Process.exit(caller, :kill)
    send(server, {:DOWN, pending.monitor, :process, caller, :killed})
    assert :sys.get_state(server).rich_patch == nil

    assert :ok =
             EditorDocument.apply_rich_patch(
               server,
               self(),
               id,
               prepared_update(snapshot, "Late")
             )

    assert {:ok, nil} = EditorSyncStorage.load(name, directory)
  end

  test "a rich patch storage failure does not acknowledge or broadcast the update", context do
    %{directory: directory, name: name} = context
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert {:ok, _messages} = EditorDocument.join(server, self())

    task =
      Task.async(fn ->
        try do
          EditorDocument.request_rich_patch(server, "After")
        catch
          :exit, _reason -> :unavailable
        end
      end)

    {id, snapshot} = receive_rich_patch(name)
    assert :ok = File.write(directory, "occupied")

    assert {:error, _reason} =
             EditorDocument.apply_rich_patch(
               server,
               self(),
               id,
               prepared_update(snapshot, "After")
             )

    assert :unavailable = Task.await(task)
    refute_receive {:editor_document_update, ^name, _update}
    assert_receive {:editor_document_closed, ^name, {:document_update_failed, _reason}}
  end

  defp prepared_update(snapshot, value) do
    doc = Yex.Doc.new()
    :ok = Yex.apply_update(doc, snapshot)
    {:ok, vector} = Yex.encode_state_vector(doc)
    text = Yex.Doc.get_text(doc, "content")
    :ok = Yex.Text.delete(text, 0, Yex.Text.length(text))
    :ok = Yex.Text.insert(text, 0, value)
    Yex.encode_state_as_update!(doc, vector)
  end

  test "relays awareness and removes it when the owning client leaves", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    test_pid = self()
    peer = spawn(fn -> relay_messages(test_pid) end)
    on_exit(fn -> Process.exit(peer, :kill) end)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert {:ok, _messages} = EditorDocument.join(server, peer)

    assert {:ok, _document_name, message} =
             LangboardSocket.EditorSyncFrame.decode(@awareness_frame, 1024)

    assert {:ok, {:awareness, present}} = Yex.Sync.message_decode(message)
    assert :ok = EditorDocument.apply_awareness(server, self(), present, "Editor")
    assert_receive {:peer_message, {:editor_document_awareness, ^name, received}}
    {:ok, awareness} = Yex.Awareness.new(Yex.Doc.new())
    assert :ok = Yex.Awareness.apply_update(awareness, received)
    assert Map.has_key?(Yex.Awareness.get_states(awareness), 4242)

    assert :ok = EditorDocument.leave(server, self())
    assert_receive {:peer_message, {:editor_document_awareness, ^name, removed}}
    assert :ok = Yex.Awareness.apply_update(awareness, removed)
    refute Map.has_key?(Yex.Awareness.get_states(awareness), 4242)
  end

  test "rejects updates and removals for another connection's awareness client ID", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    test_pid = self()
    peer = spawn(fn -> relay_messages(test_pid) end)
    on_exit(fn -> Process.exit(peer, :kill) end)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert {:ok, _messages} = EditorDocument.join(server, peer)

    {:ok, owner_awareness} =
      Yex.Awareness.new(Yex.Doc.with_options(%Yex.Doc.Options{client_id: 4242}))

    assert :ok = Yex.Awareness.set_local_state(owner_awareness, %{"user" => %{"name" => "Owner"}})
    {:ok, owner_update} = Yex.Awareness.encode_update(owner_awareness)
    assert :ok = EditorDocument.apply_awareness(server, self(), owner_update, "Owner")

    {:ok, forged_awareness} =
      Yex.Awareness.new(Yex.Doc.with_options(%Yex.Doc.Options{client_id: 4242}))

    assert :ok =
             Yex.Awareness.set_local_state(forged_awareness, %{"user" => %{"name" => "Other"}})

    assert :ok =
             Yex.Awareness.set_local_state(forged_awareness, %{"user" => %{"name" => "Impostor"}})

    {:ok, forged_update} = Yex.Awareness.encode_update(forged_awareness)

    assert {:error, :invalid_awareness} =
             EditorDocument.apply_awareness(server, peer, forged_update, "Other")

    assert :ok = Yex.Awareness.clean_local_state(forged_awareness)
    {:ok, forged_removal} = Yex.Awareness.encode_update(forged_awareness, [4242])

    assert {:error, :invalid_awareness} =
             EditorDocument.apply_awareness(server, peer, forged_removal, "Other")

    {:ok, mixed_awareness} =
      Yex.Awareness.new(Yex.Doc.with_options(%Yex.Doc.Options{client_id: 5252}))

    assert :ok = Yex.Awareness.apply_update(mixed_awareness, owner_update)
    assert :ok = Yex.Awareness.set_local_state(mixed_awareness, %{"data" => %{}})
    {:ok, mixed_update} = Yex.Awareness.encode_update(mixed_awareness)

    assert {:error, :invalid_awareness} =
             EditorDocument.apply_awareness(server, peer, mixed_update, "Other")

    state = :sys.get_state(server)

    assert get_in(Yex.Awareness.get_states(state.awareness), [4242, "data", "name"]) ==
             "Owner"

    refute Map.has_key?(Yex.Awareness.get_states(state.awareness), 5252)

    assert Process.alive?(server)
  end

  test "ignores a peer's identical awareness echo without transferring ownership", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    test_pid = self()
    peer = spawn(fn -> relay_messages(test_pid) end)
    on_exit(fn -> Process.exit(peer, :kill) end)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert {:ok, _messages} = EditorDocument.join(server, peer)

    {:ok, owner_awareness} =
      Yex.Awareness.new(Yex.Doc.with_options(%Yex.Doc.Options{client_id: 4242}))

    assert :ok =
             Yex.Awareness.set_local_state(owner_awareness, %{"data" => %{"name" => "Claimed"}})

    {:ok, owner_update} = Yex.Awareness.encode_update(owner_awareness)
    assert :ok = EditorDocument.apply_awareness(server, self(), owner_update, "Owner")
    assert_receive {:peer_message, {:editor_document_awareness, ^name, _update}}

    current = :sys.get_state(server)
    {:ok, echo} = Yex.Awareness.encode_update(current.awareness, [4242])
    assert :ok = EditorDocument.apply_awareness(server, peer, echo, "Peer")
    refute_receive {:editor_document_awareness, ^name, _update}, 20

    after_echo = :sys.get_state(server)
    assert after_echo.awareness_owners[4242] == self()

    assert get_in(Yex.Awareness.get_states(after_echo.awareness), [4242, "data", "name"]) ==
             "Owner"

    {:ok, [entry]} = LangboardSocket.EditorSyncFrame.decode_awareness(echo, 32)
    changed_state = Map.update!(entry.state, "data", &Map.put(&1, "color", "forged"))

    {:ok, _ids, changed_echo} =
      LangboardSocket.EditorSyncFrame.encode_awareness([%{entry | state: changed_state}], "Owner")

    assert {:error, :invalid_awareness} =
             EditorDocument.apply_awareness(server, peer, changed_echo, "Peer")

    refute_receive {:editor_document_awareness, ^name, _update}, 20
    refute_receive {:peer_message, {:editor_document_awareness, ^name, _update}}, 20
    after_rejection = :sys.get_state(server)
    assert after_rejection.awareness_owners == after_echo.awareness_owners
    assert Yex.Awareness.get_states(after_rejection.awareness)[4242] == entry.state

    assert :ok = EditorDocument.leave(server, peer)
    after_peer_leave = :sys.get_state(server)
    assert Map.has_key?(Yex.Awareness.get_states(after_peer_leave.awareness), 4242)
  end

  test "accepts an owned cursor in a batch with an unchanged peer echo", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    test_pid = self()
    peer = spawn(fn -> relay_messages(test_pid) end)
    on_exit(fn -> Process.exit(peer, :kill) end)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert {:ok, _messages} = EditorDocument.join(server, peer)

    {:ok, owner_awareness} =
      Yex.Awareness.new(Yex.Doc.with_options(%Yex.Doc.Options{client_id: 4242}))

    assert :ok = Yex.Awareness.set_local_state(owner_awareness, %{"data" => %{}})
    {:ok, owner_update} = Yex.Awareness.encode_update(owner_awareness)
    assert :ok = EditorDocument.apply_awareness(server, self(), owner_update, "Owner")
    assert_receive {:peer_message, {:editor_document_awareness, ^name, _update}}

    {:ok, mixed_awareness} =
      Yex.Awareness.new(Yex.Doc.with_options(%Yex.Doc.Options{client_id: 5252}))

    current = :sys.get_state(server)
    {:ok, echo} = Yex.Awareness.encode_update(current.awareness, [4242])
    assert :ok = Yex.Awareness.apply_update(mixed_awareness, echo)
    assert :ok = Yex.Awareness.set_local_state(mixed_awareness, %{"data" => %{}})
    {:ok, mixed_update} = Yex.Awareness.encode_update(mixed_awareness)
    assert :ok = EditorDocument.apply_awareness(server, peer, mixed_update, "Peer")

    after_batch = :sys.get_state(server)
    assert after_batch.awareness_owners[4242] == self()
    assert after_batch.awareness_owners[5252] == peer

    assert get_in(Yex.Awareness.get_states(after_batch.awareness), [5252, "data", "name"]) ==
             "Peer"

    assert :ok = EditorDocument.leave(server, peer)
    after_peer_leave = :sys.get_state(server)
    assert Map.has_key?(Yex.Awareness.get_states(after_peer_leave.awareness), 4242)
    refute Map.has_key?(Yex.Awareness.get_states(after_peer_leave.awareness), 5252)
  end

  test "ignores a stale peer echo after the owner advances its cursor", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    test_pid = self()
    peer = spawn(fn -> relay_messages(test_pid) end)
    on_exit(fn -> Process.exit(peer, :kill) end)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert {:ok, _messages} = EditorDocument.join(server, peer)

    {:ok, owner_awareness} =
      Yex.Awareness.new(Yex.Doc.with_options(%Yex.Doc.Options{client_id: 4242}))

    assert :ok = Yex.Awareness.set_local_state(owner_awareness, %{"data" => %{"color" => "red"}})
    {:ok, initial_update} = Yex.Awareness.encode_update(owner_awareness)
    assert :ok = EditorDocument.apply_awareness(server, self(), initial_update, "Owner")
    assert_receive {:peer_message, {:editor_document_awareness, ^name, _update}}

    initial = :sys.get_state(server)
    {:ok, stale_echo} = Yex.Awareness.encode_update(initial.awareness, [4242])
    assert :ok = Yex.Awareness.set_local_state(owner_awareness, %{"data" => %{"color" => "blue"}})
    {:ok, newer_update} = Yex.Awareness.encode_update(owner_awareness)
    assert :ok = EditorDocument.apply_awareness(server, self(), newer_update, "Owner")
    assert_receive {:peer_message, {:editor_document_awareness, ^name, _update}}

    assert :ok = EditorDocument.apply_awareness(server, peer, stale_echo, "Peer")
    current = :sys.get_state(server)
    assert current.awareness_owners[4242] == self()

    assert get_in(Yex.Awareness.get_states(current.awareness), [4242, "data", "color"]) ==
             "blue"
  end

  test "replaces a client's claimed cursor name with the authorized name", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    test_pid = self()
    peer = spawn(fn -> relay_messages(test_pid) end)
    on_exit(fn -> Process.exit(peer, :kill) end)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert {:ok, _messages} = EditorDocument.join(server, peer)

    {:ok, awareness} =
      Yex.Awareness.new(Yex.Doc.with_options(%Yex.Doc.Options{client_id: 5252}))

    assert :ok =
             Yex.Awareness.set_local_state(awareness, %{
               "data" => %{"name" => "Impostor", "color" => "red"},
               "user" => %{"name" => "Impostor"}
             })

    {:ok, update} = Yex.Awareness.encode_update(awareness)
    assert :ok = EditorDocument.apply_awareness(server, self(), update, "Verified Editor")

    assert_receive {:peer_message, {:editor_document_awareness, ^name, received}}
    {:ok, mirror} = Yex.Awareness.new(Yex.Doc.new())
    assert :ok = Yex.Awareness.apply_update(mirror, received)
    state = Yex.Awareness.get_states(mirror)[5252]
    assert state["data"] == %{"name" => "Verified Editor", "color" => "red"}
    assert state["user"]["name"] == "Verified Editor"
  end

  test "expires stale awareness without disconnecting the editor", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    test_pid = self()
    peer = spawn(fn -> relay_messages(test_pid) end)
    on_exit(fn -> Process.exit(peer, :kill) end)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert {:ok, _messages} = EditorDocument.join(server, peer)

    assert {:ok, _document_name, message} =
             LangboardSocket.EditorSyncFrame.decode(@awareness_frame, 1024)

    assert {:ok, {:awareness, present}} = Yex.Sync.message_decode(message)
    assert :ok = EditorDocument.apply_awareness(server, self(), present, "Editor")
    assert_receive {:peer_message, {:editor_document_awareness, ^name, _update}}

    state = :sys.get_state(server)
    assert Map.has_key?(state.awareness_last_seen, 4242)

    :sys.replace_state(server, fn current ->
      %{current | awareness_last_seen: %{4242 => System.monotonic_time(:millisecond) - 30_001}}
    end)

    send(server, {:timeout, state.awareness_ref, :awareness_sweep})
    assert_receive {:peer_message, {:editor_document_awareness, ^name, removed}}
    {:ok, awareness} = Yex.Awareness.new(Yex.Doc.new())
    assert :ok = Yex.Awareness.apply_update(awareness, present)
    assert :ok = Yex.Awareness.apply_update(awareness, removed)
    refute Map.has_key?(Yex.Awareness.get_states(awareness), 4242)
    assert Process.alive?(server)
  end

  test "direct text replacement persists and sends a Yjs delta to every editor", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    test_pid = self()
    peer = spawn(fn -> relay_messages(test_pid) end)
    on_exit(fn -> Process.exit(peer, :kill) end)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert {:ok, _messages} = EditorDocument.join(server, peer)

    assert :ok = EditorDocument.apply_update(server, self(), text_update("content", "Before"))
    assert_receive {:peer_message, {:editor_document_update, ^name, _initial_update}}
    refute_receive {:editor_document_update, ^name, _echo}, 20
    assert {:ok, "Before"} = EditorDocument.get_text(server, "content")
    assert {:ok, initial_state} = EditorSyncStorage.load(name, directory)
    mirror = Yex.Doc.new()
    assert :ok = Yex.apply_update(mirror, initial_state)

    assert :ok = EditorDocument.replace_text(server, "content", "After")
    assert_receive {:editor_document_update, ^name, delta}
    assert_receive {:peer_message, {:editor_document_update, ^name, ^delta}}
    assert :ok = Yex.apply_update(mirror, delta)
    assert Yex.Text.to_string(Yex.Doc.get_text(mirror, "content")) == "After"
    assert {:ok, "After"} = EditorDocument.get_text(server, "content")

    assert {:ok, saved} = EditorSyncStorage.load(name, directory)
    persisted = Yex.Doc.new()
    assert :ok = Yex.apply_update(persisted, saved)
    assert Yex.Text.to_string(Yex.Doc.get_text(persisted, "content")) == "After"

    assert :ok = EditorDocument.replace_text(server, "content", "After")
    refute_receive {:editor_document_update, ^name, _update}, 20
    refute_receive {:peer_message, {:editor_document_update, ^name, _update}}, 20
  end

  test "a direct text replacement does not broadcast when storage fails", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert :ok = File.write(directory, "occupied")

    assert {:error, _reason} = EditorDocument.replace_text(server, "content", "Not saved")
    refute_receive {:editor_document_update, ^name, _update}, 20
    assert_receive {:editor_document_closed, ^name, {:document_update_failed, _reason}}
  end

  test "a failed save stops the document without acknowledging the update", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    monitor = Process.monitor(server)
    assert {:ok, _messages} = EditorDocument.join(server, self())

    assert :ok = File.write(directory, "occupied")

    assert {:error, _reason} =
             EditorDocument.apply_update(server, self(), text_update("title", "Lost"))

    assert_receive {:editor_document_closed, ^name, {:document_update_failed, _reason}}
    assert_receive {:DOWN, ^monitor, :process, ^server, {:document_update_failed, _reason}}
    refute Process.alive?(server)
  end

  test "a document with no clients is evicted while a joined document ignores a stale idle timer",
       %{
         directory: directory,
         name: name
       } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    initial_idle_ref = :sys.get_state(server).idle_ref
    monitor = Process.monitor(server)

    assert {:ok, _messages} = EditorDocument.join(server, self())
    send(server, {:timeout, initial_idle_ref, :idle})
    assert Process.alive?(server)

    assert :ok = EditorDocument.leave(server, self())
    next_idle_ref = :sys.get_state(server).idle_ref
    send(server, {:timeout, next_idle_ref, :idle})
    assert_receive {:DOWN, ^monitor, :process, ^server, :normal}
  end

  test "concurrent starts resolve to one document owner", %{directory: directory, name: name} do
    tasks =
      for _ <- 1..12, do: Task.async(fn -> EditorDocument.ensure_started(name, directory) end)

    owners = Enum.map(tasks, &Task.await/1)

    assert [{:ok, owner}] = Enum.uniq(owners)
    assert :global.whereis_name({EditorDocument, name}) == owner
  end

  test "inactive deletion and document startup cannot erase each other's state", %{
    directory: directory,
    name: base_name
  } do
    for iteration <- 1..20 do
      name = "#{base_name}-#{iteration}"
      assert :ok = EditorSyncStorage.save(name, text_update("title", "Before"), directory)
      gate = make_ref()

      clear =
        Task.async(fn ->
          receive do
            {:go, ^gate} -> EditorDocument.clear_inactive(name, directory)
          end
        end)

      start =
        Task.async(fn ->
          receive do
            {:go, ^gate} -> EditorDocument.ensure_started(name, directory)
          end
        end)

      send(clear.pid, {:go, gate})
      send(start.pid, {:go, gate})

      clear_result = Task.await(clear, 10_000)
      assert {:ok, server} = Task.await(start, 10_000)

      case clear_result do
        :ok ->
          assert {:ok, nil} = EditorSyncStorage.load(name, directory)
          assert {:ok, ""} = EditorDocument.get_text(server, "title")

        {:error, :active} ->
          assert {:ok, saved} = EditorSyncStorage.load(name, directory)
          restored = Yex.Doc.new()
          assert :ok = Yex.apply_update(restored, saved)
          assert Yex.Text.to_string(Yex.Doc.get_text(restored, "title")) == "Before"
      end

      assert :ok =
               DynamicSupervisor.terminate_child(LangboardSocket.EditorDocumentSupervisor, server)

      assert_owner_released(name)
    end
  end

  test "clear preserves inactive drafts when the editor cluster is incomplete", %{
    directory: directory,
    name: name
  } do
    assert :ok = EditorSyncStorage.save(name, <<1, 2, 3>>, directory)
    previous = Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_expected_nodes, previous)
    end)

    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, 2)

    assert {:error, :cluster_unavailable} = EditorDocument.clear_inactive(name, directory)
    assert {:ok, <<1, 2, 3>>} = EditorSyncStorage.load(name, directory)
  end

  test "rejects an incomplete cluster before starting a document", %{
    directory: directory,
    name: name
  } do
    previous = Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_expected_nodes, previous)
    end)

    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, 2)

    assert {:error, :cluster_unavailable} = EditorDocument.ensure_started(name, directory)
    assert {:error, :cluster_unavailable} = EditorDocument.active(name)
    assert {:error, :cluster_unavailable} = EditorDocument.active_names("card", "test", 2)
    assert :undefined == :global.whereis_name({EditorDocument, name})
  end

  test "stops a document without saving an update after cluster membership is lost", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    assert :ok = EditorDocument.replace_text(server, "title", "Saved")
    assert {:ok, saved} = EditorSyncStorage.load(name, directory)

    previous = Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_expected_nodes, previous)
    end)

    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, 2)

    monitor = Process.monitor(server)

    assert {:error, :cluster_unavailable} =
             EditorDocument.apply_update(server, self(), text_update("title", "Rejected"))

    assert_receive {:editor_document_closed, ^name, {:shutdown, :cluster_unavailable}}
    assert_receive {:DOWN, ^monitor, :process, ^server, {:shutdown, :cluster_unavailable}}
    assert {:ok, ^saved} = EditorSyncStorage.load(name, directory)
  end

  test "closes an active document when a peer node disconnects", %{
    directory: directory,
    name: name
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert {:ok, _messages} = EditorDocument.join(server, self())
    monitor = Process.monitor(server)

    send(server, {:nodedown, :peer@host})

    assert_receive {:editor_document_closed, ^name, {:shutdown, :cluster_changed}}
    assert_receive {:DOWN, ^monitor, :process, ^server, {:shutdown, :cluster_changed}}
    assert_owner_released(name)
  end

  defp text_update(field, value) do
    doc = Yex.Doc.new()
    Yex.Text.insert(Yex.Doc.get_text(doc, field), 0, value)
    Yex.encode_state_as_update!(doc)
  end

  defp assert_owner_released(name) do
    assert_owner_released(name, System.monotonic_time(:millisecond) + 1_000)
  end

  defp assert_owner_released(name, deadline) do
    case :global.whereis_name({EditorDocument, name}) do
      :undefined ->
        :ok

      _pid ->
        assert System.monotonic_time(:millisecond) < deadline
        Process.sleep(1)
        assert_owner_released(name, deadline)
    end
  end

  defp relay_messages(test_pid) do
    receive do
      message ->
        send(test_pid, {:peer_message, message})
        relay_messages(test_pid)
    end
  end
end
