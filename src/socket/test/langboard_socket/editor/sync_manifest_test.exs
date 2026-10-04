defmodule LangboardSocket.Editor.SyncManifestTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.Editor.SyncManifest
  alias LangboardSocket.Editor.SyncStorage

  setup do
    root =
      Path.join(
        System.tmp_dir!(),
        "langboard-editor-manifest-#{System.unique_integer([:positive])}"
      )

    source = Path.join(root, "source")
    destination = Path.join(root, "destination")
    File.mkdir_p!(source)
    File.mkdir_p!(destination)
    on_exit(fn -> File.rm_rf!(root) end)
    %{source: source, destination: destination}
  end

  test "verifies exact binary copies using Node-compatible document hashes", context do
    name = "card:fixture:description"
    doc = Yex.Doc.new()
    assert :ok = Yex.Text.insert(Yex.Doc.get_text(doc, "title"), 0, "Before")
    bytes = Yex.encode_state_as_update!(doc)
    source_path = SyncStorage.path(name, context.source)
    destination_path = SyncStorage.path(name, context.destination)
    assert :ok = File.write(source_path, bytes)
    assert :ok = File.write(destination_path, bytes)

    assert {:ok, manifest} =
             SyncManifest.audit(context.source, context.destination, [name])

    assert manifest["verified"]
    assert manifest["format_version"] == 2
    assert manifest["source_directory"] == Path.expand(context.source)
    assert manifest["destination_directory"] == Path.expand(context.destination)
    assert {:ok, _generated_at, _offset} = DateTime.from_iso8601(manifest["generated_at"])
    assert manifest["opaque_documents"] == []
    assert manifest["unmapped_source_files"] == []
    assert manifest["unmapped_destination_files"] == []

    assert [%{"restore_status" => "verified", "source_bytes" => size} = row] =
             manifest["documents"]

    assert size == byte_size(bytes)
    assert row["source_checksum"] == row["destination_checksum"]
    assert row["file_name"] == Path.basename(source_path)
    assert {:ok, ^bytes} = File.read(source_path)
  end

  test "reports missing, corrupt, mismatched, and unmapped files without changing them",
       context do
    names =
      for section <- ["missing", "corrupt", "mismatch", "invalid-destination"],
          do: "card:fixture:#{section}"

    doc = Yex.Doc.new()
    assert :ok = Yex.Text.insert(Yex.Doc.get_text(doc, "title"), 0, "Before")
    valid = Yex.encode_state_as_update!(doc)
    other = Yex.Doc.new()
    assert :ok = Yex.Text.insert(Yex.Doc.get_text(other, "title"), 0, "After")
    changed = Yex.encode_state_as_update!(other)

    for name <- names do
      source_path = SyncStorage.path(name, context.source)
      assert :ok = File.write(source_path, valid)
    end

    assert :ok =
             File.write(SyncStorage.path(Enum.at(names, 1), context.source), <<0, 1, 2>>)

    assert :ok =
             File.write(
               SyncStorage.path(Enum.at(names, 2), context.destination),
               changed
             )

    assert :ok =
             File.write(
               SyncStorage.path(Enum.at(names, 3), context.destination),
               <<0, 1, 2>>
             )

    assert :ok = File.write(Path.join(context.source, "unknown.ydoc"), valid)
    assert :ok = File.write(Path.join(context.destination, "pending.ydoc.tmp"), valid)

    assert {:ok, manifest} =
             SyncManifest.audit(context.source, context.destination, names)

    refute manifest["verified"]
    assert manifest["unmapped_source_files"] == ["unknown.ydoc"]
    assert manifest["unmapped_destination_files"] == ["pending.ydoc.tmp"]

    statuses = Map.new(manifest["documents"], &{&1["document_name"], &1["restore_status"]})
    assert statuses[Enum.at(names, 0)] == "missing_destination"
    assert statuses[Enum.at(names, 1)] == "invalid_source"
    assert statuses[Enum.at(names, 2)] == "checksum_mismatch"
    assert statuses[Enum.at(names, 3)] == "invalid_destination"
    assert {:ok, ^valid} = File.read(SyncStorage.path(Enum.at(names, 0), context.source))
  end

  test "verifies opaque hashed Yjs documents without guessing their names", context do
    doc = Yex.Doc.new()
    assert :ok = Yex.Text.insert(Yex.Doc.get_text(doc, "title"), 0, "Opaque")
    bytes = Yex.encode_state_as_update!(doc)
    file_name = "#{String.duplicate("a", 64)}.ydoc"
    assert :ok = File.write(Path.join(context.source, file_name), bytes)
    assert :ok = File.write(Path.join(context.destination, file_name), bytes)

    assert {:ok, manifest} = SyncManifest.audit(context.source, context.destination, [])

    assert manifest["verified"]
    assert manifest["documents"] == []
    assert manifest["unmapped_source_files"] == []
    assert manifest["unmapped_destination_files"] == []

    assert [
             %{
               "file_name" => ^file_name,
               "restore_status" => "verified",
               "source_bytes" => source_bytes,
               "source_checksum" => checksum,
               "destination_checksum" => checksum
             }
           ] = manifest["opaque_documents"]

    assert source_bytes == byte_size(bytes)
  end

  test "does not verify a missing opaque destination", context do
    doc = Yex.Doc.new()
    bytes = Yex.encode_state_as_update!(doc)
    file_name = "#{String.duplicate("b", 64)}.ydoc"
    assert :ok = File.write(Path.join(context.source, file_name), bytes)

    assert {:ok, manifest} = SyncManifest.audit(context.source, context.destination, [])

    refute manifest["verified"]

    assert [%{"file_name" => ^file_name, "restore_status" => "missing_destination"}] =
             manifest["opaque_documents"]
  end

  test "rejects a hard-linked restore instead of treating it as an independent copy", context do
    name = "card:fixture:linked"
    source_path = SyncStorage.path(name, context.source)
    destination_path = SyncStorage.path(name, context.destination)
    assert :ok = File.write(source_path, Yex.encode_state_as_update!(Yex.Doc.new()))
    assert :ok = File.ln(source_path, destination_path)

    assert {:ok, manifest} =
             SyncManifest.audit(context.source, context.destination, [name])

    refute manifest["verified"]
    assert [%{"restore_status" => "linked_source"}] = manifest["documents"]
  end

  test "rejects a symbolic-link restore directory", context do
    linked = Path.join(Path.dirname(context.source), "linked-destination")

    case File.ln_s(context.source, linked) do
      :ok ->
        assert {:error, :linked_directory} =
                 SyncManifest.audit(context.source, linked, [])

      {:error, :eperm} ->
        :ok
    end
  end

  test "rejects documents larger than the Phoenix persistence limit", context do
    name = "card:fixture:oversized"
    source_path = SyncStorage.path(name, context.source)
    destination_path = SyncStorage.path(name, context.destination)
    max_bytes = Application.fetch_env!(:langboard_socket, :editor_sync_max_document_bytes)
    assert :ok = File.write(source_path, :binary.copy(<<0>>, max_bytes + 1))

    assert {:ok, manifest} =
             SyncManifest.audit(context.source, context.destination, [name])

    refute manifest["verified"]
    assert [%{"restore_status" => "oversized_source"}] = manifest["documents"]

    valid = Yex.encode_state_as_update!(Yex.Doc.new())
    assert :ok = File.write(source_path, valid)
    assert :ok = File.write(destination_path, :binary.copy(<<0>>, max_bytes + 1))

    assert {:ok, manifest} =
             SyncManifest.audit(context.source, context.destination, [name])

    refute manifest["verified"]
    assert [%{"restore_status" => "oversized_destination"}] = manifest["documents"]
  end

  test "rejects incomplete input rather than reporting a clean migration", context do
    missing = Path.join(Path.dirname(context.source), "missing")

    assert {:error, :missing_source_directory} =
             SyncManifest.audit(missing, context.destination, [])

    assert {:error, :missing_destination_directory} =
             SyncManifest.audit(context.source, missing, [])

    refute File.exists?(missing)

    assert {:error, :same_directory} =
             SyncManifest.audit(context.source, context.source, [])

    assert {:error, :duplicate_document_names} =
             SyncManifest.audit(context.source, context.destination, [
               "card:one",
               "card:one"
             ])

    assert {:error, :invalid_document_names} =
             SyncManifest.audit(context.source, context.destination, ["card:one", nil])

    assert :ok = File.write(Path.join(context.source, "orphan.ydoc"), <<0>>)

    assert {:ok, %{"verified" => false, "unmapped_source_files" => ["orphan.ydoc"]}} =
             SyncManifest.audit(context.source, context.destination, [])
  end

  test "command writes a verified JSON manifest and reports success", context do
    name = "card:fixture:description"
    doc = Yex.Doc.new()
    assert :ok = Yex.Text.insert(Yex.Doc.get_text(doc, "title"), 0, "Before")
    bytes = Yex.encode_state_as_update!(doc)
    assert :ok = File.write(SyncStorage.path(name, context.source), bytes)
    assert :ok = File.write(SyncStorage.path(name, context.destination), bytes)

    root = Path.dirname(context.source)
    names_path = Path.join(root, "names.json")
    manifest_path = Path.join(root, "manifest.json")
    assert :ok = File.write(names_path, Jason.encode!([name]))

    {output, exit_code} =
      System.cmd(
        System.find_executable("elixir"),
        [
          "-S",
          "mix",
          "run",
          "scripts/editor_sync_manifest.exs",
          "--",
          context.source,
          context.destination,
          names_path,
          manifest_path
        ],
        cd: Path.expand("../../..", __DIR__),
        stderr_to_stdout: true
      )

    assert exit_code == 0, output
    assert {:ok, output_json} = File.read(manifest_path)

    assert %{"verified" => true, "documents" => [%{"restore_status" => "verified"}]} =
             Jason.decode!(output_json)

    assert {:ok, ^bytes} = File.read(SyncStorage.path(name, context.source))
  end

  test "document audit command rejects a file beyond the configured limit", context do
    path = Path.join(context.source, "oversized.ydoc")
    assert :ok = File.write(path, :binary.copy(<<0>>, 1_048_577))

    {output, exit_code} =
      System.cmd(
        System.find_executable("elixir"),
        ["-S", "mix", "run", "scripts/audit_editor_documents.exs", "--", context.source],
        cd: Path.expand("../../..", __DIR__),
        env: [{"SOCKET_EDITOR_SYNC_MAX_DOCUMENT_MB", "1"}],
        stderr_to_stdout: true
      )

    assert exit_code == 1, output
    assert output =~ "Editor documents: 1 checked, 1 failed"
    assert output =~ path
  end
end
