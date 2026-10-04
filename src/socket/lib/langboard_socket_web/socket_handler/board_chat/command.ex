defmodule LangboardSocketWeb.SocketHandler.BoardChat.Command do
  @moduledoc false

  alias LangboardSocket.BoardChat.ResumeWorker
  alias LangboardSocket.BoardChat.RunClient
  alias LangboardSocket.BoardChat.RunWorker
  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocketWeb.SocketHandler.State
  alias LangboardSocketWeb.SocketHandler.Subscriptions

  @short_uid_length Contract.short_uid_length!()
  @task_id_pattern ~r/\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\z/
  @board_topic Contract.topic!("board")
  @chat_send_event Contract.event!("board_chat_send")
  @chat_cancel_event Contract.event!("board_chat_cancel")
  @chat_resume_event Contract.event!("board_chat_resume")

  def handle(event, payload, state) do
    cond do
      event == @chat_send_event and
          Application.get_env(:langboard_socket, :board_chat_send_enabled, false) ->
        handle_send(payload, state)

      event == @chat_cancel_event and
          Application.get_env(:langboard_socket, :board_chat_send_enabled, false) ->
        handle_cancel(payload, state)

      event == @chat_resume_event and
          Application.get_env(:langboard_socket, :board_chat_resume_enabled, false) ->
        handle_resume(payload, state)

      true ->
        {:ok, state}
    end
  end

  defp handle_send(%{"topic" => @board_topic, "topic_id" => topic_id, "data" => data}, state)
       when is_binary(topic_id) and topic_id != "" and is_map(data) do
    if valid_send_data?(data) do
      case Subscriptions.authorize_board_command(topic_id, state) do
        :ok -> start_send(topic_id, data, state, State.command_capacity_exhausted?(state))
        {:error, close_code} -> {:stop, :normal, close_code, state}
      end
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_send(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp handle_cancel(
         %{"topic" => @board_topic, "topic_id" => topic_id, "data" => %{"task_id" => task_id}},
         state
       )
       when is_binary(topic_id) and topic_id != "" and is_binary(task_id) do
    if valid_task_id?(task_id) do
      case Subscriptions.authorize_board_command(topic_id, state) do
        :ok -> start_cancel(topic_id, task_id, state, State.command_capacity_exhausted?(state))
        {:error, close_code} -> {:stop, :normal, close_code, state}
      end
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_cancel(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  defp handle_resume(%{"topic" => @board_topic, "topic_id" => topic_id, "data" => data}, state)
       when is_binary(topic_id) and topic_id != "" and is_map(data) do
    if valid_resume_data?(data) do
      case Subscriptions.authorize_board_command(topic_id, state) do
        :ok -> start_resume(topic_id, data, state, State.command_capacity_exhausted?(state))
        {:error, close_code} -> {:stop, :normal, close_code, state}
      end
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  defp handle_resume(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  def valid_task_id?(task_id) when is_binary(task_id),
    do: String.match?(task_id, @task_id_pattern)

  def valid_task_id?(_task_id), do: false

  def start_cancel(topic_id, task_id, state, capacity_exhausted?) do
    if Map.has_key?(state.pending_chat_cancels, task_id) do
      {:ok, state}
    else
      if capacity_exhausted? do
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
      else
        start_chat_cancel_request(topic_id, task_id, state)
      end
    end
  end

  defp start_chat_cancel_request(topic_id, task_id, state) do
    owner = self()
    token = state.authorization_token
    client = Application.get_env(:langboard_socket, :board_chat_run_client, RunClient)

    cancel_request = fn ->
      result = client.cancel(token, topic_id, task_id)

      if match?({:ok, _run_uid}, result) do
        {:ok, run_uid} = result

        Phoenix.PubSub.broadcast(
          LangboardSocket.PubSub,
          RunWorker.cancel_topic(run_uid),
          {:board_chat_run_cancelled, run_uid}
        )
      end

      send(owner, {:board_chat_cancel_result, task_id, self(), result})
    end

    case Task.Supervisor.start_child(LangboardSocket.CommandTaskSupervisor, cancel_request) do
      {:ok, worker_pid} ->
        monitor_ref = Process.monitor(worker_pid)

        {:ok,
         %{
           state
           | pending_chat_cancels:
               Map.put(state.pending_chat_cancels, task_id, {topic_id, worker_pid, monitor_ref})
         }}

      {:error, _reason} ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
    end
  end

  def valid_send_data?(data) do
    message = Map.get(data, "message")
    file_token = Map.get(data, "file_token")
    task_id = Map.get(data, "task_id")
    scope_table = Map.get(data, "scope_table", "project")
    scope_uid = Map.get(data, "scope_uid")
    session_uid = Map.get(data, "session_uid")
    permission_level = Map.get(data, "api_permission_level", "read")

    valid_chat_content?(message, file_token) and
      valid_task_id?(task_id) and
      is_nil(Map.get(data, "file_path")) and
      (is_nil(session_uid) or Contract.valid_short_uid?(session_uid)) and
      permission_level in ["read", "edit", "full_access"] and
      valid_chat_scope?(scope_table, scope_uid)
  end

  defp valid_chat_content?(message, file_token) when is_binary(message) do
    byte_size(message) <= 65_536 and
      (is_nil(file_token) or valid_file_token?(file_token)) and
      (byte_size(message) > 0 or is_binary(file_token))
  end

  defp valid_chat_content?(_message, _file_token), do: false

  defp valid_chat_scope?("project", nil), do: true

  defp valid_chat_scope?(scope_table, scope_uid)
       when scope_table in ["card", "project_column", "project_wiki"],
       do: Contract.valid_short_uid?(scope_uid)

  defp valid_chat_scope?(_scope_table, _scope_uid), do: false

  defp valid_file_token?(token) when is_binary(token),
    do: byte_size(token) in 32..128 and String.match?(token, ~r/^[A-Za-z0-9._:-]+$/)

  defp valid_file_token?(_token), do: false

  def start_send(topic_id, data, state, capacity_exhausted?) do
    task_id = data["task_id"]

    if Map.has_key?(state.pending_chat_sends, task_id) do
      {:ok, state}
    else
      if capacity_exhausted? do
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
      else
        start_chat_send_request(topic_id, data, state)
      end
    end
  end

  defp start_chat_send_request(topic_id, data, state) do
    task_id = data["task_id"]
    worker = Application.get_env(:langboard_socket, :board_chat_run_worker, RunWorker)

    command =
      data
      |> Map.take([
        "task_id",
        "message",
        "file_token",
        "session_uid",
        "scope_table",
        "scope_uid",
        "api_permission_level"
      ])
      |> Map.put_new("scope_table", "project")
      |> Map.put_new("api_permission_level", "read")

    options = [
      token: state.authorization_token,
      project_uid: topic_id,
      command: command,
      receiver: self()
    ]

    case DynamicSupervisor.start_child(
           LangboardSocket.BoardChatRunSupervisor,
           {worker, options}
         ) do
      {:ok, worker_pid} ->
        monitor_ref = Process.monitor(worker_pid)

        {:ok,
         %{
           state
           | pending_chat_sends:
               Map.put(state.pending_chat_sends, task_id, {
                 topic_id,
                 worker_pid,
                 monitor_ref,
                 false
               })
         }}

      {:error, _reason} ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
    end
  end

  def valid_resume_data?(
        %{
          "message_uid" => uid,
          "thread_id" => thread_id,
          "session_id" => session_id,
          "resume" => resume
        } = data
      ) do
    Contract.valid_short_uid?(uid) and
      is_binary(thread_id) and byte_size(thread_id) in 1..512 and
      is_binary(session_id) and byte_size(session_id) in @short_uid_length..512 and
      is_map(resume) and
      (is_nil(Map.get(data, "approval_uid")) or Contract.valid_short_uid?(data["approval_uid"]))
  end

  def valid_resume_data?(_data), do: false

  def start_resume(topic_id, data, state, capacity_exhausted?) do
    source_uid = data["message_uid"]

    if Map.has_key?(state.pending_chat_resumes, source_uid) do
      {:ok, state}
    else
      if capacity_exhausted? do
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
      else
        start_chat_resume_request(topic_id, data, state)
      end
    end
  end

  defp start_chat_resume_request(topic_id, data, state) do
    source_uid = data["message_uid"]

    worker =
      Application.get_env(:langboard_socket, :board_chat_resume_worker, ResumeWorker)

    options = [
      token: state.authorization_token,
      project_uid: topic_id,
      command: data,
      receiver: self()
    ]

    case DynamicSupervisor.start_child(
           LangboardSocket.BoardChatRunSupervisor,
           {worker, options}
         ) do
      {:ok, worker_pid} ->
        monitor_ref = Process.monitor(worker_pid)

        {:ok,
         %{
           state
           | pending_chat_resumes:
               Map.put(
                 state.pending_chat_resumes,
                 source_uid,
                 {topic_id, worker_pid, monitor_ref, false}
               )
         }}

      {:error, _reason} ->
        {:stop, :normal, Contract.close_code!("try_again_later"), state}
    end
  end
end
