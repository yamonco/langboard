defmodule LangboardSocketWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :langboard_socket

  # Code reloading can be explicitly enabled under the
  # :code_reloader configuration of your endpoint.
  if code_reloading? do
    plug Phoenix.CodeReloader
  end

  plug Plug.RequestId
  plug LangboardSocketWeb.TelemetryPlug
  plug Plug.Telemetry, event_prefix: [:phoenix, :endpoint]

  plug Plug.Head
  plug LangboardSocketWeb.SocketUpgrade
  plug LangboardSocketWeb.EditorHttpLimiterPlug

  plug Plug.Parsers,
    parsers: [:json],
    pass: ["application/json"],
    json_decoder: Jason,
    length: 8 * 1024 * 1024

  plug LangboardSocketWeb.Router
end
