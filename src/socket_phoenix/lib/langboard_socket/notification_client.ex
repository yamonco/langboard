defmodule LangboardSocket.NotificationClient do
  @moduledoc false

  require OpenTelemetry.Tracer, as: Tracer

  def execute(token, action, uid, options \\ []) when is_binary(token) and token != "" do
    {method, route, path} = route(action, uid)
    base_url = Application.fetch_env!(:langboard_socket, :api_internal_url)
    timeout = Application.fetch_env!(:langboard_socket, :auth_timeout_ms)

    Tracer.with_span "langboard.socket.notification.command",
      attributes: %{
        "http.request.method" => method |> Atom.to_string() |> String.upcase(),
        "http.route" => route
      } do
      headers = :otel_propagator_text_map.inject([{"authorization", "Bearer " <> token}])

      [
        method: method,
        url: base_url <> path,
        headers: headers,
        retry: false,
        finch: [
          name: LangboardSocket.Finch,
          pool_timeout: timeout,
          receive_timeout: timeout,
          request_timeout: timeout
        ]
      ]
      |> Keyword.merge(options)
      |> Req.request()
      |> response()
    end
  end

  defp route(:read, uid) when is_binary(uid) do
    {:put, "/notifications/{notification_uid}/read",
     "/notifications/#{URI.encode(uid, &URI.char_unreserved?/1)}/read"}
  end

  defp route(:read_all, nil), do: {:put, "/notifications/read-all", "/notifications/read-all"}

  defp route(:delete, uid) when is_binary(uid) do
    {:delete, "/notifications/{notification_uid}",
     "/notifications/#{URI.encode(uid, &URI.char_unreserved?/1)}"}
  end

  defp route(:delete_all, nil), do: {:delete, "/notifications", "/notifications"}

  defp response({:ok, %Req.Response{status: status}}) when status in 200..299, do: :ok
  defp response({:ok, %Req.Response{status: 400}}), do: {:error, :invalid_data}
  defp response({:ok, %Req.Response{status: 401}}), do: {:error, :unauthorized}
  defp response({:ok, %Req.Response{status: 403}}), do: {:error, :forbidden}

  defp response(_result) do
    Tracer.set_status(:error, "notification backend unavailable")
    {:error, :unavailable}
  end
end
