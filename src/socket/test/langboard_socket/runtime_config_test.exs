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

  test "production requires explicit internal API and Graph URLs" do
    previous_api_url = System.get_env("API_INTERNAL_URL")
    previous_graph_url = System.get_env("DEFAULT_GRAPH_URL")
    previous_editor_sync = System.get_env("SOCKET_PHOENIX_EDITOR_SYNC_ENABLED")
    previous_secret = System.get_env("SECRET_KEY_BASE")
    previous_internal_secret = System.get_env("SOCKET_PHOENIX_INTERNAL_SECRET")

    on_exit(fn ->
      restore_env("API_INTERNAL_URL", previous_api_url)
      restore_env("DEFAULT_GRAPH_URL", previous_graph_url)
      restore_env("SOCKET_PHOENIX_EDITOR_SYNC_ENABLED", previous_editor_sync)
      restore_env("SECRET_KEY_BASE", previous_secret)
      restore_env("SOCKET_PHOENIX_INTERNAL_SECRET", previous_internal_secret)
    end)

    System.delete_env("API_INTERNAL_URL")
    System.delete_env("DEFAULT_GRAPH_URL")
    System.put_env("SOCKET_PHOENIX_EDITOR_SYNC_ENABLED", "false")

    assert_raise RuntimeError, ~r/API_INTERNAL_URL is required in production/, fn ->
      Config.Reader.read!(@runtime_config, env: :prod)
    end

    System.put_env("API_INTERNAL_URL", "http://api.internal:5381/")

    assert_raise RuntimeError, ~r/DEFAULT_GRAPH_URL is required in production/, fn ->
      Config.Reader.read!(@runtime_config, env: :prod)
    end

    System.put_env("DEFAULT_GRAPH_URL", "http://graph.internal:5020/")
    System.put_env("SECRET_KEY_BASE", String.duplicate("a", 64))
    System.delete_env("SOCKET_PHOENIX_INTERNAL_SECRET")
    secret_error = ~r/SOCKET_PHOENIX_INTERNAL_SECRET must contain at least 32 bytes/

    assert_raise RuntimeError, secret_error, fn ->
      Config.Reader.read!(@runtime_config, env: :prod)
    end

    System.put_env("SOCKET_PHOENIX_INTERNAL_SECRET", String.duplicate("b", 31))

    assert_raise RuntimeError, secret_error, fn ->
      Config.Reader.read!(@runtime_config, env: :prod)
    end

    System.put_env("SOCKET_PHOENIX_INTERNAL_SECRET", String.duplicate("b", 32))
    config = Config.Reader.read!(@runtime_config, env: :prod)
    assert config[:langboard_socket][:api_internal_url] == "http://api.internal:5381"
    assert config[:langboard_socket][:graph_internal_url] == "http://graph.internal:5020"
    assert config[:langboard_socket][:internal_api_secret] == String.duplicate("b", 32)
  end

  defp restore_env(name, nil), do: System.delete_env(name)
  defp restore_env(name, value), do: System.put_env(name, value)
end
