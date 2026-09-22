defmodule LangboardSocket.YjsBinaryCompatibilityTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.EditorSyncFrame

  # Encoded with the Node socket's installed yjs package using client IDs 305419896 and 2271560481.
  @initial Base.decode64!(
             "AQb4rNGRAQAEAQV0aXRsZQZCZWZvcmUHAQtkZXNjcmlwdGlvbgMBcAcA+KzRkQEGBgYA+KzRkQEHBGJvbGQEdHJ1ZYT4rNGRAQgEUmljaIb4rNGRAQwEYm9sZARudWxsAA=="
           )
  @state_vector Base.decode64!("Afis0ZEBDg==")
  @delta Base.decode64!("AQGhhpW7CACE+KzRkQEFBUFmdGVyAfis0ZEBAQAG")
  # Node Yjs client 741852963 inserts "N" at index 2 of the initial title.
  @node_concurrent_delta Base.decode64!("AQGjjt/hAgDE+KzRkQEB+KzRkQECAU4A")
  @document_name "card:fixture:description"
  @sync_step1 Base.decode64!("GGNhcmQ6Zml4dHVyZTpkZXNjcmlwdGlvbgAAAQA=")
  @sync_step2 Base.decode64!(
                "GGNhcmQ6Zml4dHVyZTpkZXNjcmlwdGlvbgABYQEG+KzRkQEABAEFdGl0bGUGQmVmb3JlBwELZGVzY3JpcHRpb24DAXAHAPis0ZEBBgYGAPis0ZEBBwRib2xkBHRydWWE+KzRkQEIBFJpY2iG+KzRkQEMBGJvbGQEbnVsbAA="
              )
  @sync_update Base.decode64!(
                 "GGNhcmQ6Zml4dHVyZTpkZXNjcmlwdGlvbgACHgEBoYaVuwgAhPis0ZEBBQVBZnRlcgH4rNGRAQEABg=="
               )
  @awareness_present Base.decode64!(
                       "GGNhcmQ6Zml4dHVyZTpkZXNjcmlwdGlvbgE1AZIhATB7InVzZXIiOnsibmFtZSI6IkVkaXRvciJ9LCJjdXJzb3IiOnsiYW5jaG9yIjoyfX0="
                     )
  @awareness_removed Base.decode64!("GGNhcmQ6Zml4dHVyZTpkZXNjcmlwdGlvbgEJAZIhAgRudWxs")

  test "loads a Node Yjs text and rich XML update without converting its history" do
    doc = Yex.Doc.new()

    assert :ok = Yex.apply_update(doc, @initial)
    assert Yex.Text.to_string(Yex.Doc.get_text(doc, "title")) == "Before"

    assert Yex.XmlFragment.to_string(Yex.Doc.get_xml_fragment(doc, "description")) ==
             "<p><bold>Rich</bold></p>"

    assert Yex.encode_state_vector!(doc) == @state_vector

    replica = Yex.Doc.new()
    assert :ok = Yex.apply_update(replica, Yex.encode_state_as_update!(doc))
    assert Yex.encode_state_vector!(replica) == @state_vector
  end

  test "applies a Node Yjs incremental update to the original document" do
    doc = Yex.Doc.new()

    assert :ok = Yex.apply_update(doc, @initial)
    assert :ok = Yex.apply_update(doc, @delta)
    assert Yex.Text.to_string(Yex.Doc.get_text(doc, "title")) == "After"

    assert Yex.XmlFragment.to_string(Yex.Doc.get_xml_fragment(doc, "description")) ==
             "<p><bold>Rich</bold></p>"

    assert :ok = Yex.apply_update(doc, @delta)
    assert Yex.Text.to_string(Yex.Doc.get_text(doc, "title")) == "After"
  end

  test "concurrent edits converge from the Node document regardless of delivery order" do
    for seed <- 1..40 do
      :rand.seed(:exsss, {seed, seed * 2, seed * 3})

      updates =
        for marker <- ["A", "B", "C"] do
          replica = Yex.Doc.new()
          assert :ok = Yex.apply_update(replica, @initial)
          title = Yex.Doc.get_text(replica, "title")
          assert :ok = Yex.Text.insert(title, :rand.uniform(7) - 1, marker)
          Yex.encode_state_as_update!(replica)
        end

      results =
        for order <- permutations(updates) do
          merged = Yex.Doc.new()
          assert :ok = Yex.apply_update(merged, @initial)

          for update <- order do
            assert :ok = Yex.apply_update(merged, update)
          end

          assert :ok = Yex.apply_update(merged, hd(order))

          {Yex.encode_state_as_update!(merged),
           Yex.Text.to_string(Yex.Doc.get_text(merged, "title"))}
        end

      assert length(Enum.uniq(Enum.map(results, &elem(&1, 1)))) == 1, inspect(seed)
      [{_update, title} | _] = results
      assert Enum.sort(String.graphemes(title)) == Enum.sort(String.graphemes("BeforeABC"))

      reconciled = Yex.Doc.new()

      for {update, _title} <- results do
        assert :ok = Yex.apply_update(reconciled, update)
      end

      assert Yex.Text.to_string(Yex.Doc.get_text(reconciled, "title")) == title

      assert Yex.XmlFragment.to_string(Yex.Doc.get_xml_fragment(reconciled, "description")) ==
               "<p><bold>Rich</bold></p>"
    end
  end

  test "concurrent Node Yjs and Yex edits converge in either delivery order" do
    phoenix = Yex.Doc.new()
    assert :ok = Yex.apply_update(phoenix, @initial)
    assert :ok = Yex.Text.insert(Yex.Doc.get_text(phoenix, "title"), 2, "P")
    phoenix_delta = Yex.encode_state_as_update!(phoenix, @state_vector)

    results =
      for updates <- [
            [@node_concurrent_delta, phoenix_delta],
            [phoenix_delta, @node_concurrent_delta]
          ] do
        merged = Yex.Doc.new()
        assert :ok = Yex.apply_update(merged, @initial)

        for update <- updates do
          assert :ok = Yex.apply_update(merged, update)
        end

        assert :ok = Yex.apply_update(merged, hd(updates))

        assert Yex.XmlFragment.to_string(Yex.Doc.get_xml_fragment(merged, "description")) ==
                 "<p><bold>Rich</bold></p>"

        {Yex.Text.to_string(Yex.Doc.get_text(merged, "title")),
         Yex.encode_state_as_update!(merged)}
      end

    [{title, first_state}, {title, second_state}] = results
    assert title in ["BeNPfore", "BePNfore"]

    for state <- [first_state, second_state] do
      replica = Yex.Doc.new()
      assert :ok = Yex.apply_update(replica, state)
      assert Yex.Text.to_string(Yex.Doc.get_text(replica, "title")) == title
    end
  end

  test "reads Node y-protocols sync frames and answers a step1 request" do
    source = Yex.Doc.new()
    client = Yex.Doc.new()

    assert :ok = Yex.apply_update(source, @initial)
    assert {:sync, {:sync_step1, empty_vector}} = decode_hocuspocus_frame(@sync_step1)

    assert {:ok, {:sync_step2, response}} =
             Yex.Sync.read_sync_message({:sync_step1, empty_vector}, source, nil)

    assert :ok = Yex.apply_update(client, response)
    assert Yex.Text.to_string(Yex.Doc.get_text(client, "title")) == "Before"

    assert {:sync, step2} = decode_hocuspocus_frame(@sync_step2)
    assert :ok = Yex.Sync.read_sync_message(step2, client, nil)
    assert Yex.encode_state_vector!(client) == @state_vector

    assert {:sync, update} = decode_hocuspocus_frame(@sync_update)
    assert :ok = Yex.Sync.read_sync_message(update, client, nil)
    assert Yex.Text.to_string(Yex.Doc.get_text(client, "title")) == "After"
  end

  test "reads Node Hocuspocus awareness entry and removal frames" do
    {:ok, awareness} = Yex.Awareness.new(Yex.Doc.new())

    assert {:awareness, present} = decode_hocuspocus_frame(@awareness_present)
    assert :ok = Yex.Awareness.apply_update(awareness, present)

    assert Yex.Awareness.get_states(awareness)[4242] == %{
             "user" => %{"name" => "Editor"},
             "cursor" => %{"anchor" => 2}
           }

    assert {:awareness, removed} = decode_hocuspocus_frame(@awareness_removed)
    assert :ok = Yex.Awareness.apply_update(awareness, removed)
    refute Map.has_key?(Yex.Awareness.get_states(awareness), 4242)
  end

  defp decode_hocuspocus_frame(binary) do
    assert {:ok, document_name, frame} = EditorSyncFrame.decode(binary, 8_388_608)
    assert document_name == @document_name
    Yex.Sync.message_decode!(frame)
  end

  defp permutations([]), do: [[]]

  defp permutations(items) do
    for item <- items, rest <- permutations(List.delete(items, item)), do: [item | rest]
  end
end
