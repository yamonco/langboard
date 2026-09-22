defmodule LangboardSocket.RuntimeConfigTest do
  use ExUnit.Case, async: false

  @runtime_config Path.expand("../../config/runtime.exs", __DIR__)

  test "editor node count defaults only while editor sync is disabled" do
    previous_count = System.get_env("SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES")
    previous_enabled = System.get_env("SOCKET_PHOENIX_EDITOR_SYNC_ENABLED")

    on_exit(fn ->
      restore_env("SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES", previous_count)
      restore_env("SOCKET_PHOENIX_EDITOR_SYNC_ENABLED", previous_enabled)
    end)

    System.put_env("SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES", "")
    System.put_env("SOCKET_PHOENIX_EDITOR_SYNC_ENABLED", "false")

    config = Config.Reader.read!(@runtime_config, env: :test)
    assert config[:langboard_socket][:editor_sync_expected_nodes] == 1

    System.put_env("SOCKET_PHOENIX_EDITOR_SYNC_ENABLED", "true")

    assert_raise RuntimeError, ~r/EDITOR_SYNC_EXPECTED_NODES is required/, fn ->
      Config.Reader.read!(@runtime_config, env: :prod)
    end

    System.put_env("SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES", "2")
    config = Config.Reader.read!(@runtime_config, env: :test)
    assert config[:langboard_socket][:editor_sync_expected_nodes] == 2
  end

  defp restore_env(name, nil), do: System.delete_env(name)
  defp restore_env(name, value), do: System.put_env(name, value)
end
