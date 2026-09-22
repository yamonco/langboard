defmodule LangboardSocket.AuthClient do
  @moduledoc false

  require OpenTelemetry.Tracer, as: Tracer

  alias LangboardSocket.RealtimeContract, as: Contract

  def authenticate(token, options \\ [])

  def authenticate(token, options) when is_binary(token) and token != "" do
    case request(:post, "/auth/socket", token, options) do
      {:ok, %Req.Response{status: 200, body: %{"user_uid" => user_uid}}}
      when is_binary(user_uid) and user_uid != "" ->
        {:ok, user_uid}

      {:ok, %Req.Response{status: 401, body: %{"code" => "AU1004"}}} ->
        {:error, :expired_token}

      {:ok, %Req.Response{status: 401}} ->
        {:error, :unauthorized}

      _ ->
        {:error, :unavailable}
    end
  end

  def authenticate(_token, _options), do: {:error, :unauthorized}

  def authorize_subscriptions(token, topic, topic_ids, options \\ [])

  def authorize_subscriptions(token, topic, topic_ids, options)
      when is_binary(token) and token != "" and is_binary(topic) and is_list(topic_ids) do
    subscriptions = Enum.map(topic_ids, &%{topic: topic, topic_id: &1})

    case request(
           :post,
           "/auth/socket/subscriptions",
           token,
           Keyword.merge([json: %{subscriptions: subscriptions}], options)
         ) do
      {:ok, %Req.Response{status: 200, body: %{"authorized" => authorized}}}
      when is_list(authorized) ->
        requested_ids = MapSet.new(topic_ids)

        authorized_ids =
          for %{"topic" => ^topic, "topic_id" => topic_id} <- authorized,
              is_binary(topic_id),
              MapSet.member?(requested_ids, topic_id),
              uniq: true,
              do: topic_id

        {:ok, authorized_ids}

      {:ok, %Req.Response{status: 401, body: %{"code" => "AU1004"}}} ->
        {:error, :expired_token}

      {:ok, %Req.Response{status: 401}} ->
        {:error, :unauthorized}

      _ ->
        {:error, :unavailable}
    end
  end

  def authorize_subscriptions(_token, _topic, _topic_ids, _options), do: {:error, :unauthorized}

  def authorize_editor_document(token, document_name, options \\ [])

  def authorize_editor_document(token, document_name, options)
      when is_binary(token) and token != "" and is_binary(document_name) and
             document_name != "" do
    :post
    |> request(
      "/auth/socket/editor-document",
      token,
      options
      |> Keyword.put(:json, %{document_name: document_name})
      |> Keyword.put(:response_validator, &valid_editor_authorization_response?/1)
    )
    |> editor_authorization_result()
  end

  def authorize_editor_document(_token, _document_name, _options),
    do: {:error, :unauthorized}

  defp editor_authorization_result(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{"authorized" => true, "user_name" => name, "writable" => writable}
          }}
       )
       when is_binary(name) and name != "" and is_boolean(writable),
       do: {:ok, name, writable}

  defp editor_authorization_result(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{"authorized" => false, "user_name" => nil, "writable" => false}
          }}
       ),
       do: {:error, :forbidden}

  defp editor_authorization_result({:ok, %Req.Response{status: 401}}),
    do: {:error, :unauthorized}

  defp editor_authorization_result(_result), do: {:error, :unavailable}

  def authorize_editor_http_document(credentials, document_name, options \\ [])

  def authorize_editor_http_document({:api_token, token}, document_name, options)
      when is_binary(token) and token != "" and is_binary(document_name) and
             document_name != "" do
    headers = [{"x-api-token", token}]
    {write, options} = Keyword.pop(options, :write, false)

    authorize_document_request(
      "/auth/socket/editor-http-document",
      document_name,
      write,
      Keyword.put(options, :request_headers, headers)
    )
  end

  def authorize_editor_http_document({:bearer, token, cookie}, document_name, options)
      when is_binary(token) and token != "" and is_binary(cookie) and cookie != "" and
             is_binary(document_name) and document_name != "" do
    headers = [{"authorization", "Bearer " <> token}, {"cookie", cookie}]
    {write, options} = Keyword.pop(options, :write, false)

    authorize_document_request(
      "/auth/socket/editor-http-document",
      document_name,
      write,
      Keyword.put(options, :request_headers, headers)
    )
  end

  def authorize_editor_http_document(_credentials, _document_name, _options),
    do: {:error, :unauthorized}

  def authorize_editor_http_documents(credentials, document_names, options \\ [])

  def authorize_editor_http_documents({:api_token, token}, document_names, options)
      when is_binary(token) and token != "" and is_list(document_names) do
    {write, options} = Keyword.pop(options, :write, false)

    authorize_documents_request(
      document_names,
      write,
      Keyword.put(options, :request_headers, [{"x-api-token", token}])
    )
  end

  def authorize_editor_http_documents({:bearer, token, cookie}, document_names, options)
      when is_binary(token) and token != "" and is_binary(cookie) and cookie != "" and
             is_list(document_names) do
    headers = [{"authorization", "Bearer " <> token}, {"cookie", cookie}]
    {write, options} = Keyword.pop(options, :write, false)

    authorize_documents_request(
      document_names,
      write,
      Keyword.put(options, :request_headers, headers)
    )
  end

  def authorize_editor_http_documents(_credentials, _document_names, _options),
    do: {:error, :unauthorized}

  defp authorize_documents_request(document_names, write, options) do
    case request(
           :post,
           "/auth/socket/editor-http-documents",
           nil,
           Keyword.merge([json: %{document_names: document_names, write: write}], options)
         ) do
      {:ok, %Req.Response{status: 200, body: %{"authorized" => authorized}}}
      when is_boolean(authorized) ->
        {:ok, authorized}

      {:ok, %Req.Response{status: 401}} ->
        {:error, :unauthorized}

      _result ->
        {:error, :unavailable}
    end
  end

  defp authorize_document_request(path, document_name, write, options) do
    case request(
           :post,
           path,
           nil,
           Keyword.merge([json: %{document_name: document_name, write: write}], options)
         ) do
      {:ok, %Req.Response{status: 200, body: %{"authorized" => authorized}}}
      when is_boolean(authorized) ->
        {:ok, authorized}

      {:ok, %Req.Response{status: 401}} ->
        {:error, :unauthorized}

      _result ->
        {:error, :unavailable}
    end
  end

  def ready?(options \\ []) do
    {secret, options} =
      Keyword.pop_lazy(options, :internal_secret, fn ->
        Application.fetch_env!(:langboard_socket, :internal_api_secret)
      end)

    if is_binary(secret) and byte_size(secret) >= 32 do
      path = Contract.internal_api_capabilities_path!()
      expected_version = Contract.internal_api_contract_version!()

      match?(
        {:ok,
         %Req.Response{
           status: 200,
           body: %{"contract_version" => ^expected_version}
         }},
        request(
          :get,
          path,
          nil,
          options
          |> Keyword.put(:request_headers, [{"x-socket-internal-secret", secret}])
          |> Keyword.put(:response_validator, &valid_internal_api_contract_response?/1)
        )
      )
    else
      false
    end
  end

  defp valid_internal_api_contract_response?(%Req.Response{
         status: 200,
         body: %{"contract_version" => version}
       }),
       do: version == Contract.internal_api_contract_version!()

  defp valid_internal_api_contract_response?(_response), do: false

  defp valid_editor_authorization_response?(%Req.Response{
         status: 200,
         body: %{"authorized" => true, "user_name" => name, "writable" => writable}
       })
       when is_binary(name) and name != "" and is_boolean(writable),
       do: true

  defp valid_editor_authorization_response?(%Req.Response{
         status: 200,
         body: %{"authorized" => false, "user_name" => nil, "writable" => false}
       }),
       do: true

  defp valid_editor_authorization_response?(_response), do: false

  defp request(method, path, token, options) do
    base_url = Application.fetch_env!(:langboard_socket, :api_internal_url)
    timeout = Application.fetch_env!(:langboard_socket, :auth_timeout_ms)

    Tracer.with_span "langboard.socket.auth.request",
      attributes: %{
        "http.request.method" => method |> Atom.to_string() |> String.upcase(),
        "http.route" => path
      } do
      {request_headers, options} = Keyword.pop(options, :request_headers)

      {response_validator, options} =
        Keyword.pop(options, :response_validator, &successful_response?/1)

      headers =
        request_headers || if(token, do: [{"authorization", "Bearer " <> token}], else: [])

      headers = :otel_propagator_text_map.inject(headers)

      request_options = [
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

      started_at = System.monotonic_time()

      result =
        request_options
        |> Kernel.++(options)
        |> Req.request()

      duration = System.monotonic_time() - started_at

      :telemetry.execute(
        [:langboard_socket, :authorization, :request],
        %{
          count: 1,
          duration_microseconds: System.convert_time_unit(duration, :native, :microsecond)
        },
        %{route: path, result: telemetry_result(result, response_validator)}
      )

      record_result(result)
    end
  end

  defp successful_response?(%Req.Response{status: status}), do: status in 200..299

  defp telemetry_result({:ok, %Req.Response{status: status} = response}, response_validator)
       when status in 200..299 do
    if response_validator.(response), do: :success, else: :invalid_response
  end

  defp telemetry_result({:ok, %Req.Response{status: status}}, _response_validator)
       when status in 400..499,
       do: :client_error

  defp telemetry_result({:ok, %Req.Response{status: status}}, _response_validator)
       when status in 500..599,
       do: :server_error

  defp telemetry_result({:ok, %Req.Response{}}, _response_validator), do: :unexpected_status
  defp telemetry_result({:error, _reason}, _response_validator), do: :transport_error

  defp record_result({:ok, %Req.Response{status: status}} = result) do
    Tracer.set_attribute("http.response.status_code", status)

    if status >= 500 do
      Tracer.set_status(:error, "authorization backend error")
    end

    result
  end

  defp record_result({:error, _reason} = result) do
    Tracer.set_status(:error, "authorization backend unavailable")
    result
  end
end
