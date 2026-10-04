defmodule LangboardSocketWeb.HealthController do
  use LangboardSocketWeb, :controller

  alias LangboardSocket.Editor.SyncStorage
  alias LangboardSocket.RuntimeStatus

  def health(conn, _params), do: send_resp(conn, 204, "")
  def live(conn, _params), do: send_resp(conn, 204, "")

  def ready(conn, _params) do
    if RuntimeStatus.ready?() and
         (not Application.fetch_env!(:langboard_socket, :editor_sync_enabled) or
            SyncStorage.verify_writable(
              Application.fetch_env!(:langboard_socket, :editor_sync_directory)
            ) == :ok) do
      send_resp(conn, 204, "")
    else
      send_resp(conn, 503, "")
    end
  end
end
