defmodule LangboardSocket.EditorRunClient do
  @moduledoc false

  require OpenTelemetry.Tracer, as: Tracer

  defguardp is_non_empty_binary(value) when is_binary(value) and value != ""

  @base_path "/auth/socket/editor-ai"

  def accept(token, command, options \\ [])

  def accept(token, command, options)
      when is_non_empty_binary(token) and is_map(command) do
    post(token, @base_path <> "/runs", command, "accept", options)
    |> accept_response()
  end

  def accept(_token, _command, _options), do: {:error, :invalid_data}

  def cancel(token, project_uid, kind, task_id, options \\ [])

  def cancel(token, project_uid, kind, task_id, options)
      when is_non_empty_binary(token) and is_non_empty_binary(project_uid) and
             kind in ["editor_chat", "editor_copilot"] and
             is_non_empty_binary(task_id) do
    post(
      token,
      @base_path <> "/cancel",
      %{project_uid: project_uid, kind: kind, task_id: task_id},
      "cancel",
      options
    )
    |> cancel_response(task_id)
  end

  def cancel(_token, _project_uid, _kind, _task_id, _options), do: {:error, :invalid_data}

  def status(token, project_uid, kind, task_id, options \\ [])

  def status(token, project_uid, kind, task_id, options)
      when is_non_empty_binary(token) and is_non_empty_binary(project_uid) and
             kind in ["editor_chat", "editor_copilot"] and
             is_non_empty_binary(task_id) do
    post(
      token,
      @base_path <> "/status",
      %{project_uid: project_uid, kind: kind, task_id: task_id},
      "status",
      options
    )
    |> status_response(task_id, kind)
  end

  def status(_token, _project_uid, _kind, _task_id, _options), do: {:error, :invalid_data}

  def list_accepted(limit, options \\ [])

  def list_accepted(limit, options)
      when is_integer(limit) and limit > 0 and limit <= 100 and is_list(options) do
    {after_run_uid, request_options} = Keyword.pop(options, :after_run_uid)

    if is_nil(after_run_uid) or is_non_empty_binary(after_run_uid) do
      path = @base_path <> "/runs/accepted?limit=#{limit}"

      path =
        if after_run_uid,
          do: path <> "&after_run_uid=#{URI.encode(after_run_uid, &URI.char_unreserved?/1)}",
          else: path

      get(path, "accepted_list", request_options) |> accepted_list_response()
    else
      {:error, :invalid_data}
    end
  end

  def list_accepted(_limit, _options), do: {:error, :invalid_data}

  def start(run_uid, options \\ [])

  def start(run_uid, options) when is_non_empty_binary(run_uid) do
    post(nil, run_path(run_uid) <> "/start", %{}, "start", options)
    |> start_response(run_uid)
  end

  def start(_run_uid, _options), do: {:error, :invalid_data}

  def finish(run_uid, attempt, status, output_text, error_message, options \\ [])

  def finish(run_uid, attempt, status, output_text, error_message, options)
      when is_non_empty_binary(run_uid) and is_integer(attempt) and attempt > 0 and
             status in ["completed", "failed", "cancelled"] and is_binary(output_text) and
             (is_binary(error_message) or is_nil(error_message)) do
    post(
      nil,
      run_path(run_uid) <> "/finish",
      %{attempt: attempt, status: status, output_text: output_text, error_message: error_message},
      "finish",
      options
    )
    |> status_response(run_uid, attempt, status)
  end

  def finish(_run_uid, _attempt, _status, _output_text, _error_message, _options),
    do: {:error, :invalid_data}

  def pause(run_uid, attempt, output_text, interrupt, options \\ [])

  def pause(run_uid, attempt, output_text, interrupt, options)
      when is_non_empty_binary(run_uid) and is_integer(attempt) and attempt > 0 and
             is_binary(output_text) and is_map(interrupt) do
    post(
      nil,
      run_path(run_uid) <> "/pause",
      %{attempt: attempt, output_text: output_text, interrupt: interrupt},
      "pause",
      options
    )
    |> pause_response(run_uid, attempt)
  end

  def pause(_run_uid, _attempt, _output_text, _interrupt, _options),
    do: {:error, :invalid_data}

  def renew_lease(run_uid, attempt, options \\ [])

  def renew_lease(run_uid, attempt, options)
      when is_non_empty_binary(run_uid) and is_integer(attempt) and attempt > 0 do
    post(nil, run_path(run_uid) <> "/lease", %{attempt: attempt}, "lease", options)
    |> status_response(run_uid, attempt, "streaming")
  end

  def renew_lease(_run_uid, _attempt, _options), do: {:error, :invalid_data}

  def claim_resume(token, project_uid, approval_uid, decision, options \\ [])

  def claim_resume(token, project_uid, approval_uid, decision, options)
      when is_non_empty_binary(token) and is_non_empty_binary(project_uid) and
             is_non_empty_binary(approval_uid) and
             is_map(decision) do
    path =
      @base_path <> "/approvals/" <> URI.encode(approval_uid, &URI.char_unreserved?/1) <> "/claim"

    post(token, path, %{project_uid: project_uid, resume: decision}, "resume_claim", options)
    |> resume_claim_response(decision)
  end

  def claim_resume(_token, _project_uid, _approval_uid, _decision, _options),
    do: {:error, :invalid_data}

  def complete_resume(run_uid, attempt, thread_id, session_id, graph_result, options \\ [])

  def complete_resume(
        run_uid,
        attempt,
        thread_id,
        session_id,
        %{response_text: response_text, interrupt: interrupt},
        options
      )
      when is_non_empty_binary(run_uid) and is_integer(attempt) and attempt > 0 and
             is_non_empty_binary(thread_id) and is_non_empty_binary(session_id) and
             is_binary(response_text) and
             (is_map(interrupt) or is_nil(interrupt)) do
    post(
      nil,
      run_path(run_uid) <> "/resume/result",
      %{
        attempt: attempt,
        thread_id: thread_id,
        session_id: session_id,
        response_text: response_text,
        interrupt: interrupt
      },
      "resume_result",
      options
    )
    |> resume_result_response(run_uid, attempt)
  end

  def complete_resume(_run_uid, _attempt, _thread_id, _session_id, _graph_result, _options),
    do: {:error, :invalid_data}

  def renew_resume_lease(run_uid, attempt, options \\ [])

  def renew_resume_lease(run_uid, attempt, options)
      when is_non_empty_binary(run_uid) and is_integer(attempt) and attempt > 0 do
    post(nil, run_path(run_uid) <> "/resume/lease", %{attempt: attempt}, "resume_lease", options)
    |> status_response(run_uid, attempt, "resuming")
  end

  def renew_resume_lease(_run_uid, _attempt, _options), do: {:error, :invalid_data}

  defp run_path(run_uid),
    do: @base_path <> "/runs/" <> URI.encode(run_uid, &URI.char_unreserved?/1)

  defp post(token, path, body, action, options) do
    secret = Application.fetch_env!(:langboard_socket, :internal_api_secret)

    if byte_size(secret) < 32 do
      {:error, :unavailable}
    else
      base_url = Application.fetch_env!(:langboard_socket, :api_internal_url)
      timeout = Application.fetch_env!(:langboard_socket, :auth_timeout_ms)

      Tracer.with_span "langboard.socket.editor_ai.#{action}",
        attributes: %{"http.request.method" => "POST", "http.route" => @base_path} do
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

  defp get(path, action, options) do
    secret = Application.fetch_env!(:langboard_socket, :internal_api_secret)

    if byte_size(secret) < 32 do
      {:error, :unavailable}
    else
      base_url = Application.fetch_env!(:langboard_socket, :api_internal_url)
      timeout = Application.fetch_env!(:langboard_socket, :auth_timeout_ms)

      Tracer.with_span "langboard.socket.editor_ai.#{action}",
        attributes: %{"http.request.method" => "GET", "http.route" => @base_path} do
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
           "task_id" => task_id,
           "kind" => kind
         } ->
           is_non_empty_binary(run_uid) and is_non_empty_binary(project_uid) and
             is_non_empty_binary(task_id) and
             kind in ["editor_chat", "editor_copilot"]

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
            body: %{"run_uid" => run_uid, "status" => status, "accepted" => accepted} = body
          }}
       )
       when is_non_empty_binary(run_uid) and
              status in ["accepted", "streaming", "completed", "failed", "cancelled", "uncertain"] and
              is_boolean(accepted),
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

  defp status_response(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{
              "run_uid" => run_uid,
              "task_id" => response_task_id,
              "kind" => response_kind,
              "status" => status,
              "attempt" => attempt,
              "output_text" => output_text,
              "error_message" => error_message
            }
          } = response},
         task_id,
         kind
       )
       when is_non_empty_binary(run_uid) and response_task_id == task_id and
              response_kind == kind and
              status in [
                "accepted",
                "streaming",
                "awaiting_approval",
                "resuming",
                "completed",
                "failed",
                "cancelled",
                "uncertain"
              ] and
              is_integer(attempt) and attempt >= 0 and is_binary(output_text) and
              (is_binary(error_message) or is_nil(error_message)),
       do: {:ok, response.body}

  defp status_response(result, _task_id, _kind), do: error_response(result)

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
                  "input_value" => input_value,
                  "tweaks" => %{
                    "LangboardCalledVariablesComponent" => %{"app_api_token" => graph_token}
                  }
                } = graph_request
            }
          }},
         run_uid
       )
       when is_integer(attempt) and attempt > 0 and is_non_empty_binary(session_id) and
              is_non_empty_binary(thread_id) and
              is_non_empty_binary(input_value) and is_non_empty_binary(graph_token),
       do: {:ok, %{run_uid: run_uid, attempt: attempt, graph_request: graph_request}}

  defp start_response(result, _run_uid), do: error_response(result)

  defp status_response(
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

  defp status_response(result, _run_uid, _attempt, _status), do: error_response(result)

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
              "resume" => resume
            }
          }},
         decision
       )
       when is_non_empty_binary(run_uid) and is_integer(attempt) and attempt > 0 and
              is_non_empty_binary(thread_id) and is_non_empty_binary(session_id) and
              is_map(resume) do
    same_decision? = Enum.all?(decision, fn {key, value} -> resume[key] == value end)
    approved? = decision["approved"] == true
    token = resume["app_api_token"]

    if same_decision? and (not approved? or is_non_empty_binary(token)) do
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

  defp resume_claim_response(result, _decision), do: error_response(result)

  defp resume_result_response(
         {:ok,
          %Req.Response{
            status: 200,
            body: %{
              "run_uid" => run_uid,
              "attempt" => attempt,
              "status" => status,
              "newly_applied" => newly_applied,
              "output_text" => output_text
            }
          }},
         run_uid,
         attempt
       )
       when status in ["completed", "awaiting_approval"] and is_boolean(newly_applied) and
              is_binary(output_text),
       do: {:ok, %{status: status, newly_applied: newly_applied, output_text: output_text}}

  defp resume_result_response(result, _run_uid, _attempt), do: error_response(result)

  defp error_response({:ok, %Req.Response{status: 400}}), do: {:error, :invalid_data}
  defp error_response({:ok, %Req.Response{status: 401}}), do: {:error, :unauthorized}
  defp error_response({:ok, %Req.Response{status: 403}}), do: {:error, :forbidden}
  defp error_response({:ok, %Req.Response{status: 409}}), do: {:error, :conflict}
  defp error_response({:ok, %Req.Response{status: 422}}), do: {:error, :invalid_data}

  defp error_response(_result) do
    Tracer.set_status(:error, "editor AI backend unavailable")
    {:error, :unavailable}
  end
end
