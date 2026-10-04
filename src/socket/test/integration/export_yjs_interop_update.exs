initial = IO.read(:stdio, :eof) |> String.trim() |> Base.decode64!()
doc = Yex.Doc.with_options(%Yex.Doc.Options{client_id: 2_271_560_481})

if "--replay" in System.argv() do
  for update <- Jason.decode!(initial) do
    :ok = Yex.apply_update(doc, Base.decode64!(update))
  end

  IO.puts(Base.encode64(Yex.encode_state_as_update!(doc)))
else
  :ok = Yex.apply_update(doc, initial)

  if "--roundtrip" in System.argv() do
    IO.puts(Base.encode64(Yex.encode_state_as_update!(doc)))
  else
    "Before" = Yex.Text.to_string(Yex.Doc.get_text(doc, "title"))

    "<p><bold>Rich</bold></p>" =
      Yex.XmlFragment.to_string(Yex.Doc.get_xml_fragment(doc, "description"))

    state_vector = Yex.encode_state_vector!(doc)
    :ok = Yex.Text.insert(Yex.Doc.get_text(doc, "title"), 2, "P")
    IO.puts(Base.encode64(Yex.encode_state_as_update!(doc, state_vector)))
  end
end
