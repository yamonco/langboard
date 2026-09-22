defmodule LangboardSocket.TestAuthClient do
  @moduledoc false

  def authenticate(_token) do
    Process.put(:authentication_calls, Process.get(:authentication_calls, 0) + 1)
    Process.get(:authentication_result, {:ok, "user-uid"})
  end

  def authorize_subscriptions(_token, _topic, topic_ids) do
    Process.get(:authorization_result, {:ok, topic_ids})
  end

  def authorize_editor_document(_token, _document_name) do
    Process.put(
      :editor_authorization_calls,
      Process.get(:editor_authorization_calls, 0) + 1
    )

    Process.get(:editor_authorization_result, {:ok, "Verified Editor", true})
  end

  def authorize_editor_http_document(credentials, document_name, options \\ []) do
    Process.put(:editor_http_credentials, {credentials, document_name, options})
    Process.get(:editor_http_authorization_result, {:ok, true})
  end

  def authorize_editor_http_documents(credentials, document_names, options \\ []) do
    Process.put(:editor_http_batch_credentials, {credentials, document_names, options})

    Process.put(
      :editor_http_batch_calls,
      [document_names | Process.get(:editor_http_batch_calls, [])]
    )

    Process.get(:editor_http_batch_authorization_result, {:ok, true})
  end

  def ready?, do: Process.get(:authorization_ready, true)
end
