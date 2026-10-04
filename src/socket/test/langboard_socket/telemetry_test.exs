defmodule LangboardSocket.TelemetryTest do
  use ExUnit.Case, async: true

  test "Phoenix and Broadway OpenTelemetry handlers are attached" do
    handler_ids = :telemetry.list_handlers([]) |> Enum.map(& &1.id)

    assert {OpentelemetryPhoenix, :endpoint_start} in handler_ids
    assert {OpentelemetryPhoenix, :router_dispatch_start} in handler_ids
    assert "Elixir.OpentelemetryBroadway.message_start" in handler_ids
  end

  test "HTTP span attributes never include the authorization query" do
    conn =
      Plug.Test.conn(:get, "/?authorization=secret-token")
      |> Plug.Conn.fetch_query_params()

    attributes = LangboardSocketWeb.TelemetryPlug.span_attributes(conn)

    refute Map.has_key?(attributes, "url.query")
    refute inspect(attributes) =~ "secret-token"
  end
end
