case System.argv() do
  [directory] ->
    unless File.dir?(directory) do
      IO.puts(:stderr, "Editor document directory does not exist: #{directory}")
      System.halt(2)
    end

    files = Path.wildcard(Path.join(directory, "*.ydoc"))

    failures =
      Enum.reject(files, fn file ->
        case File.read(file) do
          {:ok, state} ->
            try do
              Yex.apply_update(Yex.Doc.new(), state) == :ok
            rescue
              _error -> false
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
