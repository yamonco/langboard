defmodule LangboardSocketWeb.EditorSyncControllerTest do
  use LangboardSocketWeb.ConnCase, async: false

  alias LangboardSocket.EditorDocument
  alias LangboardSocket.EditorHttpLimiter
  alias LangboardSocket.EditorSyncStorage

  setup do
    previous = Application.fetch_env!(:langboard_socket, :editor_sync_enabled)
    previous_directory = Application.fetch_env!(:langboard_socket, :editor_sync_directory)
    Application.put_env(:langboard_socket, :editor_sync_enabled, true)

    name = "card:test-#{System.unique_integer([:positive])}:description"

    directory =
      Path.join(System.tmp_dir!(), "langboard-editor-http-#{System.unique_integer([:positive])}")

    Application.put_env(:langboard_socket, :editor_sync_directory, directory)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_enabled, previous)
      Application.put_env(:langboard_socket, :editor_sync_directory, previous_directory)

      case :global.whereis_name({EditorDocument, name}) do
        server when is_pid(server) ->
          DynamicSupervisor.terminate_child(LangboardSocket.EditorDocumentSupervisor, server)

        :undefined ->
          :ok
      end

      File.rm_rf!(directory)
    end)

    %{name: name, directory: directory}
  end

  test "reports authorized active drafts across the document owner", %{
    conn: conn,
    name: name,
    directory: directory
  } do
    {:ok, _server} = EditorDocument.ensure_started(name, directory)
    inactive_name = "card:inactive-#{System.unique_integer([:positive])}:description"

    response =
      conn
      |> put_req_header("x-api-token", "internal-token")
      |> post_json("/editor-sync/active", %{document_names: [inactive_name, name, name]})

    assert json_response(response, 200) == %{"active_document_names" => [name]}

    assert Process.get(:editor_http_batch_credentials) ==
             {{:api_token, "internal-token"}, [inactive_name, name], [write: false]}

    assert :sys.get_state(EditorHttpLimiter).holders == %{}
  end

  test "rich patch HTTP response waits for the document owner to persist", %{
    conn: conn,
    name: name,
    directory: directory
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    {:ok, _messages} = EditorDocument.join(server, self())

    task =
      Task.async(fn ->
        conn
        |> put_req_header("x-api-token", "internal-token")
        |> post_json("/editor-sync/rich/patch-request", %{document_name: name, value: "After"})
      end)

    assert_receive {:editor_document_stateless, ^name, frame}
    assert Task.yield(task, 0) == nil
    {:ok, ^name, message} = LangboardSocket.EditorSyncFrame.decode(frame, 4096)
    {:ok, payload} = LangboardSocket.EditorSyncFrame.decode_stateless(message)
    %{"request_id" => id} = Jason.decode!(payload)
    doc = Yex.Doc.new()
    :ok = Yex.Text.insert(Yex.Doc.get_text(doc, "content"), 0, "After")

    assert :ok =
             EditorDocument.apply_rich_patch(server, self(), id, Yex.encode_state_as_update!(doc))

    assert Task.await(task) |> json_response(200) == %{}
    assert {:ok, saved} = EditorSyncStorage.load(name, directory)
    assert is_binary(saved)
    assert :sys.get_state(EditorHttpLimiter).holders == %{}
  end

  test "rich patch validates names and authorization before checking the active owner", %{
    conn: conn,
    name: name
  } do
    body = %{document_name: name, value: "After"}
    assert conn |> post_json("/editor-sync/rich/patch-request", body) |> json_response(401) == %{}
    Process.put(:editor_http_authorization_result, {:ok, false})

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/rich/patch-request", body)
           |> json_response(403) == %{}

    Process.put(:editor_http_authorization_result, {:ok, true})

    for invalid <- ["", "card:one:title", "wiki:one:title", "card::description", 123] do
      response =
        conn
        |> recycle()
        |> put_req_header("x-api-token", "internal-token")
        |> post_json("/editor-sync/rich/patch-request", %{document_name: invalid, value: "After"})

      assert response.status == 400
    end

    response =
      conn
      |> recycle()
      |> put_req_header("x-api-token", "internal-token")
      |> post_json("/editor-sync/rich/patch-request", body)

    assert response.status == 409
  end

  test "rejects invalid or unauthorized active-draft lookups", %{conn: conn, name: name} do
    assert conn
           |> post_json("/editor-sync/active", %{document_names: [name]})
           |> json_response(401) == %{}

    Process.put(:editor_http_batch_authorization_result, {:ok, false})

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/active", %{document_names: [name]})
           |> json_response(403) == %{}

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/active", %{document_names: [name, 123]})
           |> json_response(400) == %{"message" => "Invalid editor sync payload."}

    too_many =
      List.duplicate(
        name,
        Application.fetch_env!(:langboard_socket, :editor_sync_max_documents) + 1
      )

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/active", %{document_names: too_many})
           |> json_response(400) == %{"message" => "Invalid editor sync payload."}
  end

  test "active-draft lookup fails closed on auth backend errors and authenticates empty lists", %{
    conn: conn,
    name: name
  } do
    Process.put(:editor_http_batch_authorization_result, {:error, :unavailable})

    assert conn
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/active", %{document_names: [name]})
           |> json_response(503) == %{"message" => "Editor sync is unavailable."}

    Process.put(:editor_http_batch_authorization_result, {:error, :unauthorized})

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/active", %{document_names: []})
           |> json_response(401) == %{}

    assert Process.get(:editor_http_batch_credentials) ==
             {{:api_token, "internal-token"}, [], [write: false]}
  end

  test "active-draft lookup authorizes configured lists in bounded batches", %{conn: conn} do
    previous = Application.fetch_env!(:langboard_socket, :editor_sync_max_documents)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_max_documents, previous)
    end)

    Application.put_env(:langboard_socket, :editor_sync_max_documents, 300)
    names = for index <- 1..257, do: "card:inactive-#{index}"

    assert conn
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/active", %{document_names: names})
           |> json_response(200) == %{"active_document_names" => []}

    assert Process.get(:editor_http_batch_calls) |> Enum.reverse() == [
             Enum.take(names, 256),
             [List.last(names)]
           ]
  end

  test "clear deletes only authorized inactive drafts and can be retried", %{
    conn: conn,
    name: name,
    directory: directory
  } do
    assert :ok = EditorSyncStorage.save(name, <<1, 2, 3>>, directory)

    for _ <- 1..2 do
      assert conn
             |> recycle()
             |> put_req_header("x-api-token", "internal-token")
             |> post_json("/editor-sync/clear", %{document_names: [name]})
             |> json_response(200) == %{}
    end

    assert {:ok, nil} = EditorSyncStorage.load(name, directory)

    assert Process.get(:editor_http_batch_credentials) ==
             {{:api_token, "internal-token"}, [name], [write: true]}
  end

  test "clear rejects active drafts and leaves their saved state intact", %{
    conn: conn,
    name: name,
    directory: directory
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert :ok = EditorDocument.replace_text(server, "title", "Keep")
    assert {:ok, saved} = EditorSyncStorage.load(name, directory)

    assert conn
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/clear", %{document_names: [name]})
           |> json_response(403) == %{}

    assert {:ok, ^saved} = EditorSyncStorage.load(name, directory)
  end

  test "clear fails closed before deletion on missing or denied credentials", %{
    conn: conn,
    name: name,
    directory: directory
  } do
    assert :ok = EditorSyncStorage.save(name, <<1, 2, 3>>, directory)

    assert conn
           |> post_json("/editor-sync/clear", %{document_names: [name]})
           |> json_response(401) == %{}

    Process.put(:editor_http_batch_authorization_result, {:ok, false})

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/clear", %{document_names: [name]})
           |> json_response(403) == %{}

    assert {:ok, <<1, 2, 3>>} = EditorSyncStorage.load(name, directory)
  end

  test "reads an active text draft with the existing internal token", %{
    conn: conn,
    name: name,
    directory: directory
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert :ok = EditorDocument.replace_text(server, "title", "Before")

    response =
      conn
      |> put_req_header("x-api-token", "internal-token")
      |> post_json("/editor-sync/text", %{document_name: name, field: "title"})

    assert json_response(response, 200) == %{"value" => "Before"}

    assert Process.get(:editor_http_credentials) ==
             {{:api_token, "internal-token"}, name, [write: false]}

    assert :sys.get_state(EditorHttpLimiter).holders == %{}
  end

  test "replaces an active text draft and broadcasts a persisted Yjs update", %{
    conn: conn,
    name: name,
    directory: directory
  } do
    {:ok, server} = EditorDocument.ensure_started(name, directory)
    assert {:ok, _messages} = EditorDocument.join(server, self())

    response =
      conn
      |> put_req_header("authorization", "bearer access-token")
      |> put_req_header("cookie", "refresh=value")
      |> post_json("/editor-sync/text/patch", %{
        document_name: name,
        field: "title",
        value: "After"
      })

    assert json_response(response, 200) == %{}

    assert Process.get(:editor_http_credentials) ==
             {{:bearer, "access-token", "refresh=value"}, name, [write: true]}

    assert_receive {:editor_document_update, ^name, _update}
    assert {:ok, saved} = EditorSyncStorage.load(name, directory)
    doc = Yex.Doc.new()
    assert :ok = Yex.apply_update(doc, saved)
    assert Yex.Text.to_string(Yex.Doc.get_text(doc, "title")) == "After"
  end

  test "rejects missing credentials, denied access, and inactive drafts", %{
    conn: conn,
    name: name
  } do
    body = %{document_name: name, field: "title"}
    assert conn |> post_json("/editor-sync/text", body) |> json_response(401) == %{}

    Process.put(:editor_http_authorization_result, {:ok, false})

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/text", body)
           |> json_response(403) == %{}

    Process.put(:editor_http_authorization_result, {:ok, true})

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/text", body)
           |> json_response(409) == %{"message" => "The collaborative draft is not active."}
  end

  test "the HTTP route stays disabled with the editor feature flag", %{conn: conn, name: name} do
    Application.put_env(:langboard_socket, :editor_sync_enabled, false)

    assert conn
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/text", %{document_name: name, field: "title"})
           |> json_response(503) == %{"message" => "Editor sync is unavailable."}

    assert :sys.get_state(EditorHttpLimiter).holders == %{}
  end

  test "the HTTP route rejects a missing editor storage directory", %{
    conn: conn,
    name: name,
    directory: directory
  } do
    assert :ok = EditorSyncStorage.save(name, <<1, 2, 3>>, directory)
    Application.put_env(:langboard_socket, :editor_sync_directory, "")

    assert conn
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/clear", %{document_names: [name]})
           |> json_response(503) == %{"message" => "Editor sync is unavailable."}

    assert {:ok, <<1, 2, 3>>} = EditorSyncStorage.load(name, directory)
  end

  test "the HTTP route rejects an incomplete editor cluster", %{conn: conn, name: name} do
    previous = Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_expected_nodes, previous)
    end)

    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, 2)

    assert conn
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/text", %{document_name: name, field: "title"})
           |> json_response(503) == %{"message" => "Editor sync is unavailable."}
  end

  test "HTTP admission is bounded before parsing and recovers when request processes exit", %{
    conn: conn,
    name: name
  } do
    parent = self()
    max = :sys.get_state(EditorHttpLimiter).max

    holders =
      for _ <- 1..max do
        spawn(fn ->
          send(parent, {:slot_acquired, EditorHttpLimiter.acquire()})
          Process.sleep(:infinity)
        end)
      end

    on_exit(fn -> Enum.each(holders, &Process.exit(&1, :kill)) end)

    for _ <- holders do
      assert_receive {:slot_acquired, :ok}
    end

    assert conn
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/text", %{document_name: name, field: "title"})
           |> json_response(503) == %{"message" => "Too many concurrent editor sync requests."}

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/active", %{document_names: [name]})
           |> json_response(503) == %{"message" => "Too many concurrent editor sync requests."}

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/clear", %{document_names: [name]})
           |> json_response(503) == %{"message" => "Too many concurrent editor sync requests."}

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/text/patch", %{
             document_name: name,
             field: "title",
             value: "Not admitted"
           })
           |> json_response(503) == %{"message" => "Too many concurrent editor sync requests."}

    Enum.each(holders, &Process.exit(&1, :kill))
    assert_slots_released()

    assert conn
           |> recycle()
           |> put_req_header("x-api-token", "internal-token")
           |> post_json("/editor-sync/text", %{document_name: name, field: "title"})
           |> json_response(409) == %{"message" => "The collaborative draft is not active."}

    assert :sys.get_state(EditorHttpLimiter).holders == %{}
  end

  defp post_json(conn, path, body) do
    conn
    |> put_req_header("content-type", "application/json")
    |> post(path, Jason.encode!(body))
  end

  defp assert_slots_released do
    deadline = System.monotonic_time(:millisecond) + 1_000
    assert_slots_released(deadline)
  end

  defp assert_slots_released(deadline) do
    if :sys.get_state(EditorHttpLimiter).holders != %{} do
      assert System.monotonic_time(:millisecond) < deadline
      Process.sleep(1)
      assert_slots_released(deadline)
    end
  end
end
