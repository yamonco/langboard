defmodule LangboardSocketWeb.HealthControllerTest do
  use LangboardSocketWeb.ConnCase, async: false

  alias LangboardSocket.RuntimeStatus

  test "health endpoints report a live process", %{conn: conn} do
    health = get(conn, "/health")
    assert response(health, 204) == ""
    assert get_resp_header(health, "x-langboard-socket-runtime") == ["phoenix"]

    assert get_resp_header(health, "x-langboard-socket-version") == [
             :langboard_socket |> Application.spec(:vsn) |> to_string()
           ]

    assert conn |> get("/health/live") |> response(204) == ""
  end

  test "readiness rejects new traffic while the runtime drains", %{conn: conn} do
    on_exit(fn -> RuntimeStatus.reset() end)

    assert conn |> get("/health/ready") |> response(204) == ""
    assert :ok = RuntimeStatus.begin_drain()
    assert conn |> recycle() |> get("/health/ready") |> response(503) == ""
    assert conn |> recycle() |> get("/health/live") |> response(204) == ""
  end

  test "readiness rejects traffic when the API contract is incompatible", %{conn: conn} do
    on_exit(fn -> Process.delete(:authorization_ready) end)

    Process.put(:authorization_ready, false)
    assert conn |> get("/health/ready") |> response(503) == ""
    assert conn |> recycle() |> get("/health/live") |> response(204) == ""

    Process.put(:authorization_ready, true)
    assert conn |> recycle() |> get("/health/ready") |> response(204) == ""
  end

  test "readiness requires the editor owner cohort when editor sync is enabled", %{conn: conn} do
    previous_enabled = Application.fetch_env!(:langboard_socket, :editor_sync_enabled)
    previous_nodes = Application.fetch_env!(:langboard_socket, :editor_sync_expected_nodes)
    previous_directory = Application.fetch_env!(:langboard_socket, :editor_sync_directory)

    directory =
      Path.join(System.tmp_dir!(), "langboard-ready-#{System.unique_integer([:positive])}")

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_enabled, previous_enabled)
      Application.put_env(:langboard_socket, :editor_sync_expected_nodes, previous_nodes)
      Application.put_env(:langboard_socket, :editor_sync_directory, previous_directory)
      File.rm_rf!(directory)
    end)

    assert :ok = File.mkdir_p(directory)
    current_nodes = LangboardSocket.ClusterStatus.current_size()
    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, current_nodes + 1)
    Application.put_env(:langboard_socket, :editor_sync_enabled, true)
    Application.put_env(:langboard_socket, :editor_sync_directory, directory)

    assert conn |> get("/health/ready") |> response(503) == ""
    assert conn |> recycle() |> get("/health/live") |> response(204) == ""

    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, current_nodes)
    assert conn |> recycle() |> get("/health/ready") |> response(204) == ""

    assert :ok = File.rmdir(directory)
    assert conn |> recycle() |> get("/health/ready") |> response(503) == ""
    assert conn |> recycle() |> get("/health/live") |> response(204) == ""

    assert :ok = File.mkdir_p(directory)
    assert conn |> recycle() |> get("/health/ready") |> response(204) == ""

    Application.put_env(:langboard_socket, :editor_sync_enabled, false)
    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, current_nodes + 1)
    assert :ok = File.rmdir(directory)
    assert conn |> recycle() |> get("/health/ready") |> response(204) == ""
  end
end
