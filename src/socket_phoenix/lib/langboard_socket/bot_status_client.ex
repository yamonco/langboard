defmodule LangboardSocket.BotStatusClient do
  @moduledoc false

  require OpenTelemetry.Tracer, as: Tracer

  @empty_status_map %{"project_column" => %{}, "card" => %{}}

  def fetch(project_uid, request_options \\ [])
      when is_binary(project_uid) and project_uid != "" do
    base_url = Application.fetch_env!(:langboard_socket, :graph_internal_url)
    timeout = Application.fetch_env!(:langboard_socket, :graph_timeout_ms)

    Tracer.with_span "langboard.socket.bot_status.request",
      attributes: %{"http.request.method" => "GET", "http.route" => "/bot/status/map"} do
      [
        url: base_url <> "/bot/status/map",
        params: [project_uid: project_uid],
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

  defp response({:ok, %Req.Response{status: 200, body: %{"status_map" => status_map}}})
       when is_map(status_map),
       do: {:ok, Map.merge(@empty_status_map, status_map)}

  defp response({:error, %Req.TransportError{reason: :econnrefused}}),
    do: {:ok, @empty_status_map}

  defp response(_result) do
    Tracer.set_status(:error, "bot status backend unavailable")
    {:error, :unavailable}
  end
end
