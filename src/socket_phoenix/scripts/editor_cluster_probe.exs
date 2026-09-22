defmodule EditorClusterProbe do
  @moduledoc false

  alias LangboardSocket.EditorDocument
  alias LangboardSocket.EditorSyncStorage

  def run do
    if not Node.alive?() do
      {:ok, _pid} = Node.start(:editor_cluster_probe, :shortnames)
    end

    for shutdown <- [:halt, 5_000], do: run_case(shutdown)
  end

  defp run_case(shutdown) do
    name = "card:cluster-#{System.unique_integer([:positive])}:description"
    remote_name = "card:cluster-#{System.unique_integer([:positive])}:description"

    directory =
      Path.join(
        System.tmp_dir!(),
        "langboard-editor-cluster-#{System.unique_integer([:positive])}"
      )

    previous = Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)
    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, 2)

    try do
      code_paths = Enum.flat_map(:code.get_path(), &[~c"-pa", &1])

      {:ok, peer, peer_node} =
        :peer.start_link(%{
          name: :peer.random_name(:editor_cluster_peer),
          args: code_paths,
          shutdown: shutdown
        })

      try do
        for app <- [:langboard_socket, :opentelemetry],
            {key, value} <- Application.get_all_env(app) do
          :ok = :rpc.call(peer_node, Application, :put_env, [app, key, value])
        end

        {:ok, _started} =
          :rpc.call(peer_node, Application, :ensure_all_started, [:langboard_socket])

        remote_supervisor =
          :rpc.call(peer_node, Process, :whereis, [LangboardSocket.EditorDocumentSupervisor])

        true = is_pid(remote_supervisor)
        2 = LangboardSocket.ClusterStatus.current_size()
        2 = :rpc.call(peer_node, LangboardSocket.ClusterStatus, :current_size, [])

        {:ok, owner} = EditorDocument.ensure_started(name, directory)
        {:ok, ^owner} = :rpc.call(peer_node, EditorDocument, :ensure_started, [name, directory])
        ^owner = :rpc.call(peer_node, :global, :whereis_name, [{EditorDocument, name}])

        {:error, :active} =
          :rpc.call(peer_node, EditorDocument, :clear_inactive, [name, directory])

        :ok =
          :rpc.call(peer_node, EditorDocument, :replace_text, [owner, "title", "Remote write"])

        {:ok, "Remote write"} = EditorDocument.get_text(owner, "title")
        {:ok, saved} = EditorSyncStorage.load(name, directory)
        restored = Yex.Doc.new()
        :ok = Yex.apply_update(restored, saved)
        "Remote write" = Yex.Text.to_string(Yex.Doc.get_text(restored, "title"))

        {:ok, remote_owner} =
          :rpc.call(peer_node, EditorDocument, :ensure_started, [remote_name, directory])

        ^peer_node = node(remote_owner)
        {:ok, ^remote_owner} = EditorDocument.ensure_started(remote_name, directory)
        :ok = EditorDocument.replace_text(remote_owner, "title", "Local write")

        {:ok, "Local write"} =
          :rpc.call(peer_node, EditorDocument, :get_text, [remote_owner, "title"])

        {:ok, _sync_messages} = EditorDocument.join(remote_owner, self())
        client_doc = Yex.Doc.new()
        :ok = Yex.Text.insert(Yex.Doc.get_text(client_doc, "client"), 0, "Accepted client edit")

        :ok =
          EditorDocument.apply_update(
            remote_owner,
            self(),
            Yex.encode_state_as_update!(client_doc)
          )

        {:ok, remote_saved} = EditorSyncStorage.load(remote_name, directory)
        remote_restored = Yex.Doc.new()
        :ok = Yex.apply_update(remote_restored, remote_saved)
        "Local write" = Yex.Text.to_string(Yex.Doc.get_text(remote_restored, "title"))
        "Accepted client edit" = Yex.Text.to_string(Yex.Doc.get_text(remote_restored, "client"))

        for _ <- 1..10 do
          contested_name =
            "card:cluster-race-#{System.unique_integer([:positive])}:description"

          local = Task.async(fn -> EditorDocument.ensure_started(contested_name, directory) end)

          remote =
            Task.async(fn ->
              :rpc.call(peer_node, EditorDocument, :ensure_started, [contested_name, directory])
            end)

          {:ok, contested_owner} = Task.await(local)
          {:ok, ^contested_owner} = Task.await(remote)
          ^contested_owner = :global.whereis_name({EditorDocument, contested_name})
        end

        clear_name = "card:cluster-clear-#{System.unique_integer([:positive])}:description"
        :ok = EditorSyncStorage.save(clear_name, <<1, 2, 3>>, directory)
        :ok = :rpc.call(peer_node, EditorDocument, :clear_inactive, [clear_name, directory])
        {:ok, nil} = EditorSyncStorage.load(clear_name, directory)

        for _ <- 1..10 do
          contested_name =
            "card:cluster-clear-race-#{System.unique_integer([:positive])}:description"

          saved_doc = Yex.Doc.new()
          :ok = Yex.Text.insert(Yex.Doc.get_text(saved_doc, "title"), 0, "Before")

          :ok =
            EditorSyncStorage.save(
              contested_name,
              Yex.encode_state_as_update!(saved_doc),
              directory
            )

          clear = Task.async(fn -> EditorDocument.clear_inactive(contested_name, directory) end)

          start =
            Task.async(fn ->
              :rpc.call(
                peer_node,
                EditorDocument,
                :ensure_started,
                [contested_name, directory],
                15_000
              )
            end)

          clear_result = Task.await(clear, 20_000)
          {:ok, contested_owner} = Task.await(start, 20_000)

          case clear_result do
            :ok ->
              {:ok, nil} = EditorSyncStorage.load(contested_name, directory)
              {:ok, ""} = EditorDocument.get_text(contested_owner, "title")

            {:error, :active} ->
              {:ok, "Before"} = EditorDocument.get_text(contested_owner, "title")
          end

          :ok =
            :rpc.call(peer_node, DynamicSupervisor, :terminate_child, [
              LangboardSocket.EditorDocumentSupervisor,
              contested_owner
            ])
        end

        monitor = Process.monitor(owner)
        :ok = :peer.stop(peer)

        receive do
          {:DOWN, ^monitor, :process, ^owner, {:shutdown, :cluster_changed}} -> :ok
        after
          5_000 -> raise "Editor owner stayed active after peer loss"
        end

        {:error, :cluster_unavailable} = EditorDocument.ensure_started(name, directory)
        {:error, :cluster_unavailable} = EditorDocument.clear_inactive(name, directory)
        {:ok, ^saved} = EditorSyncStorage.load(name, directory)

        {:ok, replacement, replacement_node} =
          :peer.start_link(%{
            name: :peer.random_name(:editor_cluster_replacement),
            args: code_paths
          })

        try do
          for app <- [:langboard_socket, :opentelemetry],
              {key, value} <- Application.get_all_env(app) do
            :ok = :rpc.call(replacement_node, Application, :put_env, [app, key, value])
          end

          {:ok, _started} =
            :rpc.call(replacement_node, Application, :ensure_all_started, [:langboard_socket])

          2 = LangboardSocket.ClusterStatus.current_size()
          2 = :rpc.call(replacement_node, LangboardSocket.ClusterStatus, :current_size, [])
          {:ok, restored_owner} = EditorDocument.ensure_started(name, directory)

          {:ok, ^restored_owner} =
            :rpc.call(replacement_node, EditorDocument, :ensure_started, [name, directory])

          {:ok, "Remote write"} = EditorDocument.get_text(restored_owner, "title")
          {:ok, ^saved} = EditorSyncStorage.load(name, directory)

          {:ok, restored_remote_owner} =
            :rpc.call(replacement_node, EditorDocument, :ensure_started, [remote_name, directory])

          ^replacement_node = node(restored_remote_owner)
          {:ok, ^restored_remote_owner} = EditorDocument.ensure_started(remote_name, directory)
          {:ok, "Local write"} = EditorDocument.get_text(restored_remote_owner, "title")
          {:ok, "Accepted client edit"} = EditorDocument.get_text(restored_remote_owner, "client")
          {:ok, ^remote_saved} = EditorSyncStorage.load(remote_name, directory)

          :ok =
            :rpc.call(replacement_node, EditorDocument, :replace_text, [
              restored_owner,
              "title",
              "Recovered write"
            ])

          {:ok, "Recovered write"} = EditorDocument.get_text(restored_owner, "title")
          {:ok, recovered_bytes} = EditorSyncStorage.load(name, directory)
          recovered_doc = Yex.Doc.new()
          :ok = Yex.apply_update(recovered_doc, recovered_bytes)
          "Recovered write" = Yex.Text.to_string(Yex.Doc.get_text(recovered_doc, "title"))
        after
          if Process.alive?(replacement), do: :peer.stop(replacement)
        end

        IO.puts("Phoenix editor cluster probe passed (shutdown: #{inspect(shutdown)})")
      after
        if Process.alive?(peer), do: :peer.stop(peer)
      end
    after
      Application.put_env(:langboard_socket, :editor_sync_expected_nodes, previous)
      File.rm_rf!(directory)
    end
  end
end

EditorClusterProbe.run()
