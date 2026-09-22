defmodule LangboardSocket.OllamaClient do
  @moduledoc false

  require OpenTelemetry.Tracer, as: Tracer

  def execute(token, action, data, options \\ []) when is_binary(token) and token != "" do
    {method, path} = route(action)
    timeout = Application.fetch_env!(:langboard_socket, :ollama_timeout_ms)
    base_url = Application.fetch_env!(:langboard_socket, :api_internal_url)

    Tracer.with_span "langboard.socket.ollama.command",
      attributes: %{
        "http.request.method" => method |> Atom.to_string() |> String.upcase(),
        "http.route" => path
      } do
      headers = :otel_propagator_text_map.inject([{"authorization", "Bearer " <> token}])

      [
        method: method,
        url: base_url <> path,
        headers: headers,
        json: data,
        retry: false,
        finch: [
          name: LangboardSocket.OllamaFinch,
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

  defp route(:copy), do: {:post, "/auth/socket/ollama/models/copy"}
  defp route(:delete), do: {:delete, "/auth/socket/ollama/models"}
  defp route(:pull), do: {:post, "/auth/socket/ollama/models/pull"}

  defp response({:ok, %Req.Response{status: status}}) when status in 200..299, do: :ok
  defp response({:ok, %Req.Response{status: 400}}), do: {:error, :invalid_data}
  defp response({:ok, %Req.Response{status: 401}}), do: {:error, :unauthorized}
  defp response({:ok, %Req.Response{status: 403}}), do: {:error, :forbidden}

  defp response(_result) do
    Tracer.set_status(:error, "ollama backend unavailable")
    {:error, :unavailable}
  end
end
