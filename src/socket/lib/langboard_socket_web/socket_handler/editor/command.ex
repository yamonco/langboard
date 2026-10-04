defmodule LangboardSocketWeb.SocketHandler.Editor.Command do
  @moduledoc false

  alias LangboardSocket.Editor.ResumeWorker
  alias LangboardSocket.Editor.RunClient
  alias LangboardSocket.Editor.RunWorker
  alias LangboardSocket.RealtimeContract, as: Contract

  @editor_status_event Contract.event!("editor_ai_status")
  @editor_approval_resume_event Contract.event!("editor_approval_resume")
  @notification_topic Contract.topic!("none")
  @notification_topic_id Contract.topic_id!("none")
  @task_id_pattern ~r/\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\z/
  @editor_send_commands %{
    Contract.event!("editor_card_chat_send") => %{
      kind: "editor_chat",
      scope_field: "card_uid",
      document_type: "card",
      output: Contract.event!("editor_card_chat_stream")
    },
    Contract.event!("editor_card_copilot_send") => %{
      kind: "editor_copilot",
      scope_field: "card_uid",
      document_type: "card",
      output: Contract.event!("editor_card_copilot_receive")
    },
    Contract.event!("editor_wiki_chat_send") => %{
      kind: "editor_chat",
      scope_field: "wiki_uid",
      document_type: "wiki",
      output: Contract.event!("editor_wiki_chat_stream")
    },
    Contract.event!("editor_wiki_copilot_send") => %{
      kind: "editor_copilot",
      scope_field: "wiki_uid",
      document_type: "wiki",
      output: Contract.event!("editor_wiki_copilot_receive")
    }
  }
  @editor_abort_commands %{
    Contract.event!("editor_card_chat_abort") => Contract.event!("editor_card_chat_send"),
    Contract.event!("editor_card_copilot_abort") => Contract.event!("editor_card_copilot_send"),
    Contract.event!("editor_wiki_chat_abort") => Contract.event!("editor_wiki_chat_send"),
    Contract.event!("editor_wiki_copilot_abort") => Contract.event!("editor_wiki_copilot_send")
  }

  def handle(event, payload, state, capacity_exhausted?) do
    if Application.get_env(:langboard_socket, :editor_ai_enabled, false) do
      cond do
        event == @editor_status_event ->
          handle_editor_status(payload, state, capacity_exhausted?)

        Map.has_key?(@editor_send_commands, event) ->
          handle_editor_send(
            payload,
            Map.fetch!(@editor_send_commands, event),
            state,
            capacity_exhausted?
          )

        Map.has_key?(@editor_abort_commands, event) ->
          handle_editor_abort(
            payload,
            Map.fetch!(@editor_abort_commands, event),
            state,
            capacity_exhausted?
          )

        event == @editor_approval_resume_event ->
          handle_editor_approval_resume(payload, state, capacity_exhausted?)

        true ->
          {:ok, state}
      end
    else
      {:ok, state}
    end
  end

  defp handle_editor_send(
         %{
           "event" => event,
           "topic" => @notification_topic,
           "topic_id" => @notification_topic_id,
           "data" => data
         },
         route,
         state,
         capacity_exhausted?
       )
       when is_map(data) do
    task_id = data["task_id"]

    cond do
      not valid_editor_send?(data, route) ->
        {:stop, :normal, Contract.close_code!("invalid_data"), state}

      Map.has_key?(state.pending_editor_runs, task_id) ->
        {:ok, state}

      capacity_exhausted? ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}

      true ->
        command = editor_command(data, route)
        worker = Application.get_env(:langboard_socket, :editor_run_worker, RunWorker)
        options = [token: state.authorization_token, command: command, receiver: self()]

        case DynamicSupervisor.start_child(
               LangboardSocket.EditorRunSupervisor,
               {worker, options}
             ) do
          {:ok, worker_pid} ->
            monitor_ref = Process.monitor(worker_pid)

            pending = %{
              pid: worker_pid,
              monitor: monitor_ref,
              project_uid: command["project_uid"],
              event: event,
              kind: route.kind,
              output: route.output,
              outcome: false
            }

            {:ok,
             %{
               state
               | pending_editor_runs: Map.put(state.pending_editor_runs, task_id, pending)
             }}

          {:error, _reason} ->
            {:stop, :normal, Contract.close_code!("try_again_later"), state}
        end
    end
  end

  defp handle_editor_send(_payload, _route, state, _capacity_exhausted?),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp handle_editor_abort(
         %{
           "topic" => @notification_topic,
           "topic_id" => @notification_topic_id,
           "data" => %{"task_id" => task_id, "project_uid" => project_uid}
         },
         send_event,
         state,
         capacity_exhausted?
       )
       when is_binary(task_id) and is_binary(project_uid) do
    if String.match?(task_id, @task_id_pattern) and Contract.valid_short_uid?(project_uid) do
      route = Map.fetch!(@editor_send_commands, send_event)

      case Map.get(state.pending_editor_runs, task_id) do
        %{event: ^send_event, project_uid: ^project_uid, pid: worker_pid} ->
          send(worker_pid, {:editor_abort_requested, task_id})
          {:ok, state}

        nil ->
          start_editor_cancel(project_uid, route.kind, task_id, state, capacity_exhausted?)

        _other ->
          {:stop, :normal, Contract.close_code!("invalid_data"), state}
      end
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_editor_abort(_payload, _send_event, state, _capacity_exhausted?),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp start_editor_cancel(project_uid, kind, task_id, state, capacity_exhausted?) do
    owner = self()
    reference = make_ref()
    token = state.authorization_token
    client = Application.get_env(:langboard_socket, :editor_run_client, RunClient)

    with false <- capacity_exhausted?,
         {:ok, worker_pid} <-
           Task.Supervisor.start_child(LangboardSocket.CommandTaskSupervisor, fn ->
             result = client.cancel(token, project_uid, kind, task_id)
             send(owner, {:editor_cancel, reference, self(), task_id, result})
           end) do
      monitor_ref = Process.monitor(worker_pid)

      {:ok,
       %{
         state
         | pending_editor_cancels:
             Map.put(state.pending_editor_cancels, reference, {worker_pid, monitor_ref})
       }}
    else
      _result -> {:stop, :normal, Contract.close_code!("try_again_later"), state}
    end
  end

  defp handle_editor_status(
         %{
           "topic" => @notification_topic,
           "topic_id" => @notification_topic_id,
           "data" => %{
             "task_id" => task_id,
             "project_uid" => project_uid,
             "kind" => kind
           }
         },
         state,
         capacity_exhausted?
       )
       when is_binary(task_id) and is_binary(project_uid) and is_binary(kind) do
    if valid_editor_status?(task_id, project_uid, kind) do
      start_editor_status(task_id, project_uid, kind, state, capacity_exhausted?)
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_editor_status(_payload, state, _capacity_exhausted?),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp valid_editor_status?(task_id, project_uid, kind) do
    String.match?(task_id, @task_id_pattern) and Contract.valid_short_uid?(project_uid) and
      kind in ["editor_chat", "editor_copilot"]
  end

  defp start_editor_status(task_id, project_uid, kind, state, capacity_exhausted?) do
    cond do
      Map.has_key?(state.pending_editor_statuses, task_id) ->
        {:ok, state}

      capacity_exhausted? ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}

      true ->
        owner = self()
        token = state.authorization_token
        client = Application.get_env(:langboard_socket, :editor_run_client, RunClient)

        fetch_status = fn ->
          send(
            owner,
            {:editor_status, task_id, self(), client.status(token, project_uid, kind, task_id)}
          )
        end

        case Task.Supervisor.start_child(LangboardSocket.CommandTaskSupervisor, fetch_status) do
          {:ok, worker_pid} ->
            monitor_ref = Process.monitor(worker_pid)

            {:ok,
             %{
               state
               | pending_editor_statuses:
                   Map.put(state.pending_editor_statuses, task_id, {worker_pid, monitor_ref})
             }}

          {:error, _reason} ->
            {:stop, :normal, Contract.close_code!("try_again_later"), state}
        end
    end
  end

  defp handle_editor_approval_resume(
         %{
           "topic" => @notification_topic,
           "topic_id" => @notification_topic_id,
           "data" => %{
             "approval_uid" => approval_uid,
             "project_uid" => project_uid,
             "resume" => decision
           }
         },
         state,
         capacity_exhausted?
       ) do
    cond do
      not (Contract.valid_short_uid?(approval_uid) and Contract.valid_short_uid?(project_uid) and
               valid_editor_approval_decision?(decision)) ->
        {:stop, :normal, Contract.close_code!("invalid_data"), state}

      Map.has_key?(state.pending_editor_resumes, approval_uid) ->
        {:ok, state}

      capacity_exhausted? ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}

      true ->
        worker =
          Application.get_env(:langboard_socket, :editor_resume_worker, ResumeWorker)

        options = [
          token: state.authorization_token,
          project_uid: project_uid,
          approval_uid: approval_uid,
          decision: decision,
          receiver: self()
        ]

        case DynamicSupervisor.start_child(
               LangboardSocket.EditorRunSupervisor,
               {worker, options}
             ) do
          {:ok, worker_pid} ->
            monitor_ref = Process.monitor(worker_pid)

            pending = %{
              pid: worker_pid,
              monitor: monitor_ref,
              outcome: false
            }

            {:ok,
             %{
               state
               | pending_editor_resumes:
                   Map.put(state.pending_editor_resumes, approval_uid, pending)
             }}

          {:error, _reason} ->
            {:stop, :normal, Contract.close_code!("try_again_later"), state}
        end
    end
  end

  defp handle_editor_approval_resume(_payload, state, _capacity_exhausted?),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp valid_editor_approval_decision?(
         %{"approved" => approved, "rejected" => rejected} = decision
       ) do
    map_size(decision) in 2..3 and
      Enum.all?(Map.keys(decision), &(&1 in ["approved", "rejected", "reason"])) and
      is_boolean(approved) and is_boolean(rejected) and
      approved != rejected and
      (not Map.has_key?(decision, "reason") or
         (rejected and is_binary(decision["reason"]) and byte_size(decision["reason"]) <= 1000))
  end

  defp valid_editor_approval_decision?(_decision), do: false

  defp valid_editor_send?(data, route) do
    task_id = Map.get(data, "task_id")
    project_uid = Map.get(data, "project_uid")
    scope_uid = Map.get(data, route.scope_field)
    document_name = Map.get(data, "document_name")
    system = Map.get(data, "system", "")

    is_binary(task_id) and String.match?(task_id, @task_id_pattern) and
      Contract.valid_short_uid?(project_uid) and Contract.valid_short_uid?(scope_uid) and
      valid_editor_document_name?(document_name, route.document_type, scope_uid) and
      is_binary(system) and byte_size(system) <= 65_536 and
      is_nil(Map.get(data, "file_path")) and valid_editor_input?(data, route.kind)
  end

  defp valid_editor_document_name?(name, type, scope_uid)
       when is_binary(name) and byte_size(name) in 1..512,
       do: String.starts_with?(name, "#{type}:#{scope_uid}:")

  defp valid_editor_document_name?(_name, _type, _scope_uid), do: false

  defp valid_editor_input?(data, "editor_chat") do
    messages = Map.get(data, "messages")

    is_nil(Map.get(data, "prompt")) and is_list(messages) and length(messages) in 1..100 and
      Enum.all?(messages, fn
        %{"role" => role, "content" => content} ->
          role in ["system", "user", "assistant"] and is_binary(content) and
            byte_size(content) <= 65_536

        _ ->
          false
      end) and
      Enum.reduce(messages, 0, fn message, total -> total + byte_size(message["content"]) end) <=
        65_536
  end

  defp valid_editor_input?(data, "editor_copilot") do
    prompt = Map.get(data, "prompt")
    is_nil(Map.get(data, "messages")) and is_binary(prompt) and byte_size(prompt) in 1..65_536
  end

  defp editor_command(data, route) do
    base = %{
      "task_id" => data["task_id"],
      "project_uid" => data["project_uid"],
      "scope_uid" => data[route.scope_field],
      "document_name" => data["document_name"],
      "kind" => route.kind,
      "system" => Map.get(data, "system", "")
    }

    case route.kind do
      "editor_chat" ->
        Map.put(base, "messages", Enum.map(data["messages"], &Map.take(&1, ["role", "content"])))

      "editor_copilot" ->
        Map.put(base, "prompt", data["prompt"])
    end
  end
end
