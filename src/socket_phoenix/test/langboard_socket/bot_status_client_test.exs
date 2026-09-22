defmodule LangboardSocket.BotStatusClientTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.BotStatusClient

  test "reads the project-scoped map from Graph's response" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/bot/status/map"
      assert conn.query_string == "project_uid=project-uid"

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        Jason.encode!(%{status_map: %{project_column: %{"column-uid" => ["bot-uid"]}}})
      )
    end)

    assert {:ok, %{"project_column" => %{"column-uid" => ["bot-uid"]}, "card" => %{}}} =
             BotStatusClient.fetch("project-uid", plug: {Req.Test, __MODULE__})
  end

  test "an empty Graph map keeps both UI status categories" do
    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, Jason.encode!(%{status_map: %{}}))
    end)

    assert {:ok, %{"project_column" => %{}, "card" => %{}}} =
             BotStatusClient.fetch("project-uid", plug: {Req.Test, __MODULE__})
  end

  test "a refused Graph connection matches the previous empty-map fallback" do
    Req.Test.expect(__MODULE__, &Req.Test.transport_error(&1, :econnrefused))

    assert {:ok, %{"project_column" => %{}, "card" => %{}}} =
             BotStatusClient.fetch("project-uid", plug: {Req.Test, __MODULE__})
  end

  test "unexpected responses remain unavailable" do
    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, Jason.encode!(%{status_map: []}))
    end)

    assert {:error, :unavailable} =
             BotStatusClient.fetch("project-uid", plug: {Req.Test, __MODULE__})
  end
end
