defmodule LangboardSocket.EditorSyncFrameTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.EditorSyncFrame

  @document_name "card:fixture:description"
  @node_sync_step1 Base.decode64!("GGNhcmQ6Zml4dHVyZTpkZXNjcmlwdGlvbgAAAQA=")
  @node_auth Base.decode64!("GGNhcmQ6Zml4dHVyZTpkZXNjcmlwdGlvbgIACnRlc3QtdG9rZW4=")
  @node_ack Base.decode64!("GGNhcmQ6Zml4dHVyZTpkZXNjcmlwdGlvbgICCnJlYWQtd3JpdGU=")

  test "decodes and re-encodes a Node Hocuspocus sync frame" do
    assert {:ok, @document_name, message} = EditorSyncFrame.decode(@node_sync_step1, 8_388_608)
    assert {:ok, {:sync, {:sync_step1, _state_vector}}} = Yex.Sync.message_decode(message)
    assert {:ok, @node_sync_step1} = EditorSyncFrame.encode(@document_name, message)
  end

  test "supports a multi-byte lib0 document-name length" do
    name = String.duplicate("a", 130)
    message = Yex.Sync.message_encode!({:sync, {:sync_step1, <<0>>}})

    assert {:ok, frame} = EditorSyncFrame.encode(name, message)
    assert <<0x82, 0x01, _rest::binary>> = frame
    assert {:ok, ^name, ^message} = EditorSyncFrame.decode(frame, 1_024)
  end

  test "decodes the Node authentication request and emits its authenticated response" do
    assert {:ok, @document_name, auth_message} = EditorSyncFrame.decode(@node_auth, 1024)
    assert {:ok, "test-token"} = EditorSyncFrame.decode_auth_token(auth_message)
    assert {:ok, @node_ack} = EditorSyncFrame.authenticated(@document_name)
    assert {:ok, readonly} = EditorSyncFrame.authenticated(@document_name, false)

    assert {:ok, @document_name, <<2, 2, 8, "readonly">>} =
             EditorSyncFrame.decode(readonly, 1024)

    assert {:ok, _status} = EditorSyncFrame.sync_status(@document_name, true)
    assert {:error, :invalid_auth_frame} = EditorSyncFrame.decode_auth_token(<<2, 0, 3, "ab">>)
  end

  test "rejects oversized and malformed frames" do
    assert {:error, :frame_too_large} = EditorSyncFrame.decode(@node_sync_step1, 2)
    assert {:error, :invalid_length} = EditorSyncFrame.decode(<<0x80>>, 10)

    assert {:error, :invalid_length} =
             EditorSyncFrame.decode(<<0xFF, 0xFF, 0xFF, 0xFF, 0x10>>, 10)

    assert {:error, :invalid_frame} = EditorSyncFrame.decode(<<3, "ab">>, 10)
    assert {:error, :invalid_frame} = EditorSyncFrame.decode(<<1, 0xFF, 0>>, 10)
    assert {:error, :invalid_frame} = EditorSyncFrame.decode(<<1, "a">>, 10)
    assert {:error, :invalid_frame} = EditorSyncFrame.encode("", <<0>>)
  end

  test "extracts awareness ownership IDs and rejects malformed batches" do
    assert {:ok, [4242], <<1, 0x92, 0x21, 1, 4, "null">>} =
             EditorSyncFrame.normalize_awareness(<<1, 0x92, 0x21, 1, 4, "null">>, 32, "Editor")

    assert {:ok, [1], _normalized} =
             EditorSyncFrame.normalize_awareness(
               <<1, 1, 0x80, 0x80, 0x80, 0x80, 0x10, 4, "null">>,
               32,
               "Editor"
             )

    assert {:ok, [%{clock_value: 4_294_967_296}]} =
             EditorSyncFrame.decode_awareness(
               <<1, 1, 0x80, 0x80, 0x80, 0x80, 0x10, 4, "null">>,
               32
             )

    assert {:error, :invalid_awareness} =
             EditorSyncFrame.normalize_awareness(<<33>>, 32, "Editor")

    assert {:error, :invalid_awareness} =
             EditorSyncFrame.normalize_awareness(<<1, 1, 1, 4, "nu">>, 32, "Editor")

    assert {:error, :invalid_awareness} =
             EditorSyncFrame.normalize_awareness(
               <<2, 1, 1, 4, "null", 1, 2, 4, "null">>,
               32,
               "Editor"
             )

    assert {:error, :invalid_awareness} =
             EditorSyncFrame.normalize_awareness(<<1, 1, 1, 4, "nope">>, 32, "Editor")
  end

  test "accepts the installed Hocuspocus provider's initial empty awareness state" do
    assert {:ok, {:sync, {:sync_step1, <<0>>}}} =
             Yex.Sync.message_decode(Base.decode16!("00000100", case: :lower))

    assert {:ok, {:sync, {:sync_step2, <<0, 0>>}}} =
             Yex.Sync.message_decode(Base.decode16!("0001020000", case: :lower))

    message = Base.decode16!("010a01c5b7e0b90100027b7d", case: :lower)
    assert {:ok, {:awareness, update}} = Yex.Sync.message_decode(message)

    assert {:ok, [_client_id], normalized} =
             EditorSyncFrame.normalize_awareness(update, 32, "Verified Editor")

    assert byte_size(normalized) > byte_size(update)
  end

  test "encodes ordered awareness batches with unchanged clock and identity bytes" do
    entries = [
      %{id: 0, clock: <<0>>, state: %{"user" => %{"name" => "Untrusted"}}},
      %{id: 0xFFFFFFFF, clock: <<0x80, 1>>, state: nil}
    ]

    assert {:ok, [0, 0xFFFFFFFF], encoded} = EditorSyncFrame.encode_awareness(entries, "Editor")
    assert {:ok, [first, last]} = EditorSyncFrame.decode_awareness(encoded, 2)
    assert first.id == 0
    assert first.clock == <<0>>
    assert first.state["user"]["name"] == "Editor"
    assert first.state["data"]["name"] == "Editor"
    assert last == %{id: 0xFFFFFFFF, clock: <<0x80, 1>>, clock_value: 128, state: nil}
    assert {:ok, [], <<0>>} = EditorSyncFrame.encode_awareness([], "Editor")

    for id <- [-1, 0x100000000, 1.0, nil] do
      assert {:error, :invalid_awareness} =
               EditorSyncFrame.encode_awareness([%{id: id, clock: <<0>>, state: nil}], "Editor")
    end
  end
end
