defmodule LangboardSocket.GraphStreamDecoderTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.GraphStreamDecoder

  test "decodes fragmented UTF-8 token frames without losing the final delimiter" do
    frame = frame("token", %{"chunk" => "café"})
    {offset, _length} = :binary.match(frame, "é")
    first = binary_part(frame, 0, offset + 1)
    second = binary_part(frame, offset + 1, byte_size(frame) - offset - 1)
    decoder = GraphStreamDecoder.new(1024)

    assert {:ok, [], decoder} = GraphStreamDecoder.feed(decoder, first)
    assert {:ok, [{:token, "café"}], decoder} = GraphStreamDecoder.feed(decoder, second)
    assert {:error, :incomplete_stream} = GraphStreamDecoder.finish(decoder)

    assert {:ok, [:end], decoder} =
             GraphStreamDecoder.feed(decoder, frame("end", %{"result" => %{}}))

    assert :ok = GraphStreamDecoder.finish(decoder)
  end

  test "keeps ordered tokens and interrupts while ignoring unknown frames" do
    payload =
      frame("status", %{"value" => "running"}) <>
        frame("token", %{"chunk" => "a"}) <>
        frame("interrupt", %{"thread_id" => "thread-1"}) <>
        frame("end", %{})

    assert {:ok, [{:token, "a"}, {:interrupt, %{"thread_id" => "thread-1"}}, :end], decoder} =
             GraphStreamDecoder.feed(GraphStreamDecoder.new(1024), payload)

    assert :ok = GraphStreamDecoder.finish(decoder)
  end

  test "accepts a chunk of small complete frames larger than the frame limit" do
    payload =
      frame("token", %{"chunk" => "a"}) <> frame("token", %{"chunk" => "b"}) <> frame("end", %{})

    assert {:ok, [{:token, "a"}, {:token, "b"}, :end], decoder} =
             GraphStreamDecoder.feed(GraphStreamDecoder.new(64), payload)

    assert :ok = GraphStreamDecoder.finish(decoder)
  end

  test "treats graph errors as terminal and rejects a second terminal frame" do
    assert {:ok, [{:error, "upstream failed"}], decoder} =
             GraphStreamDecoder.feed(
               GraphStreamDecoder.new(1024),
               frame("error", %{"error" => "upstream failed"})
             )

    assert :ok = GraphStreamDecoder.finish(decoder)
    assert {:error, :already_ended} = GraphStreamDecoder.feed(decoder, frame("end", %{}))

    assert {:error, :data_after_end} =
             GraphStreamDecoder.feed(
               GraphStreamDecoder.new(1024),
               frame("end", %{}) <> frame("token", %{"chunk" => "late"})
             )
  end

  test "rejects oversized and malformed frames" do
    assert {:error, :buffer_too_large} =
             GraphStreamDecoder.feed(GraphStreamDecoder.new(8), frame("token", %{"chunk" => "a"}))

    assert {:error, :invalid_frame} =
             GraphStreamDecoder.feed(
               GraphStreamDecoder.new(1024),
               ~s({"event":"token"}) <> "\n\n"
             )

    assert {:error, :incomplete_stream} =
             GraphStreamDecoder.new(1024)
             |> GraphStreamDecoder.feed("{\"event\":")
             |> elem(2)
             |> GraphStreamDecoder.finish()
  end

  test "Langflow frames ignore user messages and preserve cumulative bot text" do
    payload =
      frame("add_message", %{"sender" => "UsEr", "text" => "question"}) <>
        frame("token", %{"token" => false, "chunk" => "ignored"}) <>
        frame("token", %{"token" => true, "chunk" => "partial"}) <>
        frame("add_message", %{"sender" => "AI", "text" => "complete"}) <>
        frame("end", %{})

    assert {:ok, [{:token, "partial"}, {:token, "complete"}, :end], decoder} =
             GraphStreamDecoder.feed(GraphStreamDecoder.new(1024, :langflow), payload)

    assert :ok = GraphStreamDecoder.finish(decoder)
  end

  test "Langflow ignores non-token frames and cannot complete an interrupted stream" do
    assert {:ok, [], _decoder} =
             GraphStreamDecoder.feed(
               GraphStreamDecoder.new(1024, :langflow),
               frame("token", %{"chunk" => "missing flag"}) <>
                 frame("interrupt", %{"thread_id" => "ignored"})
             )

    assert {:ok, [{:token, "partial"}], decoder} =
             GraphStreamDecoder.feed(
               GraphStreamDecoder.new(1024, :langflow),
               frame("token", %{"token" => true, "chunk" => "partial"})
             )

    assert {:error, :incomplete_stream} = GraphStreamDecoder.finish(decoder)
  end

  test "preserves mode-specific validation of known events" do
    for mode <- [:graph, :langflow] do
      for invalid <- ["not json", "null", "[]", "{}", frame("end", []), frame("error", %{})] do
        assert {:error, :invalid_frame} =
                 GraphStreamDecoder.feed(GraphStreamDecoder.new(1024, mode), invalid <> "\n\n")
      end

      assert {:ok, [{:error, "failure"}], decoder} =
               GraphStreamDecoder.feed(
                 GraphStreamDecoder.new(1024, mode),
                 frame("error", %{"error" => "failure"})
               )

      assert :ok = GraphStreamDecoder.finish(decoder)
    end

    assert {:error, :invalid_frame} =
             GraphStreamDecoder.feed(
               GraphStreamDecoder.new(1024),
               frame("error", %{"message" => "Langflow failure"})
             )

    assert {:ok, [{:error, "Langflow failure"}], decoder} =
             GraphStreamDecoder.feed(
               GraphStreamDecoder.new(1024, :langflow),
               frame("error", %{"message" => "Langflow failure"})
             )

    assert :ok = GraphStreamDecoder.finish(decoder)
  end

  test "ignores empty delimiters but rejects partial data after termination" do
    for mode <- [:graph, :langflow] do
      assert {:ok, [:end], decoder} =
               GraphStreamDecoder.feed(
                 GraphStreamDecoder.new(1024, mode),
                 "\n\n" <> frame("end", %{}) <> "\n\n"
               )

      assert :ok = GraphStreamDecoder.finish(decoder)

      assert {:error, :data_after_end} =
               GraphStreamDecoder.feed(
                 GraphStreamDecoder.new(1024, mode),
                 frame("end", %{}) <> "{"
               )
    end
  end

  defp frame(event, data) do
    Jason.encode!(%{"event" => event, "data" => data}) <> "\n\n"
  end
end
