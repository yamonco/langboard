defmodule LangboardSocket.BoardChatActiveDocuments do
  @moduledoc false

  alias LangboardSocket.EditorDocument

  @max_names 128

  def collect(project_uid, "project", nil) when is_binary(project_uid) and project_uid != "",
    do: {:ok, []}

  def collect(project_uid, scope_table, scope_uid)
      when is_binary(project_uid) and project_uid != "" and is_binary(scope_uid) and
             scope_uid != "" and scope_table in ["card", "project_column", "project_wiki"] do
    if editor_ready?() do
      collect_scope(project_uid, scope_table, scope_uid)
    else
      {:error, :unavailable}
    end
  end

  def collect(_project_uid, _scope_table, _scope_uid), do: {:error, :invalid_data}

  defp collect_scope(project_uid, "card", scope_uid) do
    with {:ok, card_names} <- active_names("card", scope_uid),
         {:ok, schedule_names} <- active_names("bot-schedule", project_uid) do
      relevant_schedules =
        Enum.filter(
          schedule_names,
          &String.starts_with?(&1, "bot-schedule:#{project_uid}:card-#{scope_uid}-")
        )

      bounded_names(card_names ++ relevant_schedules)
    end
  end

  defp collect_scope(project_uid, "project_column", scope_uid) do
    with {:ok, column_names} <- active_names("board-column-name", project_uid),
         {:ok, schedule_names} <- active_names("bot-schedule", project_uid) do
      column_name = "board-column-name:#{project_uid}:#{scope_uid}"
      schedule_prefix = "bot-schedule:#{project_uid}:project_column-#{scope_uid}-"

      bounded_names(
        Enum.filter(column_names, &(&1 == column_name)) ++
          Enum.filter(schedule_names, &String.starts_with?(&1, schedule_prefix))
      )
    end
  end

  defp collect_scope(_project_uid, "project_wiki", scope_uid) do
    with {:ok, wiki_names} <- active_names("wiki", scope_uid) do
      bounded_names(wiki_names)
    end
  end

  defp active_names(type, entity_uid) do
    max_registered =
      Application.fetch_env!(:langboard_socket, :editor_sync_max_documents) *
        Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)

    EditorDocument.active_names(type, entity_uid, max_registered)
  end

  defp bounded_names(names) do
    unique_names = Enum.uniq(names)

    if length(unique_names) <= @max_names,
      do: {:ok, Enum.sort(unique_names)},
      else: {:error, :too_many_documents}
  end

  defp editor_ready? do
    Application.fetch_env!(:langboard_socket, :editor_sync_enabled) and
      Application.fetch_env!(:langboard_socket, :editor_sync_directory) != "" and
      EditorDocument.cluster_ready?()
  end
end
