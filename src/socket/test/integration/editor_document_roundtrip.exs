documents = IO.read(:stdio, :eof) |> Jason.decode!()

roundtripped =
  Enum.map(documents, fn encoded ->
    document = Yex.Doc.new()
    :ok = Yex.apply_update(document, Base.decode64!(encoded))
    Base.encode64(Yex.encode_state_as_update!(document))
  end)

IO.puts(Jason.encode!(roundtripped))
