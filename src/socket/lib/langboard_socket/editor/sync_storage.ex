defmodule LangboardSocket.Editor.SyncStorage do
  @moduledoc false

  def verify_writable(directory) when is_binary(directory) and directory != "" do
    if File.dir?(directory) do
      probe_path = Path.join(directory, ".phoenix-storage-probe-#{temporary_suffix()}")

      verify_probe(probe_path)
    else
      {:error, :enoent}
    end
  end

  def verify_writable(_directory), do: {:error, :enoent}

  defp verify_probe(probe_path) do
    with :ok <- write_synced_temp(probe_path, "ok"),
         {:ok, "ok"} <- File.read(probe_path),
         :ok <- File.rm(probe_path) do
      sync_directory(Path.dirname(probe_path))
    else
      {:ok, _other} -> {:error, :corrupt_probe}
      {:error, reason} -> {:error, reason}
    end
  after
    File.rm(probe_path)
  end

  def path(document_name, directory) when is_binary(document_name) and is_binary(directory) do
    hash = :crypto.hash(:sha256, document_name) |> Base.encode16(case: :lower)
    Path.join(directory, "#{hash}.ydoc")
  end

  def load(document_name, directory) do
    with :ok <- require_directory(directory), do: read_document(document_name, directory)
  end

  def save(document_name, state, directory) when is_binary(state) do
    state_path = path(document_name, directory)
    temporary_path = "#{state_path}.#{temporary_suffix()}.tmp"

    try do
      with :ok <- require_directory(directory),
           :ok <- write_synced_temp(temporary_path, state),
           :ok <- File.rename(temporary_path, state_path) do
        sync_directory(directory)
      end
    after
      File.rm(temporary_path)
    end
  end

  def delete(document_name, directory) do
    with :ok <- require_directory(directory) do
      case File.rm(path(document_name, directory)) do
        :ok -> sync_directory(directory)
        {:error, :enoent} -> require_directory(directory)
        {:error, reason} -> {:error, reason}
      end
    end
  end

  defp require_directory(directory) do
    case File.stat(directory) do
      {:ok, %File.Stat{type: :directory}} -> :ok
      {:ok, _stat} -> {:error, :enotdir}
      {:error, reason} -> {:error, reason}
    end
  end

  defp read_document(document_name, directory) do
    max_bytes = Application.fetch_env!(:langboard_socket, :editor_sync_max_document_bytes)

    case File.open(path(document_name, directory), [:read, :binary]) do
      {:ok, file} ->
        try do
          read_bounded(file, max_bytes)
        after
          File.close(file)
        end

      {:error, :enoent} ->
        with :ok <- require_directory(directory), do: {:ok, nil}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp read_bounded(file, max_bytes) do
    case IO.binread(file, max_bytes + 1) do
      state when is_binary(state) and byte_size(state) <= max_bytes -> {:ok, state}
      state when is_binary(state) -> {:error, :document_too_large}
      :eof -> {:ok, <<>>}
      {:error, reason} -> {:error, reason}
    end
  end

  defp write_synced_temp(path, state) do
    with {:ok, file} <- File.open(path, [:write, :binary, :exclusive]) do
      result =
        with :ok <- IO.binwrite(file, state) do
          :file.sync(file)
        end

      case File.close(file) do
        :ok -> result
        {:error, reason} -> {:error, reason}
      end
    end
  end

  defp sync_directory(directory) do
    case :file.open(directory, [:read, :raw, :directory]) do
      {:ok, file} ->
        result = normalize_directory_sync(:file.sync(file))

        case :file.close(file) do
          :ok -> result
          {:error, reason} -> {:error, reason}
        end

      {:error, :eacces} ->
        case :os.type() do
          {:win32, _name} -> :ok
          _type -> {:error, :eacces}
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp normalize_directory_sync({:error, :eacces}) do
    case :os.type() do
      {:win32, _name} -> :ok
      _type -> {:error, :eacces}
    end
  end

  defp normalize_directory_sync(result), do: result

  defp temporary_suffix do
    :crypto.strong_rand_bytes(12) |> Base.url_encode64(padding: false)
  end
end
