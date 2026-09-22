defmodule LangboardSocket.BoardChatAcceptedRecoveryTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.BoardChatAcceptedRecovery

  defmodule RunClient do
    def list_accepted(limit, options) do
      cursor = Keyword.fetch!(options, :after_run_uid)

      send(
        Application.fetch_env!(:langboard_socket, :recovery_test_pid),
        {:scanned, limit, cursor}
      )

      case Application.fetch_env!(:langboard_socket, :recovery_test_runs) do
        {:ok, runs} ->
          page =
            runs
            |> Enum.filter(fn run -> is_nil(cursor) or run["run_uid"] > cursor end)
            |> Enum.take(limit)

          {:ok, page}

        error ->
          error
      end
    end
  end

  defmodule Worker do
    use GenServer

    def child_spec(options) do
      %{
        id: {__MODULE__, options |> Keyword.fetch!(:recovery_run) |> Map.fetch!("run_uid")},
        start: {__MODULE__, :start_link, [options]},
        restart: :temporary
      }
    end

    def start_link(options), do: GenServer.start_link(__MODULE__, options)

    @impl true
    def init(options) do
      run_uid = options |> Keyword.fetch!(:recovery_run) |> Map.fetch!("run_uid")
      allowed = Application.get_env(:langboard_socket, :recovery_test_allowed_run_uid)

      if is_nil(allowed) or allowed == run_uid do
        send(
          Application.fetch_env!(:langboard_socket, :recovery_test_pid),
          {:started, run_uid, self()}
        )

        {:ok, run_uid}
      else
        {:stop, :unavailable}
      end
    end
  end

  setup do
    Application.put_env(:langboard_socket, :recovery_test_pid, self())

    on_exit(fn ->
      Application.delete_env(:langboard_socket, :recovery_test_pid)
      Application.delete_env(:langboard_socket, :recovery_test_runs)
      Application.delete_env(:langboard_socket, :recovery_test_allowed_run_uid)
    end)

    :ok
  end

  test "limits local recovery workers and retries after a worker exits" do
    runs = [
      %{"run_uid" => "first", "project_uid" => "project", "scope_table" => "project"},
      %{"run_uid" => "second", "project_uid" => "project", "scope_table" => "project"}
    ]

    Application.put_env(:langboard_socket, :recovery_test_runs, {:ok, runs})
    supervisor = start_supervised!({DynamicSupervisor, strategy: :one_for_one, max_children: 1})

    recovery =
      start_supervised!(
        {BoardChatAcceptedRecovery,
         run_client: RunClient, run_worker: Worker, supervisor: supervisor, interval_ms: 60_000}
      )

    assert_receive {:scanned, 100, nil}
    assert_receive {:started, "first", first}
    send(recovery, :scan)
    refute_receive {:started, "second", _worker}

    Application.put_env(:langboard_socket, :recovery_test_runs, {:ok, [List.last(runs)]})
    Process.exit(first, :kill)
    Process.sleep(20)
    send(recovery, :scan)
    assert_receive {:started, "second", _second}
  end

  test "advances past a full page of unstartable accepted runs" do
    runs =
      for index <- 1..101 do
        uid = "run-#{index |> Integer.to_string() |> String.pad_leading(3, "0")}"
        %{"run_uid" => uid, "project_uid" => "project", "scope_table" => "project"}
      end

    Application.put_env(:langboard_socket, :recovery_test_runs, {:ok, runs})
    Application.put_env(:langboard_socket, :recovery_test_allowed_run_uid, "run-101")
    supervisor = start_supervised!({DynamicSupervisor, strategy: :one_for_one})

    recovery =
      start_supervised!(
        {BoardChatAcceptedRecovery,
         run_client: RunClient, run_worker: Worker, supervisor: supervisor, interval_ms: 60_000}
      )

    assert_receive {:scanned, 100, nil}
    assert :sys.get_state(recovery).cursor == "run-100"
    send(recovery, :scan)
    assert_receive {:scanned, 100, "run-100"}
    assert_receive {:started, "run-101", _worker}
  end

  test "API failure leaves the recovery scanner alive for the next interval" do
    Application.put_env(:langboard_socket, :recovery_test_runs, {:error, :unavailable})
    supervisor = start_supervised!({DynamicSupervisor, strategy: :one_for_one})

    recovery =
      start_supervised!(
        {BoardChatAcceptedRecovery,
         run_client: RunClient, run_worker: Worker, supervisor: supervisor, interval_ms: 60_000}
      )

    assert_receive {:scanned, 100, nil}
    assert Process.alive?(recovery)
    send(recovery, :scan)
    assert_receive {:scanned, 100, nil}
  end
end
