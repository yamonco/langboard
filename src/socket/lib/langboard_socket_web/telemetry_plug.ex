defmodule LangboardSocketWeb.TelemetryPlug do
  @moduledoc false
  @behaviour Plug

  import Plug.Conn

  require OpenTelemetry.Tracer, as: Tracer

  @impl true
  def init(options), do: options

  @impl true
  def call(conn, _options) do
    :otel_propagator_text_map.extract(conn.req_headers)

    conn
    |> span_name()
    |> Tracer.start_span(%{kind: :server, attributes: span_attributes(conn)})
    |> Tracer.set_current_span()

    register_before_send(conn, fn conn ->
      Tracer.set_attribute("http.response.status_code", conn.status)

      if conn.status >= 500 do
        Tracer.set_status(:error, "server error")
      end

      Tracer.end_span()
      conn
    end)
  end

  @doc false
  def span_attributes(conn) do
    %{
      "http.request.method" => conn.method,
      "server.address" => conn.host,
      "server.port" => conn.port,
      "url.path" => conn.request_path,
      "url.scheme" => Atom.to_string(conn.scheme)
    }
  end

  defp span_name(conn), do: conn.method <> " " <> conn.request_path
end
