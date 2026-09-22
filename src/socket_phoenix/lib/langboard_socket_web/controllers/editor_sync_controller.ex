defmodule LangboardSocketWeb.EditorSyncController do
  use LangboardSocketWeb, :controller

  alias LangboardSocket.EditorDocument

  @authorization_batch_size 256

  def active(conn, params) do
    with :ok <- enabled(),
         {:ok, names} <- document_names(params),
         {:ok, credentials} <- credentials(conn),
         :ok <- authorize_names(credentials, names, false),
         {:ok, active_names} <- active_names(names) do
      json(conn, %{active_document_names: active_names})
    else
      error -> respond_error(conn, error)
    end
  end

  def text(conn, params) do
    with :ok <- enabled(),
         {:ok, name, field} <- text_params(params),
         :ok <- authorize(conn, name, false),
         {:ok, server} <- EditorDocument.active(name),
         {:ok, value} <- call_document(fn -> EditorDocument.get_text(server, field) end) do
      json(conn, %{value: value})
    else
      error -> respond_error(conn, error)
    end
  end

  def patch_text(conn, params) do
    with :ok <- enabled(),
         {:ok, name, field} <- text_params(params),
         {:ok, value} <- patch_value(params),
         :ok <- authorize(conn, name, true),
         {:ok, server} <- EditorDocument.active(name),
         :ok <- call_document(fn -> EditorDocument.replace_text(server, field, value) end) do
      json(conn, %{})
    else
      error -> respond_error(conn, error)
    end
  end

  def clear(conn, params) do
    with :ok <- enabled(),
         {:ok, names} <- document_names(params),
         {:ok, credentials} <- credentials(conn),
         :ok <- authorize_names(credentials, names, true),
         :ok <- clear_documents(names) do
      json(conn, %{})
    else
      error -> respond_error(conn, error)
    end
  end

  def patch_rich(conn, params) do
    with :ok <- enabled(),
         {:ok, name} <- rich_document_name(params),
         {:ok, value} <- patch_value(params),
         :ok <- authorize(conn, name, true),
         {:ok, server} <- EditorDocument.active(name),
         :ok <- call_document(fn -> EditorDocument.request_rich_patch(server, value) end) do
      json(conn, %{})
    else
      error -> respond_error(conn, error)
    end
  end

  defp rich_document_name(%{"document_name" => name})
       when is_binary(name) and byte_size(name) <= 512 do
    case String.split(name, ":") do
      ["card", uid, "description"] when uid != "" -> {:ok, name}
      ["wiki", uid, "content"] when uid != "" -> {:ok, name}
      _result -> {:error, :invalid_payload}
    end
  end

  defp rich_document_name(_params), do: {:error, :invalid_payload}

  defp enabled do
    if Application.fetch_env!(:langboard_socket, :editor_sync_enabled) and
         Application.fetch_env!(:langboard_socket, :editor_sync_directory) != "" and
         EditorDocument.cluster_ready?(),
       do: :ok,
       else: {:error, :unavailable}
  end

  defp text_params(%{"document_name" => name, "field" => field})
       when is_binary(name) and name != "" and is_binary(field) do
    {:ok, name, field}
  end

  defp text_params(_params), do: {:error, :invalid_payload}

  defp patch_value(%{"value" => value}) when is_binary(value), do: {:ok, value}
  defp patch_value(_params), do: {:error, :invalid_payload}

  defp document_names(%{"document_names" => names}) when is_list(names) do
    max_documents = Application.fetch_env!(:langboard_socket, :editor_sync_max_documents)

    if length(names) <= max_documents and
         Enum.all?(names, &(is_binary(&1) and &1 != "" and byte_size(&1) <= 512)) do
      {:ok, Enum.uniq(names)}
    else
      {:error, :invalid_payload}
    end
  end

  defp document_names(_params), do: {:error, :invalid_payload}

  defp active_names(names) do
    Enum.reduce_while(names, {:ok, []}, fn name, {:ok, active} ->
      case EditorDocument.active(name) do
        {:ok, _server} -> {:cont, {:ok, [name | active]}}
        {:error, :inactive} -> {:cont, {:ok, active}}
        error -> {:halt, error}
      end
    end)
    |> case do
      {:ok, active} -> {:ok, Enum.reverse(active)}
      error -> error
    end
  end

  defp authorize_names(credentials, names, write) do
    auth_client = Application.fetch_env!(:langboard_socket, :authorization_client)
    batches = if names == [], do: [[]], else: Enum.chunk_every(names, @authorization_batch_size)

    Enum.reduce_while(batches, :ok, fn batch, :ok ->
      case auth_client.authorize_editor_http_documents(credentials, batch, write: write) do
        {:ok, true} -> {:cont, :ok}
        {:ok, false} -> {:halt, {:error, :forbidden}}
        {:error, :unauthorized} -> {:halt, {:error, :unauthorized}}
        _result -> {:halt, {:error, :unavailable}}
      end
    end)
  end

  defp clear_documents(names) do
    directory = Application.fetch_env!(:langboard_socket, :editor_sync_directory)

    Enum.reduce_while(names, :ok, fn name, :ok ->
      case EditorDocument.clear_inactive(name, directory) do
        :ok -> {:cont, :ok}
        error -> {:halt, error}
      end
    end)
  end

  defp authorize(conn, name, write) do
    with {:ok, credentials} <- credentials(conn) do
      authorize_credentials(credentials, name, write)
    end
  end

  defp authorize_credentials(credentials, name, write) do
    auth_client = Application.fetch_env!(:langboard_socket, :authorization_client)

    case auth_client.authorize_editor_http_document(credentials, name, write: write) do
      {:ok, true} -> :ok
      {:ok, false} -> {:error, :forbidden}
      {:error, :unauthorized} -> {:error, :unauthorized}
      _result -> {:error, :unavailable}
    end
  end

  defp credentials(conn) do
    case Plug.Conn.get_req_header(conn, "x-api-token") do
      [token] when token != "" ->
        {:ok, {:api_token, token}}

      [] ->
        bearer_credentials(conn)

      _tokens ->
        {:error, :unauthorized}
    end
  end

  defp bearer_credentials(conn) do
    with [authorization] <- Plug.Conn.get_req_header(conn, "authorization"),
         [scheme, token] <- String.split(authorization, " ", parts: 2),
         true <- String.downcase(scheme) == "bearer" and token != "",
         [cookie] when cookie != "" <- Plug.Conn.get_req_header(conn, "cookie") do
      {:ok, {:bearer, token, cookie}}
    else
      _result -> {:error, :unauthorized}
    end
  end

  defp call_document(fun) do
    fun.()
  catch
    :exit, _reason -> {:error, :unavailable}
  end

  defp respond_error(conn, {:error, :invalid_payload}),
    do: conn |> put_status(400) |> json(%{message: "Invalid editor sync payload."})

  defp respond_error(conn, {:error, :unauthorized}), do: conn |> put_status(401) |> json(%{})
  defp respond_error(conn, {:error, :forbidden}), do: conn |> put_status(403) |> json(%{})
  defp respond_error(conn, {:error, :active}), do: conn |> put_status(403) |> json(%{})

  defp respond_error(conn, {:error, :inactive}),
    do: conn |> put_status(409) |> json(%{message: "The collaborative draft is not active."})

  defp respond_error(conn, {:error, reason}) when reason in [:busy, :conflict],
    do:
      conn
      |> put_status(409)
      |> json(%{message: "The collaborative draft changed. Retry the patch."})

  defp respond_error(conn, {:error, :frame_too_large}),
    do:
      conn |> put_status(413) |> json(%{message: "Editor sync request exceeded the size limit."})

  defp respond_error(conn, {:error, :timeout}),
    do:
      conn
      |> put_status(504)
      |> json(%{message: "No editor prepared the collaborative draft in time."})

  defp respond_error(conn, _error),
    do: conn |> put_status(503) |> json(%{message: "Editor sync is unavailable."})
end
