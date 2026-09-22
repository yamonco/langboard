defmodule LangboardSocket.BoardChatActiveDocumentsTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.BoardChatActiveDocuments
  alias LangboardSocket.EditorDocument

  setup do
    enabled = Application.fetch_env!(:langboard_socket, :editor_sync_enabled)
    directory = Application.fetch_env!(:langboard_socket, :editor_sync_directory)
    expected_nodes = Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)

    test_directory =
      Path.join(
        System.tmp_dir!(),
        "langboard-board-chat-documents-#{System.unique_integer([:positive])}"
      )

    Application.put_env(:langboard_socket, :editor_sync_enabled, true)
    Application.put_env(:langboard_socket, :editor_sync_directory, test_directory)
    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, 1)

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_enabled, enabled)
      Application.put_env(:langboard_socket, :editor_sync_directory, directory)
      Application.put_env(:langboard_socket, :editor_sync_expected_nodes, expected_nodes)
      File.rm_rf!(test_directory)
    end)

    %{directory: test_directory}
  end

  test "collects only active names for the selected card, column, or wiki", %{
    directory: directory
  } do
    unique = System.unique_integer([:positive])
    project_uid = "project-#{unique}"
    scope_uid = "scope-#{unique}"
    card_name = "card:#{scope_uid}:description"
    card_schedule = "bot-schedule:#{project_uid}:card-#{scope_uid}-daily"
    column_name = "board-column-name:#{project_uid}:#{scope_uid}"
    column_schedule = "bot-schedule:#{project_uid}:project_column-#{scope_uid}-daily"
    wiki_name = "wiki:#{scope_uid}:content"

    names = [
      card_name,
      card_schedule,
      column_name,
      column_schedule,
      wiki_name,
      "card:#{scope_uid}x:description",
      "bot-schedule:#{project_uid}:card-#{scope_uid}x-daily"
    ]

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

    assert {:ok, card_names} = BoardChatActiveDocuments.collect(project_uid, "card", scope_uid)
    assert card_names == Enum.sort([card_name, card_schedule])

    assert {:ok, column_names} =
             BoardChatActiveDocuments.collect(project_uid, "project_column", scope_uid)

    assert column_names == Enum.sort([column_name, column_schedule])

    assert {:ok, [^wiki_name]} =
             BoardChatActiveDocuments.collect(project_uid, "project_wiki", scope_uid)

    assert {:ok, []} = BoardChatActiveDocuments.collect(project_uid, "project", nil)
  end

  test "rejects scoped collection when editor ownership is unavailable" do
    Application.put_env(:langboard_socket, :editor_sync_enabled, false)
    assert {:error, :unavailable} = BoardChatActiveDocuments.collect("project", "card", "card")
    assert {:ok, []} = BoardChatActiveDocuments.collect("project", "project", nil)

    Application.put_env(:langboard_socket, :editor_sync_enabled, true)
    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, 2)
    assert {:error, :unavailable} = BoardChatActiveDocuments.collect("project", "card", "card")
    assert {:error, :invalid_data} = BoardChatActiveDocuments.collect("project", "card", nil)
  end
end
