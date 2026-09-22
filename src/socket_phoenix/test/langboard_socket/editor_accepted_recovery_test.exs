defmodule LangboardSocket.EditorAcceptedRecoveryTest do
  use ExUnit.Case, async: false

  alias LangboardSocket.EditorAcceptedRecovery

  defmodule RunClient do
    def list_accepted(limit, options) do
      cursor = Keyword.fetch!(options, :after_run_uid)

      send(
        Application.fetch_env!(:langboard_socket, :editor_recovery_test_pid),
        {:scanned, limit, cursor}
      )

      case Application.fetch_env!(:langboard_socket, :editor_recovery_test_runs) do
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
      run_uid = options |> Keyword.fetch!(:recovery_run) |> Map.fetch!("run_uid")

      %{
        id: {__MODULE__, run_uid},
        start: {__MODULE__, :start_link, [options]},
        restart: :temporary
      }
    end

    def start_link(options), do: GenServer.start_link(__MODULE__, options)

    @impl true
    def init(options) do
      run_uid = options |> Keyword.fetch!(:recovery_run) |> Map.fetch!("run_uid")
      allowed = Application.get_env(:langboard_socket, :editor_recovery_allowed_run_uid)

      if is_nil(allowed) or allowed == run_uid do
        send(Application.fetch_env!(:langboard_socket, :editor_recovery_test_pid), {
          :started,
          run_uid,
          options,
          self()
        })

        {:ok, run_uid}
      else
        {:stop, :unavailable}
      end
    end
  end

  setup do
    Application.put_env(:langboard_socket, :editor_recovery_test_pid, self())

    on_exit(fn ->
      Application.delete_env(:langboard_socket, :editor_recovery_test_pid)
      Application.delete_env(:langboard_socket, :editor_recovery_test_runs)
      Application.delete_env(:langboard_socket, :editor_recovery_allowed_run_uid)
    end)

    :ok
  end

  test "starts saved editor runs without a browser token and advances past failed starts" do
    page_size =
      min(Application.fetch_env!(:langboard_socket, :socket_max_in_flight_commands), 100)

    runs =
      for index <- 1..(page_size + 1) do
        uid = "run-#{index |> Integer.to_string() |> String.pad_leading(3, "0")}"

        %{
          "run_uid" => uid,
          "project_uid" => "project",
          "task_id" => "task-#{index}",
          "kind" => "editor_chat"
        }
      end

    last_run = List.last(runs)
    Application.put_env(:langboard_socket, :editor_recovery_test_runs, {:ok, runs})
    Application.put_env(:langboard_socket, :editor_recovery_allowed_run_uid, last_run["run_uid"])
    supervisor = start_supervised!({DynamicSupervisor, strategy: :one_for_one})

    recovery =
      start_supervised!(
        {EditorAcceptedRecovery,
         run_client: RunClient, run_worker: Worker, supervisor: supervisor, interval_ms: 60_000}
      )

    assert_receive {:scanned, ^page_size, nil}
    assert :sys.get_state(recovery).cursor == Enum.at(runs, page_size - 1)["run_uid"]
    send(recovery, :scan)
    assert_receive {:scanned, ^page_size, _cursor}
    assert_receive {:started, run_uid, options, _worker}
    assert run_uid == last_run["run_uid"]
    assert options[:token] == nil
    assert options[:receiver] == nil
    assert options[:command]["task_id"] == last_run["task_id"]
  end

  test "holds local capacity and retries after a worker exits" do
    first = %{
      "run_uid" => "first",
      "project_uid" => "project",
      "task_id" => "one",
      "kind" => "editor_chat"
    }

    second = %{
      "run_uid" => "second",
      "project_uid" => "project",
      "task_id" => "two",
      "kind" => "editor_copilot"
    }

    Application.put_env(:langboard_socket, :editor_recovery_test_runs, {:ok, [first, second]})
    supervisor = start_supervised!({DynamicSupervisor, strategy: :one_for_one, max_children: 1})

    recovery =
      start_supervised!(
        {EditorAcceptedRecovery,
         run_client: RunClient, run_worker: Worker, supervisor: supervisor, interval_ms: 60_000}
      )

    assert_receive {:started, "first", _, first_worker}
    send(recovery, :scan)
    refute_receive {:started, "second", _, _}
    Application.put_env(:langboard_socket, :editor_recovery_test_runs, {:ok, [second]})
    Process.exit(first_worker, :kill)
    Process.sleep(20)
    send(recovery, :scan)
    assert_receive {:started, "second", _, _}
  end

  test "a repeated scan keeps the existing worker and monitor" do
    run = %{
      "run_uid" => "run-uid",
      "project_uid" => "project",
      "task_id" => "task",
      "kind" => "editor_chat"
    }

    Application.put_env(:langboard_socket, :editor_recovery_test_runs, {:ok, [run]})
    supervisor = start_supervised!({DynamicSupervisor, strategy: :one_for_one})

    recovery =
      start_supervised!(
        {EditorAcceptedRecovery,
         run_client: RunClient, run_worker: Worker, supervisor: supervisor, interval_ms: 60_000}
      )

    assert_receive {:started, "run-uid", _, worker}
    active = :sys.get_state(recovery).active
    assert map_size(active) == 1

    send(recovery, :scan)
    assert :sys.get_state(recovery).cursor == nil
    send(recovery, :scan)
    assert :sys.get_state(recovery).active == active
    assert DynamicSupervisor.count_children(supervisor).active == 1
    assert Process.alive?(worker)
    refute_receive {:started, _, _, _}
  end

  test "backend outage leaves the scanner alive for a later retry" do
    Application.put_env(:langboard_socket, :editor_recovery_test_runs, {:error, :unavailable})
    supervisor = start_supervised!({DynamicSupervisor, strategy: :one_for_one})

    recovery =
      start_supervised!(
        {EditorAcceptedRecovery,
         run_client: RunClient, run_worker: Worker, supervisor: supervisor, interval_ms: 60_000}
      )

    assert_receive {:scanned, _limit, nil}
    assert Process.alive?(recovery)
    send(recovery, :scan)
    assert_receive {:scanned, _limit, nil}
  end
end
