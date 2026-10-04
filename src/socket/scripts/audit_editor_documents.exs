args =
  case System.argv() do
    ["--" | rest] -> rest
    rest -> rest
  end

case args do
  [directory] ->
    unless File.dir?(directory) do
      IO.puts(:stderr, "Editor document directory does not exist: #{directory}")
      System.halt(2)
    end

    files =
      directory
      |> File.ls!()
      |> Enum.filter(&String.ends_with?(&1, ".ydoc"))
      |> Enum.map(&Path.join(directory, &1))

    max_bytes = Application.fetch_env!(:langboard_socket, :editor_sync_max_document_bytes)

    failures =
      Enum.reject(files, fn file ->
        case File.open(file, [:read, :binary]) do
          {:ok, handle} ->
            try do
              case IO.binread(handle, max_bytes + 1) do
                state when is_binary(state) and byte_size(state) <= max_bytes ->
                  try do
                    Yex.apply_update(Yex.Doc.new(), state) == :ok
                  rescue
                    _error -> false
                  end

                _other ->
                  false
              end
            after
              File.close(handle)
            end

          {:error, _reason} ->
            false
        end
      end)

    IO.puts("Editor documents: #{length(files)} checked, #{length(failures)} failed")

    if failures != [] do
      Enum.each(failures, &IO.puts(:stderr, &1))
      System.halt(1)
    end

  _args ->
    IO.puts(:stderr, "Usage: mix run scripts/audit_editor_documents.exs -- DOCUMENT_DIRECTORY")
    System.halt(2)
end
