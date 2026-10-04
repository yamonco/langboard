defmodule LangboardSocket.TestBotStatusClient do
  @moduledoc false

  @status_map %{"project_column" => %{"column-uid" => ["bot-uid"]}, "card" => %{}}

  def fetch("hold:" <> _project_uid) do
    receive do
      :release -> {:ok, @status_map}
    end
  end

  def fetch("crash:" <> _project_uid), do: raise("bot status client failed")
  def fetch("fail:" <> _project_uid), do: {:error, :unavailable}
  def fetch(_project_uid), do: {:ok, @status_map}
end
