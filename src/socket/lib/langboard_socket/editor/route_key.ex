defmodule LangboardSocket.Editor.RouteKey do
  @moduledoc false

  def for_document(name) when is_binary(name) do
    name
    |> :binary.bin_to_list()
    |> Enum.reduce(0x811C9DC5, fn byte, hash ->
      Bitwise.band(Bitwise.bxor(hash, byte) * 0x01000193, 0xFFFFFFFF)
    end)
    |> Integer.to_string(16)
    |> String.downcase()
    |> String.pad_leading(8, "0")
  end

  def allowed?(name, route_key) when is_binary(name) do
    not is_binary(route_key) or route_key == for_document(name)
  end
end
