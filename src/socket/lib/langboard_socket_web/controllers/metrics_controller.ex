defmodule LangboardSocketWeb.MetricsController do
  use LangboardSocketWeb, :controller

  def index(conn, _params) do
    secret = Application.fetch_env!(:langboard_socket, :internal_api_secret)

    with true <- byte_size(secret) >= 32,
         [provided] <- get_req_header(conn, "x-socket-internal-secret"),
         true <- Plug.Crypto.secure_compare(provided, secret) do
      conn
      |> put_resp_content_type("text/plain", "utf-8")
      |> put_resp_header("cache-control", "no-store")
      |> send_resp(200, TelemetryMetricsPrometheus.Core.scrape())
    else
      _ -> send_resp(conn, 401, "")
    end
  end
end
