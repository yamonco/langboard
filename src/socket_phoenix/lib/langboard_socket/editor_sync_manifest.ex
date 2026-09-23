defmodule LangboardSocket.EditorSyncManifest do
  @moduledoc false

  alias LangboardSocket.EditorSyncStorage

  def audit(source_directory, destination_directory, document_names)
      when is_binary(source_directory) and is_binary(destination_directory) and
             is_list(document_names) do
    source = Path.expand(source_directory)
    destination = Path.expand(destination_directory)

    cond do
      source == destination ->
        {:error, :same_directory}

      not File.dir?(source) ->
        {:error, :missing_source_directory}

      not File.dir?(destination) ->
        {:error, :missing_destination_directory}

      not Enum.all?(document_names, &valid_name?/1) ->
        {:error, :invalid_document_names}

      length(document_names) != MapSet.size(MapSet.new(document_names)) ->
        {:error, :duplicate_document_names}

      true ->
        audit_documents(source, destination, Enum.sort(document_names))
    end
  end

  def audit(_source, _destination, _names), do: {:error, :invalid_inputs}

  defp audit_documents(source, destination, names) do
    documents =
      Enum.map(names, fn name ->
        file_name = Path.basename(EditorSyncStorage.path(name, source))
        source_result = inspect_document(Path.join(source, file_name))
        destination_result = inspect_document(Path.join(destination, file_name))

        %{
          "document_name" => name,
          "file_name" => file_name,
          "source_checksum" => checksum(source_result),
          "destination_checksum" => checksum(destination_result),
          "source_bytes" => byte_count(source_result),
          "restore_status" => restore_status(source_result, destination_result)
        }
      end)

    mapped = MapSet.new(Enum.map(documents, & &1["file_name"]))
    opaque_documents = audit_opaque_documents(source, destination, mapped)
    opaque_files = MapSet.new(Enum.map(opaque_documents, & &1["file_name"]))
    audited = MapSet.union(mapped, opaque_files)
    unmapped_source = unmapped_files(source, audited)
    unmapped_destination = unmapped_files(destination, audited)

    verified =
      unmapped_source == [] and unmapped_destination == [] and
        Enum.all?(documents, &(&1["restore_status"] == "verified")) and
        Enum.all?(opaque_documents, &(&1["restore_status"] == "verified"))

    {:ok,
     %{
       "format_version" => 2,
       "generated_at" => DateTime.utc_now() |> DateTime.to_iso8601(),
       "source_directory" => source,
       "destination_directory" => destination,
       "verified" => verified,
       "documents" => documents,
       "opaque_documents" => opaque_documents,
       "unmapped_source_files" => unmapped_source,
       "unmapped_destination_files" => unmapped_destination
     }}
  end

  defp audit_opaque_documents(source, destination, mapped) do
    source
    |> File.ls!()
    |> Enum.reject(&MapSet.member?(mapped, &1))
    |> Enum.filter(&hashed_document_file?/1)
    |> Enum.sort()
    |> Enum.map(fn file_name ->
      source_result = inspect_document(Path.join(source, file_name))
      destination_result = inspect_document(Path.join(destination, file_name))

      %{
        "file_name" => file_name,
        "source_checksum" => checksum(source_result),
        "destination_checksum" => checksum(destination_result),
        "source_bytes" => byte_count(source_result),
        "restore_status" => restore_status(source_result, destination_result)
      }
    end)
  end

  defp hashed_document_file?(file_name),
    do: Regex.match?(~r/\A[0-9a-f]{64}\.ydoc\z/, file_name)

  defp valid_name?(name),
    do: is_binary(name) and name != "" and byte_size(name) <= 512 and String.valid?(name)

  defp inspect_document(path) do
    max_bytes = Application.fetch_env!(:langboard_socket, :editor_sync_max_document_bytes)

    case File.stat(path) do
      {:ok, %{size: size}} when size > max_bytes ->
        {:error, :oversized}

      {:ok, _stat} ->
        read_document(path, max_bytes)

      {:error, :enoent} ->
        {:error, :missing}

      {:error, _reason} ->
        {:error, :unreadable}
    end
  end

  defp read_document(path, max_bytes) do
    case File.read(path) do
      {:ok, bytes} when byte_size(bytes) > max_bytes ->
        {:error, :oversized}

      {:ok, bytes} ->
        checksum = :crypto.hash(:sha256, bytes) |> Base.encode16(case: :lower)

        valid =
          try do
            Yex.apply_update(Yex.Doc.new(), bytes) == :ok
          rescue
            _error -> false
          end

        {:ok, byte_size(bytes), checksum, valid}

      {:error, _reason} ->
        {:error, :unreadable}
    end
  end

  defp checksum({:ok, _size, checksum, _valid}), do: checksum
  defp checksum(_result), do: nil

  defp byte_count({:ok, size, _checksum, _valid}), do: size
  defp byte_count(_result), do: nil

  defp restore_status({:error, :missing}, _destination), do: "missing_source"
  defp restore_status({:error, :unreadable}, _destination), do: "unreadable_source"
  defp restore_status({:error, :oversized}, _destination), do: "oversized_source"
  defp restore_status({:ok, _size, _checksum, false}, _destination), do: "invalid_source"
  defp restore_status(_source, {:error, :missing}), do: "missing_destination"
  defp restore_status(_source, {:error, :unreadable}), do: "unreadable_destination"
  defp restore_status(_source, {:error, :oversized}), do: "oversized_destination"
  defp restore_status(_source, {:ok, _size, _checksum, false}), do: "invalid_destination"

  defp restore_status(
         {:ok, _source_size, checksum, true},
         {:ok, _destination_size, checksum, true}
       ),
       do: "verified"

  defp restore_status(_source, _destination), do: "checksum_mismatch"

  defp unmapped_files(directory, mapped) do
    directory
    |> File.ls!()
    |> Enum.reject(&MapSet.member?(mapped, &1))
    |> Enum.sort()
  end
end
