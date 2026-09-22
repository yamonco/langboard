defmodule LangboardSocket.ChatAvailabilityClient do
  @moduledoc false

  require OpenTelemetry.Tracer, as: Tracer

  def fetch(token, project_uid, request_options \\ [])
      when is_binary(token) and token != "" and is_binary(project_uid) and project_uid != "" do
    base_url = Application.fetch_env!(:langboard_socket, :api_internal_url)

    timeout =
      Application.fetch_env!(:langboard_socket, :graph_timeout_ms) +
        Application.fetch_env!(:langboard_socket, :auth_timeout_ms)

    Tracer.with_span "langboard.socket.chat_availability.request",
      attributes: %{
        "http.request.method" => "GET",
        "http.route" => "/auth/socket/board/{project_uid}/chat/availability"
      } do
      headers = :otel_propagator_text_map.inject([{"authorization", "Bearer " <> token}])

      path =
        "/auth/socket/board/#{URI.encode(project_uid, &URI.char_unreserved?/1)}/chat/availability"

      [
        url: base_url <> path,
        headers: headers,
        retry: false,
        finch: [
          name: LangboardSocket.GraphFinch,
          pool_timeout: timeout,
          receive_timeout: timeout,
          request_timeout: timeout
        ]
      ]
      |> Keyword.merge(request_options)
      |> Req.get()
      |> response()
    end
  end

  defp response({:ok, %Req.Response{status: 200, body: %{"available" => true, "bot" => bot}}})
       when is_map(bot),
       do: {:ok, %{"available" => true, "bot" => bot}}

  defp response({:ok, %Req.Response{status: 200, body: %{"available" => false, "bot" => bot}}})
       when is_nil(bot) or is_map(bot),
       do: {:ok, %{"available" => false, "bot" => bot}}

  defp response({:ok, %Req.Response{status: 401}}), do: {:error, :unauthorized}
  defp response({:ok, %Req.Response{status: 403}}), do: {:error, :forbidden}

  defp response(_result) do
    Tracer.set_status(:error, "chat availability backend unavailable")
    {:error, :unavailable}
  end
end
