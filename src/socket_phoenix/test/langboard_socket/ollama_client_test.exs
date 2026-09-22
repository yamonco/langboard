defmodule LangboardSocket.OllamaClientTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.OllamaClient

  test "model commands forward data with bearer authentication" do
    for {action, method, path, data} <- [
          {:copy, "POST", "/auth/socket/ollama/models/copy",
           %{"model" => "source", "copy_to" => "copy"}},
          {:delete, "DELETE", "/auth/socket/ollama/models", %{"model" => "source"}},
          {:pull, "POST", "/auth/socket/ollama/models/pull", %{"model" => "source"}}
        ] do
      Req.Test.expect(__MODULE__, fn conn ->
        assert conn.method == method
        assert conn.request_path == path
        assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
        {:ok, body, conn} = Plug.Conn.read_body(conn)
        assert Jason.decode!(body) == data
        Plug.Conn.send_resp(conn, 200, "{}")
      end)

      assert :ok =
               OllamaClient.execute("access-token", action, data, plug: {Req.Test, __MODULE__})
    end
  end

  test "API errors do not become successful commands" do
    for {status, expected} <- [
          {400, :invalid_data},
          {401, :unauthorized},
          {403, :forbidden},
          {500, :unavailable}
        ] do
      Req.Test.expect(__MODULE__, fn conn -> Plug.Conn.send_resp(conn, status, "{}") end)

      assert {:error, ^expected} =
               OllamaClient.execute("access-token", :delete, %{"model" => "source"},
                 plug: {Req.Test, __MODULE__}
               )
    end
  end
end
