defmodule LangboardSocket.NotificationClientTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.NotificationClient

  test "read and delete use the authenticated notification API" do
    for {action, uid, method, path} <- [
          {:read, "a/b", "PUT", "/notifications/a%2Fb/read"},
          {:read_all, nil, "PUT", "/notifications/read-all"},
          {:delete, "a/b", "DELETE", "/notifications/a%2Fb"},
          {:delete_all, nil, "DELETE", "/notifications"}
        ] do
      Req.Test.expect(__MODULE__, fn conn ->
        assert conn.method == method
        assert conn.request_path == path
        assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
        Plug.Conn.send_resp(conn, 200, "{}")
      end)

      assert :ok =
               NotificationClient.execute("access-token", action, uid,
                 plug: {Req.Test, __MODULE__}
               )
    end
  end

  test "API failures retain authorization and validation distinctions" do
    for {status, expected} <- [
          {400, :invalid_data},
          {401, :unauthorized},
          {403, :forbidden},
          {500, :unavailable}
        ] do
      Req.Test.expect(__MODULE__, fn conn -> Plug.Conn.send_resp(conn, status, "{}") end)

      assert {:error, ^expected} =
               NotificationClient.execute("access-token", :read_all, nil,
                 plug: {Req.Test, __MODULE__}
               )
    end
  end
end
