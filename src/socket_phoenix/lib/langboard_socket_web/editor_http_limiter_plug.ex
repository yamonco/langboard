defmodule LangboardSocketWeb.EditorHttpLimiterPlug do
  @moduledoc false
  @behaviour Plug

  import Plug.Conn

  def init(options), do: options

  def call(%Plug.Conn{method: "POST", request_path: path} = conn, _options)
      when path in [
             "/editor-sync/active",
             "/editor-sync/clear",
             "/editor-sync/text",
             "/editor-sync/text/patch"
           ] do
    with true <- Application.fetch_env!(:langboard_socket, :editor_sync_enabled),
         :ok <- LangboardSocket.EditorHttpLimiter.acquire() do
      register_before_send(conn, fn conn ->
        :ok = LangboardSocket.EditorHttpLimiter.release()
        conn
      end)
    else
      false ->
        conn
        |> put_resp_content_type("application/json")
        |> send_resp(503, ~s({"message":"Editor sync is unavailable."}))
        |> halt()

      {:error, :overloaded} ->
        conn
        |> put_resp_content_type("application/json")
        |> send_resp(503, ~s({"message":"Too many concurrent editor sync requests."}))
        |> halt()
    end
  end

  def call(conn, _options), do: conn
end
