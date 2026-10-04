defmodule LangboardSocket.TestNotificationClient do
  @moduledoc false

  def execute(token, action, uid) do
    send(
      Application.fetch_env!(:langboard_socket, :notification_test_owner),
      {:notification_request, self(), token, action, uid}
    )

    case uid do
      "hold0000000" ->
        receive do
          :release -> :ok
        end

      "fail0000000" ->
        {:error, :unavailable}

      "unauth00000" ->
        {:error, :unauthorized}

      "crash000000" ->
        raise "notification client failed"

      _ ->
        :ok
    end
  end
end
