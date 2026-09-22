defmodule LangboardSocket.EditorSyncStorageTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.EditorSyncStorage

  @document_name "card:fixture:description"
  @node_hash "0258ccf4aba1207cf19c5a268414ee33856a4340da0ba9d48703f66a3016a512"
  @node_update Base.decode64!(
                 "AQb4rNGRAQAEAQV0aXRsZQZCZWZvcmUHAQtkZXNjcmlwdGlvbgMBcAcA+KzRkQEGBgYA+KzRkQEHBGJvbGQEdHJ1ZYT4rNGRAQgEUmljaIb4rNGRAQwEYm9sZARudWxsAA=="
               )

  setup do
    directory =
      Path.join(System.tmp_dir!(), "langboard-editor-sync-#{System.unique_integer([:positive])}")

    on_exit(fn -> File.rm_rf!(directory) end)
    %{directory: directory}
  end

  test "storage preflight requires an existing readable and writable mount", %{
    directory: directory
  } do
    assert {:error, :enoent} = EditorSyncStorage.verify_writable(directory)
    refute File.exists?(directory)

    assert :ok = File.mkdir_p(directory)
    assert :ok = EditorSyncStorage.verify_writable(directory)
    assert {:ok, []} = File.ls(directory)
  end

  test "uses the Node storage filename and reads an existing Yjs document", %{
    directory: directory
  } do
    path = EditorSyncStorage.path(@document_name, directory)
    assert Path.basename(path) == "#{@node_hash}.ydoc"
    assert :ok = File.mkdir_p(directory)
    assert :ok = File.write(path, @node_update)
    assert {:ok, @node_update} = EditorSyncStorage.load(@document_name, directory)

    doc = Yex.Doc.new()
    assert :ok = Yex.apply_update(doc, @node_update)
    assert Yex.Text.to_string(Yex.Doc.get_text(doc, "title")) == "Before"
  end

  test "storage preflight rejects a file without changing it", %{directory: path} do
    assert :ok = File.write(path, "existing")
    assert {:error, :enoent} = EditorSyncStorage.verify_writable(path)
    assert {:ok, "existing"} = File.read(path)
    assert {:error, :enoent} = EditorSyncStorage.verify_writable(nil)
    assert {:error, :enoent} = EditorSyncStorage.verify_writable("")
  end

  test "atomically replaces a document and removes its temporary file", %{directory: directory} do
    assert {:ok, nil} = EditorSyncStorage.load(@document_name, directory)
    assert :ok = EditorSyncStorage.save(@document_name, @node_update, directory)
    assert {:ok, @node_update} = EditorSyncStorage.load(@document_name, directory)

    assert :ok = EditorSyncStorage.save(@document_name, <<0, 1, 2>>, directory)
    assert {:ok, <<0, 1, 2>>} = EditorSyncStorage.load(@document_name, directory)
    assert ["#{@node_hash}.ydoc"] = File.ls!(directory)
  end

  test "removes the synced temporary file if replacement fails", %{directory: directory} do
    path = EditorSyncStorage.path(@document_name, directory)
    assert :ok = File.mkdir_p(path)

    assert {:error, _reason} = EditorSyncStorage.save(@document_name, @node_update, directory)
    assert ["#{@node_hash}.ydoc"] = File.ls!(directory)
    assert File.dir?(path)
  end

  test "deleting a missing document is idempotent", %{directory: directory} do
    assert :ok = EditorSyncStorage.delete(@document_name, directory)
    assert :ok = EditorSyncStorage.save(@document_name, @node_update, directory)
    assert :ok = EditorSyncStorage.delete(@document_name, directory)
    assert :ok = EditorSyncStorage.delete(@document_name, directory)
    assert {:ok, nil} = EditorSyncStorage.load(@document_name, directory)
  end
end
