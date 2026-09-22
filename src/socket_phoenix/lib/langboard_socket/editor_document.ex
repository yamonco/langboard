defmodule LangboardSocket.EditorDocument do
  @moduledoc false
  use GenServer, restart: :temporary

  alias LangboardSocket.ClusterStatus
  alias LangboardSocket.EditorSyncFrame
  alias LangboardSocket.EditorSyncStorage

  @idle_timeout_ms 60_000
  @lifecycle_lock_retries 10

  def child_spec({name, directory}) do
    %{
      id: {__MODULE__, name},
      start: {__MODULE__, :start_link, [{name, directory}]},
      restart: :temporary
    }
  end

  def start_link({name, directory}) do
    GenServer.start_link(__MODULE__, {name, directory}, name: {:global, global_name(name)})
  end

  def ensure_started(name, directory) do
    with_document_lock(name, fn ->
      case :global.whereis_name(global_name(name)) do
        :undefined -> start_document(name, directory)
        pid when is_pid(pid) -> {:ok, pid}
      end
    end)
  end

  def clear_inactive(name, directory) do
    with_document_lock(name, fn ->
      case :global.whereis_name(global_name(name)) do
        :undefined -> EditorSyncStorage.delete(name, directory)
        pid when is_pid(pid) -> {:error, :active}
      end
    end)
  end

  def active(name) do
    if cluster_ready?() do
      case :global.whereis_name(global_name(name)) do
        :undefined -> {:error, :inactive}
        pid when is_pid(pid) -> {:ok, pid}
      end
    else
      {:error, :cluster_unavailable}
    end
  end

  def active_names(type, entity_uid, limit)
      when is_binary(type) and type != "" and is_binary(entity_uid) and entity_uid != "" and
             is_integer(limit) and limit > 0 do
    prefix = "#{type}:#{entity_uid}"

    with true <- cluster_ready?(),
         {:ok, names, _count} <-
           Enum.reduce_while(
             :global.registered_names(),
             {:ok, [], 0},
             &collect_active_name(&1, &2, prefix, limit)
           ),
         true <- cluster_ready?() do
      {:ok, Enum.sort(names)}
    else
      false -> {:error, :cluster_unavailable}
      error -> error
    end
  end

  defp collect_active_name({__MODULE__, name}, {:ok, names, count}, prefix, limit)
       when is_binary(name) do
    if name == prefix or String.starts_with?(name, prefix <> ":") do
      case active(name) do
        {:ok, _server} when count < limit -> {:cont, {:ok, [name | names], count + 1}}
        {:ok, _server} -> {:halt, {:error, :too_many_documents}}
        {:error, :inactive} -> {:cont, {:ok, names, count}}
        error -> {:halt, error}
      end
    else
      {:cont, {:ok, names, count}}
    end
  end

  defp collect_active_name(_registration, result, _prefix, _limit), do: {:cont, result}

  def cluster_ready? do
    ClusterStatus.current_size() ==
      Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)
  end

  def join(server, client), do: GenServer.call(server, {:join, client})
  def leave(server, client), do: GenServer.call(server, {:leave, client})

  def sync_step1(server, client, vector),
    do: GenServer.call(server, {:sync_step1, client, vector})

  def apply_update(server, client, update),
    do: GenServer.call(server, {:apply_update, client, update})

  def apply_awareness(server, client, update, user_name),
    do: GenServer.call(server, {:apply_awareness, client, update, user_name})

  def query_awareness(server, client), do: GenServer.call(server, {:query_awareness, client})
  def get_text(server, field), do: GenServer.call(server, {:get_text, field})

  def replace_text(server, field, value),
    do: GenServer.call(server, {:replace_text, field, value})

  def request_rich_patch(server, value),
    do: GenServer.call(server, {:request_rich_patch, value})

  def apply_rich_patch(server, client, request_id, update),
    do: GenServer.call(server, {:apply_rich_patch, client, request_id, update})

  @impl true
  def init({name, directory}) do
    with {:ok, stored} <- EditorSyncStorage.load(name, directory),
         doc <- Yex.Doc.new(),
         :ok <- load_state(doc, stored),
         {:ok, awareness} <- Yex.Awareness.new(doc) do
      Yex.Awareness.monitor_update(awareness)
      :ok = :net_kernel.monitor_nodes(true, node_type: :visible)

      if cluster_ready?() do
        idle_ref = :erlang.start_timer(@idle_timeout_ms, self(), :idle)

        awareness_timeout_ms =
          Application.fetch_env!(:langboard_socket, :editor_sync_awareness_timeout_ms)

        {:ok,
         %{
           name: name,
           directory: directory,
           doc: doc,
           awareness: awareness,
           clients: %{},
           awareness_owners: %{},
           awareness_last_seen: %{},
           awareness_ref: nil,
           awareness_timeout_ms: awareness_timeout_ms,
           rich_patch: nil,
           idle_ref: idle_ref
         }}
      else
        {:stop, :cluster_unavailable}
      end
    else
      {:error, reason} -> {:stop, reason}
    end
  end

  @impl true
  def handle_call({:join, client}, _from, state) do
    max_clients = Application.fetch_env!(:langboard_socket, :editor_sync_max_clients_per_document)

    cond do
      not cluster_ready?() ->
        {:stop, {:shutdown, :cluster_unavailable}, {:error, :cluster_unavailable}, state}

      Map.has_key?(state.clients, client) ->
        {:reply, {:ok, initial_messages(state)}, state}

      map_size(state.clients) >= max_clients ->
        {:reply, {:error, :too_many_clients}, state}

      true ->
        if state.idle_ref, do: Process.cancel_timer(state.idle_ref)
        monitor = Process.monitor(client)
        clients = Map.put(state.clients, client, monitor)

        awareness_ref =
          state.awareness_ref || schedule_awareness_sweep(state.awareness_timeout_ms)

        {:reply, {:ok, initial_messages(state)},
         %{state | clients: clients, idle_ref: nil, awareness_ref: awareness_ref}}
    end
  end

  def handle_call({:leave, client}, _from, state) do
    {:reply, :ok, detach_client(client, state)}
  end

  def handle_call({:sync_step1, client, vector}, _from, state) do
    if Map.has_key?(state.clients, client) do
      with {:ok, message} <- Yex.Sync.get_sync_step2(state.doc, vector),
           {:ok, encoded} <- Yex.Sync.message_encode({:sync, message}) do
        {:reply, {:ok, encoded}, state}
      else
        {:error, reason} -> {:reply, {:error, reason}, state}
      end
    else
      {:reply, {:error, :not_joined}, state}
    end
  end

  def handle_call({:apply_update, client, update}, _from, state) do
    cond do
      not cluster_ready?() ->
        {:stop, {:shutdown, :cluster_unavailable}, {:error, :cluster_unavailable}, state}

      Map.has_key?(state.clients, client) ->
        with :ok <- Yex.apply_update(state.doc, update),
             :ok <- persist(state) do
          broadcast_peers(state, :editor_document_update, update, client)

          {:reply, :ok, state}
        else
          {:error, reason} ->
            {:stop, {:document_update_failed, reason}, {:error, reason}, state}
        end

      true ->
        {:reply, {:error, :not_joined}, state}
    end
  end

  def handle_call({:apply_awareness, client, update, user_name}, _from, state) do
    if Map.has_key?(state.clients, client) do
      max_clients =
        Application.fetch_env!(:langboard_socket, :editor_sync_max_clients_per_document)

      with {:ok, entries} <- EditorSyncFrame.decode_awareness(update, max_clients),
           {:ok, owned_entries} <- owned_awareness_entries(entries, state, client, max_clients),
           {:ok, ids, normalized} <- EditorSyncFrame.encode_awareness(owned_entries, user_name),
           true <-
             map_size(state.awareness_owners) +
               Enum.count(ids, &(not Map.has_key?(state.awareness_owners, &1))) <=
               max_clients,
           :ok <- apply_awareness_update(state.awareness, normalized, client) do
        {:reply, :ok, track_awareness_owners(ids, client, state)}
      else
        _result -> {:reply, {:error, :invalid_awareness}, state}
      end
    else
      {:reply, {:error, :not_joined}, state}
    end
  end

  def handle_call({:query_awareness, client}, _from, state) do
    if Map.has_key?(state.clients, client) do
      {:reply, Yex.Awareness.encode_update(state.awareness), state}
    else
      {:reply, {:error, :not_joined}, state}
    end
  end

  def handle_call({:get_text, field}, _from, state) do
    {:reply, {:ok, Yex.Text.to_string(Yex.Doc.get_text(state.doc, field))}, state}
  end

  def handle_call({:replace_text, field, value}, _from, state) do
    if cluster_ready?() do
      replace_text_ready(field, value, state)
    else
      {:stop, {:shutdown, :cluster_unavailable}, {:error, :cluster_unavailable}, state}
    end
  end

  def handle_call({:request_rich_patch, value}, from, state) do
    cond do
      not cluster_ready?() ->
        {:stop, {:shutdown, :cluster_unavailable}, {:error, :cluster_unavailable}, state}

      state.rich_patch != nil ->
        {:reply, {:error, :busy}, state}

      map_size(state.clients) == 0 ->
        {:reply, {:error, :inactive}, state}

      true ->
        start_rich_patch(value, from, state)
    end
  end

  def handle_call({:apply_rich_patch, client, request_id, update}, _from, state) do
    cond do
      not cluster_ready?() ->
        {:stop, {:shutdown, :cluster_unavailable}, {:error, :cluster_unavailable}, state}

      not Map.has_key?(state.clients, client) ->
        {:reply, {:error, :not_joined}, state}

      state.rich_patch == nil or state.rich_patch.id != request_id ->
        {:reply, :ok, state}

      document_hash(state.doc) != state.rich_patch.snapshot_hash ->
        {:reply, :ok, finish_rich_patch(state, {:error, :conflict})}

      true ->
        with :ok <- Yex.apply_update(state.doc, update),
             :ok <- persist(state) do
          broadcast_peers(state, :editor_document_update, update, nil)
          {:reply, :ok, finish_rich_patch(state, :ok)}
        else
          {:error, reason} ->
            {:stop, {:document_update_failed, reason}, {:error, reason}, state}
        end
    end
  end

  defp start_rich_patch(value, from, state) do
    snapshot = Yex.encode_state_as_update!(state.doc)
    id = Base.url_encode64(:crypto.strong_rand_bytes(24), padding: false)

    payload =
      Jason.encode!(%{
        type: "rich_patch_prepare",
        request_id: id,
        snapshot: Base.encode64(snapshot),
        value: value
      })

    {:ok, frame} = EditorSyncFrame.stateless(state.name, payload)

    if byte_size(frame) <= Application.fetch_env!(:langboard_socket, :socket_max_payload_bytes) do
      timeout = Application.fetch_env!(:langboard_socket, :editor_sync_rich_patch_timeout_ms)
      timer = :erlang.start_timer(timeout, self(), :rich_patch)
      monitor = Process.monitor(elem(from, 0))

      pending = %{
        id: id,
        from: from,
        timer: timer,
        monitor: monitor,
        snapshot_hash: :crypto.hash(:sha256, snapshot)
      }

      broadcast_peers(state, :editor_document_stateless, frame, nil)
      {:noreply, %{state | rich_patch: pending}}
    else
      {:reply, {:error, :frame_too_large}, state}
    end
  end

  defp document_hash(doc), do: :crypto.hash(:sha256, Yex.encode_state_as_update!(doc))

  defp finish_rich_patch(%{rich_patch: nil} = state, _result), do: state

  defp finish_rich_patch(state, result) do
    Process.cancel_timer(state.rich_patch.timer)
    Process.demonitor(state.rich_patch.monitor, [:flush])
    GenServer.reply(state.rich_patch.from, result)
    %{state | rich_patch: nil}
  end

  defp track_awareness_owners(ids, client, state) do
    present = Yex.Awareness.get_states(state.awareness)
    now = System.monotonic_time(:millisecond)

    {owners, last_seen} =
      Enum.reduce(ids, {state.awareness_owners, state.awareness_last_seen}, fn id,
                                                                               {owners, last_seen} ->
        if Map.has_key?(present, id) do
          {Map.put(owners, id, client), Map.put(last_seen, id, now)}
        else
          {Map.delete(owners, id), Map.delete(last_seen, id)}
        end
      end)

    %{state | awareness_owners: owners, awareness_last_seen: last_seen}
  end

  defp replace_text_ready(field, value, state) do
    text = Yex.Doc.get_text(state.doc, field)

    if Yex.Text.to_string(text) == value do
      {:reply, :ok, state}
    else
      with {:ok, vector} <- Yex.encode_state_vector(state.doc),
           :ok <- replace_text_value(state.doc, text, value),
           {:ok, update} <- Yex.encode_state_as_update(state.doc, vector),
           :ok <- persist(state) do
        broadcast_peers(state, :editor_document_update, update, nil)

        {:reply, :ok, state}
      else
        {:error, reason} ->
          {:stop, {:document_update_failed, reason}, {:error, reason}, state}

        :error ->
          {:stop, {:document_update_failed, :text_mutation_failed},
           {:error, :text_mutation_failed}, state}
      end
    end
  end

  @impl true
  def handle_info({:awareness_update, changes, origin, _awareness}, state) do
    changed_ids = changes.added ++ changes.updated ++ changes.removed

    if changed_ids != [] do
      case Yex.Awareness.encode_update(state.awareness, changed_ids) do
        {:ok, update} ->
          broadcast_peers(state, :editor_document_awareness, update, origin)

        {:error, _reason} ->
          :ok
      end
    end

    {:noreply, state}
  end

  def handle_info({:DOWN, monitor, :process, client, _reason}, state) do
    cond do
      state.rich_patch != nil and state.rich_patch.monitor == monitor ->
        {:noreply, finish_rich_patch(state, {:error, :cancelled})}

      Map.get(state.clients, client) == monitor ->
        {:noreply, detach_client(client, state)}

      true ->
        {:noreply, state}
    end
  end

  def handle_info({:timeout, reference, :rich_patch}, state) do
    if state.rich_patch != nil and state.rich_patch.timer == reference,
      do: {:noreply, finish_rich_patch(state, {:error, :timeout})},
      else: {:noreply, state}
  end

  def handle_info({:timeout, reference, :idle}, state) do
    if state.idle_ref == reference and map_size(state.clients) == 0 do
      {:stop, :normal, state}
    else
      {:noreply, state}
    end
  end

  def handle_info({:timeout, reference, :awareness_sweep}, state) do
    if state.awareness_ref == reference and map_size(state.clients) > 0 do
      now = System.monotonic_time(:millisecond)

      expired_ids =
        for {client_id, last_seen} <- state.awareness_last_seen,
            now - last_seen >= state.awareness_timeout_ms,
            do: client_id

      if expired_ids != [], do: Yex.Awareness.remove_states(state.awareness, expired_ids)

      {:noreply,
       %{
         state
         | awareness_owners: Map.drop(state.awareness_owners, expired_ids),
           awareness_last_seen: Map.drop(state.awareness_last_seen, expired_ids),
           awareness_ref: schedule_awareness_sweep(state.awareness_timeout_ms)
       }}
    else
      {:noreply, state}
    end
  end

  def handle_info({:nodedown, _node, _details}, state),
    do: {:stop, {:shutdown, :cluster_changed}, state}

  def handle_info({:nodedown, _node}, state), do: {:stop, {:shutdown, :cluster_changed}, state}

  def handle_info({:nodeup, _node, _details}, state) do
    if cluster_ready?(),
      do: {:noreply, state},
      else: {:stop, {:shutdown, :cluster_changed}, state}
  end

  def handle_info({:nodeup, _node}, state) do
    if cluster_ready?(),
      do: {:noreply, state},
      else: {:stop, {:shutdown, :cluster_changed}, state}
  end

  @impl true
  def terminate(reason, state) do
    Enum.each(state.clients, fn {client, _monitor} ->
      send(client, {:editor_document_closed, state.name, reason})
    end)
  end

  defp start_document(name, directory) do
    case DynamicSupervisor.start_child(
           LangboardSocket.EditorDocumentSupervisor,
           {__MODULE__, {name, directory}}
         ) do
      {:error, {:already_started, pid}} ->
        {:ok, pid}

      result ->
        result
    end
  end

  defp broadcast_peers(state, event, update, origin) do
    Enum.each(state.clients, fn {peer, _monitor} ->
      if peer != origin, do: send(peer, {event, state.name, update})
    end)
  end

  defp global_name(name), do: {__MODULE__, name}

  defp with_document_lock(name, fun) do
    checked = fn ->
      if cluster_ready?(), do: fun.(), else: {:error, :cluster_unavailable}
    end

    if cluster_ready?() do
      lock_id = {{__MODULE__, :lifecycle, name}, self()}

      case :global.trans(
             lock_id,
             checked,
             [node() | Node.list(:visible)],
             @lifecycle_lock_retries
           ) do
        :aborted -> {:error, :busy}
        result -> result
      end
    else
      {:error, :cluster_unavailable}
    end
  end

  defp load_state(_doc, nil), do: :ok
  defp load_state(doc, state), do: Yex.apply_update(doc, state)

  defp initial_messages(state) do
    {:ok, sync_step1} = Yex.Sync.get_sync_step1(state.doc)
    {:ok, sync_frame} = Yex.Sync.message_encode({:sync, sync_step1})
    {:ok, awareness_update} = Yex.Awareness.encode_update(state.awareness)
    {:ok, awareness_frame} = Yex.Sync.message_encode({:awareness, awareness_update})
    [sync_frame, awareness_frame]
  end

  defp persist(state) do
    encoded = Yex.encode_state_as_update!(state.doc)
    max_bytes = Application.fetch_env!(:langboard_socket, :editor_sync_max_document_bytes)

    if byte_size(encoded) <= max_bytes do
      EditorSyncStorage.save(state.name, encoded, state.directory)
    else
      {:error, :document_too_large}
    end
  end

  defp apply_awareness_update(_awareness, <<0>>, _client), do: :ok

  defp apply_awareness_update(awareness, update, client) do
    Yex.Awareness.apply_update(awareness, update, client)
  rescue
    _error -> {:error, :invalid_awareness}
  end

  defp owned_awareness_entries(entries, state, client, max_clients) do
    {owned, echoed} =
      Enum.split_with(entries, fn %{id: id} ->
        Map.get(state.awareness_owners, id, client) == client
      end)

    if echoed == [] do
      {:ok, owned}
    else
      echoed_ids = Enum.map(echoed, & &1.id)

      with {:ok, current_update} <- Yex.Awareness.encode_update(state.awareness, echoed_ids),
           {:ok, current_entries} <-
             EditorSyncFrame.decode_awareness(current_update, max_clients),
           current = Map.new(current_entries, &{&1.id, &1}),
           true <-
             Enum.all?(echoed, &unchanged_awareness_echo?(&1, Map.get(current, &1.id))) do
        {:ok, owned}
      else
        _result -> {:error, :invalid_awareness}
      end
    end
  end

  defp unchanged_awareness_echo?(
         %{clock_value: clock, state: value},
         %{clock_value: current_clock, state: current_value}
       ) do
    current_clock > clock or (current_clock == clock and current_value == value)
  end

  defp unchanged_awareness_echo?(_echo, _current), do: false

  defp replace_text_value(doc, text, value) do
    Yex.Doc.transaction(doc, fn ->
      with :ok <- Yex.Text.delete(text, 0, Yex.Text.length(text)) do
        Yex.Text.insert(text, 0, value)
      end
    end)
  end

  defp schedule_awareness_sweep(timeout_ms) do
    :erlang.start_timer(max(div(timeout_ms, 10), 1_000), self(), :awareness_sweep)
  end

  defp detach_client(client, state) do
    case Map.pop(state.clients, client) do
      {nil, _clients} ->
        state

      {monitor, clients} ->
        Process.demonitor(monitor, [:flush])

        owned_ids =
          for {client_id, ^client} <- state.awareness_owners,
              do: client_id

        if owned_ids != [], do: Yex.Awareness.remove_states(state.awareness, owned_ids)

        owners = Map.drop(state.awareness_owners, owned_ids)

        if map_size(clients) == 0 do
          state = finish_rich_patch(state, {:error, :inactive})
          if state.awareness_ref, do: Process.cancel_timer(state.awareness_ref)
          reference = :erlang.start_timer(@idle_timeout_ms, self(), :idle)

          %{
            state
            | clients: clients,
              awareness_owners: owners,
              awareness_last_seen: Map.drop(state.awareness_last_seen, owned_ids),
              awareness_ref: nil,
              idle_ref: reference
          }
        else
          %{
            state
            | clients: clients,
              awareness_owners: owners,
              awareness_last_seen: Map.drop(state.awareness_last_seen, owned_ids)
          }
        end
    end
  end
end
