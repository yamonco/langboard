defmodule LangboardSocketWeb.HealthControllerTest do
  use LangboardSocketWeb.ConnCase, async: false

  alias LangboardSocket.RuntimeStatus

  test "health endpoints report a live process", %{conn: conn} do
    assert conn |> get("/health") |> response(204) == ""
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

    on_exit(fn ->
      Application.put_env(:langboard_socket, :editor_sync_enabled, previous_enabled)
      Application.put_env(:langboard_socket, :editor_sync_expected_nodes, previous_nodes)
    end)

    current_nodes = LangboardSocket.ClusterStatus.current_size()
    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, current_nodes + 1)
    Application.put_env(:langboard_socket, :editor_sync_enabled, true)

    assert conn |> get("/health/ready") |> response(503) == ""
    assert conn |> recycle() |> get("/health/live") |> response(204) == ""

    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, current_nodes)
    assert conn |> recycle() |> get("/health/ready") |> response(204) == ""

    Application.put_env(:langboard_socket, :editor_sync_enabled, false)
    Application.put_env(:langboard_socket, :editor_sync_expected_nodes, current_nodes + 1)
    assert conn |> recycle() |> get("/health/ready") |> response(204) == ""
  end
end
