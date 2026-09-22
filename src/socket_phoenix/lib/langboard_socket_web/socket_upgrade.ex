defmodule LangboardSocketWeb.SocketUpgrade do
  @moduledoc false
  @behaviour Plug

  import Plug.Conn

  alias LangboardSocket.EditorDocument
  alias LangboardSocket.RuntimeStatus
  alias LangboardSocketWeb.SocketHandler

  @impl true
  def init(options), do: options

  @impl true
  def call(%Plug.Conn{request_path: path} = conn, _options)
      when path in ["/editor-sync", "/editor-sync/"] do
    if Application.fetch_env!(:langboard_socket, :editor_sync_enabled) and
         websocket_upgrade?(conn) do
      directory = Application.fetch_env!(:langboard_socket, :editor_sync_directory)

      if directory == "" or not RuntimeStatus.ready?() or not EditorDocument.cluster_ready?() do
        conn |> send_resp(503, "") |> halt()
      else
        conn = fetch_query_params(conn)
        token = Map.get(conn.query_params, "authorization")
        max_payload = Application.fetch_env!(:langboard_socket, :socket_max_payload_bytes)
        timeout = Application.fetch_env!(:langboard_socket, :socket_idle_timeout_ms)
        ping_interval = Application.fetch_env!(:langboard_socket, :socket_ping_interval_ms)

        conn
        |> WebSockAdapter.upgrade(
          LangboardSocketWeb.EditorSyncHandler,
          {token, directory, max_payload, ping_interval},
          timeout: timeout,
          max_frame_size: max_payload
        )
        |> halt()
      end
    else
      conn
    end
  end

  @impl true
  def call(%Plug.Conn{request_path: "/"} = conn, _options) do
    if websocket_upgrade?(conn) do
      if RuntimeStatus.ready?() do
        conn = fetch_query_params(conn)
        token = Map.get(conn.query_params, "authorization")
        authorization_client = Application.fetch_env!(:langboard_socket, :authorization_client)
        auth_result = authorization_client.authenticate(token)
        timeout = Application.fetch_env!(:langboard_socket, :socket_idle_timeout_ms)
        max_payload = Application.fetch_env!(:langboard_socket, :socket_max_payload_bytes)
        ping_interval = Application.fetch_env!(:langboard_socket, :socket_ping_interval_ms)

        max_outbound_queue =
          Application.fetch_env!(:langboard_socket, :socket_max_outbound_queue_messages)
          |> positive_integer!(:socket_max_outbound_queue_messages)

        conn
        |> WebSockAdapter.upgrade(
          SocketHandler,
          {auth_result, token, max_payload, ping_interval, max_outbound_queue},
          timeout: timeout,
          max_frame_size: max_payload
        )
        |> halt()
      else
        conn |> send_resp(503, "") |> halt()
      end
    else
      conn
    end
  end

  def call(conn, _options), do: conn

  defp websocket_upgrade?(conn) do
    conn
    |> get_req_header("upgrade")
    |> Enum.any?(&(String.downcase(&1) == "websocket"))
  end

  defp positive_integer!(value, _name) when is_integer(value) and value > 0, do: value

  defp positive_integer!(value, name) do
    raise ArgumentError, "#{name} must be a positive integer, got: #{inspect(value)}"
  end
end
