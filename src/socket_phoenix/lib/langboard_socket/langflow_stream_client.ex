defmodule LangboardSocket.LangflowStreamClient do
  @moduledoc false

  alias LangboardSocket.GraphStreamClient

  def stream(session_id, request, on_event)
      when is_binary(session_id) and session_id != "" and is_map(request) and
             is_function(on_event, 1) do
    with %{"url" => url, "api_key" => api_key, "request_body" => body} <- request,
         true <- is_binary(url) and is_binary(api_key) and is_map(body),
         true <- body["session_id"] == session_id,
         %URI{scheme: scheme, host: host, userinfo: nil, fragment: nil} <- URI.parse(url),
         true <- scheme in ["http", "https"] and is_binary(host) and host != "" do
      GraphStreamClient.stream_http(
        url,
        [{"accept", "application/json"}, {"x-api-key", api_key}],
        body,
        :langflow,
        on_event
      )
    else
      _ -> {:error, :invalid_request}
    end
  end

  def stream(_session_id, _request, _on_event), do: {:error, :invalid_request}
end
