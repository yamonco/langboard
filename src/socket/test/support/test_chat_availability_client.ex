defmodule LangboardSocket.TestChatAvailabilityClient do
  @moduledoc false

  @bot %{"uid" => "bot-uid", "bot_type" => "project_chat", "display_name" => "Project Assistant"}

  def fetch(token, project_uid) do
    send(
      Application.fetch_env!(:langboard_socket, :chat_availability_test_owner),
      {:chat_availability_request, self(), token, project_uid}
    )

    case project_uid do
      "hold:" <> _uid ->
        receive do
          :release -> {:ok, %{"available" => true, "bot" => @bot}}
        end

      "missing:" <> _uid ->
        {:ok, %{"available" => false, "bot" => nil}}

      "fail:" <> _uid ->
        {:error, :unavailable}

      "crash:" <> _uid ->
        raise "chat availability client failed"

      _ ->
        {:ok, %{"available" => true, "bot" => @bot}}
    end
  end
end
