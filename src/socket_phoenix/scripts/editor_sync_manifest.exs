alias LangboardSocket.EditorSyncManifest

args =
  case System.argv() do
    ["--" | rest] -> rest
    rest -> rest
  end

case args do
  [source, destination, name_file, manifest_file] ->
    with {:ok, input} <- File.read(name_file),
         {:ok, names} when is_list(names) <- Jason.decode(input),
         {:ok, manifest} <- EditorSyncManifest.audit(source, destination, names),
         {:ok, output} <- Jason.encode(manifest, pretty: true),
         :ok <- File.write(manifest_file, output <> "\n", [:exclusive]) do
      IO.puts("Editor documents: #{length(names)} named, verified=#{manifest["verified"]}")
      if not manifest["verified"], do: System.halt(1)
    else
      error ->
        IO.puts(:stderr, "Editor manifest failed: #{inspect(error)}")
        System.halt(2)
    end

  _args ->
    IO.puts(
      :stderr,
      "Usage: mix run scripts/editor_sync_manifest.exs -- SOURCE_DIR RESTORE_DIR NAMES_JSON MANIFEST_JSON"
    )

    System.halt(2)
end
