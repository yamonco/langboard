defmodule LangboardSocket.EditorSyncStorage do
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
    with :ok <- File.write(probe_path, "ok", [:binary, :exclusive]) do
      read_result =
        case File.read(probe_path) do
          {:ok, "ok"} -> :ok
          {:ok, _other} -> {:error, :corrupt_probe}
          {:error, reason} -> {:error, reason}
        end

      case File.rm(probe_path) do
        :ok -> read_result
        {:error, reason} -> {:error, reason}
      end
    end
  end

  def path(document_name, directory) when is_binary(document_name) and is_binary(directory) do
    hash = :crypto.hash(:sha256, document_name) |> Base.encode16(case: :lower)
    Path.join(directory, "#{hash}.ydoc")
  end

  def load(document_name, directory) do
    case File.read(path(document_name, directory)) do
      {:ok, state} -> {:ok, state}
      {:error, :enoent} -> {:ok, nil}
      {:error, reason} -> {:error, reason}
    end
  end

  def save(document_name, state, directory) when is_binary(state) do
    state_path = path(document_name, directory)
    temporary_path = "#{state_path}.#{temporary_suffix()}.tmp"

    try do
      with :ok <- File.mkdir_p(directory),
           :ok <- write_synced_temp(temporary_path, state),
           :ok <- File.rename(temporary_path, state_path) do
        sync_directory(directory)
      end
    after
      File.rm(temporary_path)
    end
  end

  def delete(document_name, directory) do
    case File.rm(path(document_name, directory)) do
      :ok -> sync_directory(directory)
      {:error, :enoent} -> :ok
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
