defmodule LangboardSocketWeb.HealthController do
  use LangboardSocketWeb, :controller

  def health(conn, _params), do: send_resp(conn, 204, "")
  def live(conn, _params), do: send_resp(conn, 204, "")

  def ready(conn, _params) do
    if LangboardSocket.RuntimeStatus.ready?() do
      send_resp(conn, 204, "")
    else
      send_resp(conn, 503, "")
    end
  end
end
