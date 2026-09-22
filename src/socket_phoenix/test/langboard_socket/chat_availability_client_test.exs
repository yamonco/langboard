defmodule LangboardSocket.ChatAvailabilityClientTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.ChatAvailabilityClient

  test "reads the authenticated project chat availability response" do
    bot = %{"uid" => "bot-uid", "display_name" => "Project Assistant"}

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "GET"
      assert conn.request_path == "/auth/socket/board/a%2Fb/chat/availability"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, Jason.encode!(%{available: true, bot: bot}))
    end)

    assert {:ok, %{"available" => true, "bot" => ^bot}} =
             ChatAvailabilityClient.fetch("access-token", "a/b", plug: {Req.Test, __MODULE__})
  end

  test "a missing or unhealthy bot remains an unavailable chat response" do
    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"available":false,"bot":null}))
    end)

    assert {:ok, %{"available" => false, "bot" => nil}} =
             ChatAvailabilityClient.fetch("access-token", "project-uid",
               plug: {Req.Test, __MODULE__}
             )
  end

  test "authorization and malformed backend responses fail closed" do
    for {status, body, expected} <- [
          {401, "{}", :unauthorized},
          {403, "{}", :forbidden},
          {500, "{}", :unavailable},
          {200, ~s({"available":true,"bot":null}), :unavailable}
        ] do
      Req.Test.expect(__MODULE__, fn conn -> Plug.Conn.send_resp(conn, status, body) end)

      assert {:error, ^expected} =
               ChatAvailabilityClient.fetch("access-token", "project-uid",
                 plug: {Req.Test, __MODULE__}
               )
    end
  end
end
