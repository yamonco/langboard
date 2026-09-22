defmodule LangboardSocket.BoardChatRunClient do
  @moduledoc false

  require OpenTelemetry.Tracer, as: Tracer

  defguardp is_non_empty_binary(value) when is_binary(value) and value != ""

  def accept(token, project_uid, command, options \\ [])

  def accept(token, project_uid, command, options)
      when is_non_empty_binary(token) and is_non_empty_binary(project_uid) and is_map(command) do
    path = "/auth/socket/board/#{URI.encode(project_uid, &URI.char_unreserved?/1)}/chat/runs"

    post(token, path, command, "/auth/socket/board/{project_uid}/chat/runs", "accept", options)
    |> accept_response()
  end

  def accept(_token, _project_uid, _command, _options), do: {:error, :invalid_data}

  def cancel(token, project_uid, task_id, options \\ [])

  def cancel(token, project_uid, task_id, options)
      when is_non_empty_binary(token) and is_non_empty_binary(project_uid) and
             is_non_empty_binary(task_id) do
    path = "/auth/socket/board/#{URI.encode(project_uid, &URI.char_unreserved?/1)}/chat/cancel"

    post(
      token,
      path,
      %{task_id: task_id},
      "/auth/socket/board/{project_uid}/chat/cancel",
      "cancel",
      options
    )
    |> cancel_response(task_id)
  end

  def cancel(_token, _project_uid, _task_id, _options), do: {:error, :invalid_data}

  def start(token, project_uid, run_uid, active_documents, options \\ [])

  def start(token, project_uid, run_uid, active_documents, options)
      when is_non_empty_binary(token) and is_non_empty_binary(project_uid) and
             is_non_empty_binary(run_uid) and
             is_list(active_documents) do
    project_path = URI.encode(project_uid, &URI.char_unreserved?/1)
    run_path = URI.encode(run_uid, &URI.char_unreserved?/1)
    path = "/auth/socket/board/#{project_path}/chat/runs/#{run_path}/start"

    post(
      token,
      path,
      %{active_document_names: active_documents},
      "/auth/socket/board/{project_uid}/chat/runs/{run_uid}/start",
      "start",
      options
    )
    |> start_response()
  end

  def start(_token, _project_uid, _run_uid, _active_documents, _options),
    do: {:error, :invalid_data}

  def list_accepted(limit, options \\ [])

  def list_accepted(limit, options)
      when is_integer(limit) and limit > 0 and limit <= 100 and is_list(options) do
    {after_run_uid, request_options} = Keyword.pop(options, :after_run_uid)

    if is_nil(after_run_uid) or is_non_empty_binary(after_run_uid) do
      path = "/auth/socket/board/chat/runs/accepted?limit=#{limit}"

      path =
        if after_run_uid,
          do: path <> "&after_run_uid=#{URI.encode(after_run_uid, &URI.char_unreserved?/1)}",
          else: path

      get(path, "/auth/socket/board/chat/runs/accepted", "accepted_list", request_options)
      |> accepted_list_response()
    else
      {:error, :invalid_data}
    end
  end

  def list_accepted(_limit, _options), do: {:error, :invalid_data}

  def recover_start(project_uid, run_uid, active_documents, options \\ [])

  def recover_start(project_uid, run_uid, active_documents, options)
      when is_non_empty_binary(project_uid) and is_non_empty_binary(run_uid) and
             is_list(active_documents) do
    project_path = URI.encode(project_uid, &URI.char_unreserved?/1)
    run_path = URI.encode(run_uid, &URI.char_unreserved?/1)
    path = "/auth/socket/board/#{project_path}/chat/runs/#{run_path}/recover-start"

    post(
      nil,
      path,
      %{active_document_names: active_documents},
      "/auth/socket/board/{project_uid}/chat/runs/{run_uid}/recover-start",
      "recover_start",
      options
    )
    |> start_response()
  end

  def recover_start(_project_uid, _run_uid, _active_documents, _options),
    do: {:error, :invalid_data}

  def finish(project_uid, run_uid, attempt, status, output_text, error_message, options \\ [])

  def finish(project_uid, run_uid, attempt, status, output_text, error_message, options)
      when is_non_empty_binary(project_uid) and is_non_empty_binary(run_uid) and
             is_integer(attempt) and attempt > 0 and
             status in ["completed", "failed", "cancelled"] and
             is_binary(output_text) and (is_binary(error_message) or is_nil(error_message)) do
    project_path = URI.encode(project_uid, &URI.char_unreserved?/1)
    run_path = URI.encode(run_uid, &URI.char_unreserved?/1)
    path = "/auth/socket/board/#{project_path}/chat/runs/#{run_path}/finish"

    post(
      nil,
      path,
      %{attempt: attempt, status: status, output_text: output_text, error_message: error_message},
      "/auth/socket/board/{project_uid}/chat/runs/{run_uid}/finish",
      "finish",
      options
    )
    |> finish_response(run_uid, attempt, status)
  end

  def finish(_project_uid, _run_uid, _attempt, _status, _output_text, _error_message, _options),
    do: {:error, :invalid_data}

  def renew_lease(project_uid, run_uid, attempt, options \\ [])

  def renew_lease(project_uid, run_uid, attempt, options)
      when is_non_empty_binary(project_uid) and is_non_empty_binary(run_uid) and
             is_integer(attempt) and attempt > 0 do
    renew_lease_for_status(project_uid, run_uid, attempt, "streaming", options)
  end

  def renew_lease(_project_uid, _run_uid, _attempt, _options), do: {:error, :invalid_data}

  def renew_resume_lease(project_uid, run_uid, attempt, options \\ [])

  def renew_resume_lease(project_uid, run_uid, attempt, options)
      when is_non_empty_binary(project_uid) and is_non_empty_binary(run_uid) and
             is_integer(attempt) and attempt > 0 do
    renew_lease_for_status(project_uid, run_uid, attempt, "resuming", options)
  end

  def renew_resume_lease(_project_uid, _run_uid, _attempt, _options),
    do: {:error, :invalid_data}

  defp renew_lease_for_status(project_uid, run_uid, attempt, status, options) do
    project_path = URI.encode(project_uid, &URI.char_unreserved?/1)
    run_path = URI.encode(run_uid, &URI.char_unreserved?/1)
    path = "/auth/socket/board/#{project_path}/chat/runs/#{run_path}/lease"

    post(
      nil,
      path,
      %{attempt: attempt},
      "/auth/socket/board/{project_uid}/chat/runs/{run_uid}/lease",
      "lease",
      options
    )
    |> finish_response(run_uid, attempt, status)
  end

  def pause(project_uid, run_uid, attempt, output_text, interrupt, options \\ [])

  def pause(project_uid, run_uid, attempt, output_text, interrupt, options)
      when is_non_empty_binary(project_uid) and is_non_empty_binary(run_uid) and
             is_integer(attempt) and attempt > 0 and is_binary(output_text) and is_map(interrupt) do
    project_path = URI.encode(project_uid, &URI.char_unreserved?/1)
    run_path = URI.encode(run_uid, &URI.char_unreserved?/1)
    path = "/auth/socket/board/#{project_path}/chat/runs/#{run_path}/pause"

    post(
      nil,
      path,
      %{attempt: attempt, output_text: output_text, interrupt: interrupt},
      "/auth/socket/board/{project_uid}/chat/runs/{run_uid}/pause",
      "pause",
      options
    )
    |> pause_response(run_uid, attempt)
  end

  def pause(_project_uid, _run_uid, _attempt, _output_text, _interrupt, _options),
    do: {:error, :invalid_data}

  def claim_resume(token, project_uid, command, options \\ [])

  def claim_resume(token, project_uid, command, options)
      when is_non_empty_binary(token) and is_non_empty_binary(project_uid) and is_map(command) do
    project_path = URI.encode(project_uid, &URI.char_unreserved?/1)
    path = "/auth/socket/board/#{project_path}/chat/resume/claim"

    post(
      token,
      path,
      command,
      "/auth/socket/board/{project_uid}/chat/resume/claim",
      "resume_claim",
      options
    )
    |> resume_claim_response(command)
  end

  def claim_resume(_token, _project_uid, _command, _options), do: {:error, :invalid_data}

  def complete_resume(
        project_uid,
        run_uid,
        attempt,
        thread_id,
        session_id,
        graph_result,
        options \\ []
      )

  def complete_resume(
        project_uid,
        run_uid,
        attempt,
        thread_id,
        session_id,
        %{response_text: response_text, interrupt: interrupt} = graph_result,
        options
      )
      when is_non_empty_binary(project_uid) and is_non_empty_binary(run_uid) and
             is_integer(attempt) and attempt > 0 and is_non_empty_binary(thread_id) and
             is_non_empty_binary(session_id) and is_binary(response_text) and
             (is_nil(interrupt) or is_map(interrupt)) do
    project_path = URI.encode(project_uid, &URI.char_unreserved?/1)
    run_path = URI.encode(run_uid, &URI.char_unreserved?/1)
    path = "/auth/socket/board/#{project_path}/chat/runs/#{run_path}/resume/result"

    post(
      nil,
      path,
      %{
        attempt: attempt,
        thread_id: thread_id,
        session_id: session_id,
        response_text: response_text,
        interrupt: interrupt
      },
      "/auth/socket/board/{project_uid}/chat/runs/{run_uid}/resume/result",
      "resume_result",
      options
    )
    |> resume_result_response(run_uid, attempt, session_id, graph_result)
  end

  def complete_resume(
        _project_uid,
        _run_uid,
        _attempt,
        _thread_id,
        _session_id,
        _result,
        _options
      ),
      do: {:error, :invalid_data}

  defp post(token, path, body, route, action, options) do
    secret = Application.fetch_env!(:langboard_socket, :internal_api_secret)

    if byte_size(secret) < 32 do
      {:error, :unavailable}
    else
      base_url = Application.fetch_env!(:langboard_socket, :api_internal_url)
      timeout = Application.fetch_env!(:langboard_socket, :auth_timeout_ms)

      Tracer.with_span "langboard.socket.board_chat.#{action}",
        attributes: %{
          "http.request.method" => "POST",
          "http.route" => route
        } do
        headers = [{"x-socket-internal-secret", secret}]
        headers = if token, do: [{"authorization", "Bearer " <> token} | headers], else: headers
        headers = :otel_propagator_text_map.inject(headers)

        [
          url: base_url <> path,
          headers: headers,
          json: body,
          retry: false,
          finch: [
            name: LangboardSocket.Finch,
            pool_timeout: timeout,
            receive_timeout: timeout,
            request_timeout: timeout
          ]
        ]
        |> Keyword.merge(options)
        |> Req.post()
      end
    end
  end

  defp get(path, route, action, options) do
    secret = Application.fetch_env!(:langboard_socket, :internal_api_secret)

    if byte_size(secret) < 32 do
      {:error, :unavailable}
    else
      base_url = Application.fetch_env!(:langboard_socket, :api_internal_url)
      timeout = Application.fetch_env!(:langboard_socket, :auth_timeout_ms)

      Tracer.with_span "langboard.socket.board_chat.#{action}",
        attributes: %{"http.request.method" => "GET", "http.route" => route} do
        headers = :otel_propagator_text_map.inject([{"x-socket-internal-secret", secret}])

        [
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
        |> Req.get()
      end
    end
  end

  defp accepted_list_response({:ok, %Req.Response{status: 200, body: %{"runs" => runs}}})
       when is_list(runs) and length(runs) <= 100 do
    if Enum.all?(runs, fn
         %{
           "run_uid" => run_uid,
           "project_uid" => project_uid,
           "scope_table" => scope_table,
           "scope_uid" => scope_uid
         } ->
           is_non_empty_binary(run_uid) and is_non_empty_binary(project_uid) and
             scope_table in ["project", "card", "project_column", "project_wiki"] and
             (is_nil(scope_uid) or is_non_empty_binary(scope_uid))

         _ ->
           false
       end) do
      {:ok, runs}
    else
      {:error, :unavailable}
    end
  end

  defp accepted_list_response(result), do: error_response(result)

  defp accept_response(
         {:ok,
          %Req.Response{
            status: 200,
            body:
              %{
                "run_uid" => run_uid,
                "status" => status,
                "accepted" => accepted,
                "session" => %{"uid" => session_uid} = session,
                "user_message" =>
                  %{"uid" => message_uid, "chat_session_uid" => message_session_uid} =
                    user_message
              } = body
          }}
       )
       when is_non_empty_binary(run_uid) and is_non_empty_binary(status) and
              is_boolean(accepted) and is_non_empty_binary(session_uid) and
              is_non_empty_binary(message_uid) and
              message_session_uid == session_uid and is_map(session) and
              is_map(user_message),
       do: {:ok, body}

  defp accept_response(result), do: error_response(result)

  defp cancel_response(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{"run_uid" => run_uid, "status" => "cancelled", "task_id" => task_id}
          }},
         task_id
       )
       when is_non_empty_binary(run_uid),
       do: {:ok, run_uid}

  defp cancel_response(result, _task_id), do: error_response(result)

  defp start_response(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{
              "run_uid" => run_uid,
              "attempt" => attempt,
              "graph_request" =>
                %{
                  "session_id" => session_id,
                  "thread_id" => thread_id,
                  "tweaks" => %{
                    "LangboardCalledVariablesComponent" => %{"app_api_token" => graph_token}
                  }
                } = graph_request,
              "ai_message" =>
                %{"uid" => ai_message_uid, "chat_session_uid" => ai_session_uid} = ai_message
            }
          }}
       )
       when is_non_empty_binary(run_uid) and is_integer(attempt) and attempt > 0 and
              is_non_empty_binary(session_id) and is_non_empty_binary(thread_id) and
              is_non_empty_binary(graph_token) and
              is_non_empty_binary(ai_message_uid) and
              ai_session_uid == session_id,
       do:
         {:ok,
          %{
            run_uid: run_uid,
            attempt: attempt,
            graph_request: graph_request,
            ai_message: ai_message
          }}

  defp start_response(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{
              "run_uid" => run_uid,
              "attempt" => attempt,
              "langflow_request" =>
                %{
                  "session_id" => session_id,
                  "thread_id" => thread_id,
                  "url" => url,
                  "api_key" => api_key,
                  "request_body" => %{"session_id" => session_id}
                } = request,
              "ai_message" =>
                %{"uid" => ai_message_uid, "chat_session_uid" => session_id} = ai_message
            }
          }}
       )
       when is_non_empty_binary(run_uid) and is_integer(attempt) and attempt > 0 and
              is_non_empty_binary(session_id) and is_non_empty_binary(thread_id) and
              is_non_empty_binary(url) and is_binary(api_key) and
              is_non_empty_binary(ai_message_uid),
       do:
         {:ok,
          %{
            run_uid: run_uid,
            attempt: attempt,
            langflow_request: request,
            ai_message: ai_message
          }}

  defp start_response(result), do: error_response(result)

  defp finish_response(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{"run_uid" => run_uid, "attempt" => attempt, "status" => status}
          }},
         run_uid,
         attempt,
         status
       ),
       do: :ok

  defp finish_response(result, _run_uid, _attempt, _status), do: error_response(result)

  defp pause_response(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{
              "run_uid" => run_uid,
              "attempt" => attempt,
              "status" => "awaiting_approval",
              "interrupt" => interrupt
            }
          }},
         run_uid,
         attempt
       )
       when is_map(interrupt),
       do: {:ok, interrupt}

  defp pause_response(result, _run_uid, _attempt), do: error_response(result)

  defp resume_claim_response(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{
              "run_uid" => run_uid,
              "attempt" => attempt,
              "thread_id" => thread_id,
              "session_id" => session_id,
              "resume" => %{} = resume
            }
          }},
         %{"thread_id" => thread_id, "session_id" => session_id, "resume" => %{} = decision}
       )
       when is_non_empty_binary(run_uid) and is_integer(attempt) and attempt > 0 and
              is_non_empty_binary(thread_id) and is_non_empty_binary(session_id) do
    if Enum.all?(["approved", "rejected", "instruction", "reason"], fn key ->
         resume[key] == decision[key]
       end) and
         (decision["approved"] != true or
            is_non_empty_binary(resume["app_api_token"])) do
      {:ok,
       %{
         run_uid: run_uid,
         attempt: attempt,
         thread_id: thread_id,
         session_id: session_id,
         resume: resume
       }}
    else
      {:error, :unavailable}
    end
  end

  defp resume_claim_response(result, _command), do: error_response(result)

  defp resume_result_response(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{
              "run_uid" => run_uid,
              "attempt" => attempt,
              "status" => status,
              "newly_applied" => newly_applied,
              "original_message" => %{"uid" => original_uid} = original_message,
              "resumed_message" => resumed_message
            }
          }},
         run_uid,
         attempt,
         session_id,
         graph_result
       )
       when status in ["completed", "awaiting_approval"] and is_boolean(newly_applied) and
              is_non_empty_binary(original_uid) do
    expected_status =
      if is_nil(graph_result.interrupt), do: "completed", else: "awaiting_approval"

    if status == expected_status and original_message["chat_session_uid"] == session_id and
         valid_resumed_message?(resumed_message, session_id, graph_result.interrupt) do
      {:ok,
       %{
         status: status,
         newly_applied: newly_applied,
         original_message: original_message,
         resumed_message: resumed_message
       }}
    else
      {:error, :unavailable}
    end
  end

  defp resume_result_response(result, _run_uid, _attempt, _session_id, _graph_result),
    do: error_response(result)

  defp valid_resumed_message?(nil, _session_id, nil), do: true

  defp valid_resumed_message?(%{"uid" => uid, "chat_session_uid" => session_id}, session_id, nil)
       when is_non_empty_binary(uid),
       do: true

  defp valid_resumed_message?(
         %{
           "uid" => uid,
           "chat_session_uid" => session_id,
           "message" => %{"graph_interrupt" => interrupt}
         },
         session_id,
         expected_interrupt
       )
       when is_non_empty_binary(uid) and is_map(interrupt) and is_map(expected_interrupt),
       do: true

  defp valid_resumed_message?(_message, _session_id, _interrupt), do: false

  defp error_response({:ok, %Req.Response{status: 400}}), do: {:error, :invalid_data}
  defp error_response({:ok, %Req.Response{status: 401}}), do: {:error, :unauthorized}
  defp error_response({:ok, %Req.Response{status: 403}}), do: {:error, :forbidden}
  defp error_response({:ok, %Req.Response{status: 409}}), do: {:error, :conflict}
  defp error_response({:ok, %Req.Response{status: 422}}), do: {:error, :invalid_data}

  defp error_response(_result) do
    Tracer.set_status(:error, "board chat backend unavailable")
    {:error, :unavailable}
  end
end
