defmodule LangboardSocketWeb.MetricsControllerTest do
  use LangboardSocketWeb.ConnCase, async: false

  setup do
    previous = Application.fetch_env!(:langboard_socket, :internal_api_secret)
    secret = String.duplicate("metrics-test-secret", 3)
    Application.put_env(:langboard_socket, :internal_api_secret, secret)
    on_exit(fn -> Application.put_env(:langboard_socket, :internal_api_secret, previous) end)
    %{secret: secret}
  end

  test "scrapes require exactly one valid internal credential", %{conn: conn, secret: secret} do
    assert conn |> get("/internal/metrics") |> response(401) == ""

    assert conn
           |> put_req_header("x-socket-internal-secret", "wrong")
           |> get("/internal/metrics")
           |> response(401) == ""

    duplicate = %{conn | req_headers: List.duplicate({"x-socket-internal-secret", secret}, 2)}
    assert duplicate |> get("/internal/metrics") |> response(401) == ""

    Application.put_env(:langboard_socket, :internal_api_secret, "")

    assert conn
           |> put_req_header("x-socket-internal-secret", "")
           |> get("/internal/metrics")
           |> response(401) == ""
  end

  test "exports VM and sampled mailboxes without process identity labels", %{
    conn: conn,
    secret: secret
  } do
    pid = spawn(fn -> receive do: (:stop -> :ok) end)
    on_exit(fn -> send(pid, :stop) end)
    Enum.each(1..5, fn _ -> send(pid, :queued) end)
    LangboardSocketWeb.Telemetry.emit_runtime_measurements()
    :telemetry.execute([:vm, :memory], %{total: 123_456, binary: 123, processes: 456}, %{})

    conn =
      conn
      |> put_req_header("x-socket-internal-secret", secret)
      |> put_req_header("accept", "text/plain")
      |> get("/internal/metrics")

    body = response(conn, 200)
    assert body =~ "vm_memory_total 123456"
    assert body =~ "langboard_socket_runtime_uptime_seconds"
    assert body =~ "langboard_socket_runtime_process_count"
    [_, maximum] = Regex.run(~r/langboard_socket_runtime_mailbox_max (\d+)/, body)
    assert String.to_integer(maximum) >= 5
    refute body =~ inspect(pid)
    assert get_resp_header(conn, "cache-control") == ["no-store"]
  end

  test "connection changes export as a gauge and preserve decrements" do
    name = :metrics_gauge_test

    start_supervised!(
      {TelemetryMetricsPrometheus.Core,
       name: name,
       start_async: false,
       metrics: [
         Telemetry.Metrics.sum("metrics_test.connections.count",
           reporter_options: [prometheus_type: :gauge]
         )
       ]}
    )

    :telemetry.execute([:metrics_test, :connections], %{count: 2}, %{})
    :telemetry.execute([:metrics_test, :connections], %{count: -1}, %{})
    body = TelemetryMetricsPrometheus.Core.scrape(name)
    assert body =~ "# TYPE metrics_test_connections_count gauge"
    assert body =~ "metrics_test_connections_count 1"
  end

  test "metric definitions do not retain individual observations between scrapes" do
    for metric <- LangboardSocketWeb.Telemetry.metrics() do
      assert metric.__struct__ in [
               Telemetry.Metrics.Counter,
               Telemetry.Metrics.Sum,
               Telemetry.Metrics.LastValue
             ]
    end
  end

  test "authorization metrics expose bounded route and result labels without request identity" do
    reporter = :authorization_metrics_reporter

    metrics =
      Enum.filter(LangboardSocketWeb.Telemetry.metrics(), fn metric ->
        metric.name in [
          [:langboard_socket, :authorization, :request, :count],
          [:langboard_socket, :authorization, :request, :duration_microseconds]
        ]
      end)

    assert length(metrics) == 2

    start_supervised!(
      {TelemetryMetricsPrometheus.Core, name: reporter, start_async: false, metrics: metrics}
    )

    :telemetry.execute(
      [:langboard_socket, :authorization, :request],
      %{count: 1, duration_microseconds: 25_000},
      %{route: "/auth/socket/editor-document", result: :success}
    )

    body = TelemetryMetricsPrometheus.Core.scrape(reporter)
    labels = ~s(result="success",route="/auth/socket/editor-document")

    assert body =~ "langboard_socket_authorization_request_count{#{labels}} 1"

    assert body =~
             "langboard_socket_authorization_request_duration_microseconds{#{labels}} 25000"

    refute body =~ "token"
    refute body =~ "document_name"
  end

  test "worker gauges sample live supervisors and return to baseline after termination" do
    reporter = :worker_snapshot_reporter

    specification =
      {TelemetryMetricsPrometheus.Core,
       name: reporter,
       start_async: false,
       metrics: [
         Telemetry.Metrics.last_value("langboard_socket.runtime.workers.active", tags: [:kind]),
         Telemetry.Metrics.last_value("langboard_socket.runtime.workers.available", tags: [:kind])
       ]}

    start_supervised!(specification)

    for {supervisor, kind} <- [
          {LangboardSocket.BoardChatRunSupervisor, "board_chat"},
          {LangboardSocket.EditorRunSupervisor, "editor_ai"},
          {LangboardSocket.EditorDocumentSupervisor, "editor_document"}
        ] do
      baseline = DynamicSupervisor.count_children(supervisor).active

      {:ok, pid} =
        DynamicSupervisor.start_child(supervisor, {Task, fn -> receive do: (:stop -> :ok) end})

      on_exit(fn -> DynamicSupervisor.terminate_child(supervisor, pid) end)

      for attempt <- 1..2 do
        if attempt == 2 do
          stop_supervised!(reporter)
          start_supervised!(specification)
        end

        LangboardSocketWeb.Telemetry.emit_worker_measurements()
        body = TelemetryMetricsPrometheus.Core.scrape(reporter)
        assert body =~ "langboard_socket_runtime_workers_active{kind=\"#{kind}\"} #{baseline + 1}"
        assert body =~ "langboard_socket_runtime_workers_available{kind=\"#{kind}\"} 1"
        refute body =~ inspect(pid)
      end

      :ok = DynamicSupervisor.terminate_child(supervisor, pid)
      LangboardSocketWeb.Telemetry.emit_worker_measurements()

      assert TelemetryMetricsPrometheus.Core.scrape(reporter) =~
               "langboard_socket_runtime_workers_active{kind=\"#{kind}\"} #{baseline}"
    end
  end

  test "task gauges sample bounded task supervisors and return to baseline" do
    reporter = :task_snapshot_reporter

    start_supervised!(
      {TelemetryMetricsPrometheus.Core,
       name: reporter,
       start_async: false,
       metrics: [
         Telemetry.Metrics.last_value("langboard_socket.runtime.tasks.active", tags: [:kind]),
         Telemetry.Metrics.last_value("langboard_socket.runtime.tasks.available", tags: [:kind])
       ]}
    )

    for {supervisor, kind} <- [
          {LangboardSocket.CommandTaskSupervisor, "command"},
          {LangboardSocket.BoardChatGraphTaskSupervisor, "graph_stream"}
        ] do
      baseline = supervisor |> Task.Supervisor.children() |> length()
      {:ok, pid} = Task.Supervisor.start_child(supervisor, fn -> receive do: (:stop -> :ok) end)
      on_exit(fn -> Task.Supervisor.terminate_child(supervisor, pid) end)

      LangboardSocketWeb.Telemetry.emit_task_measurements()
      body = TelemetryMetricsPrometheus.Core.scrape(reporter)
      assert body =~ "langboard_socket_runtime_tasks_active{kind=\"#{kind}\"} #{baseline + 1}"
      assert body =~ "langboard_socket_runtime_tasks_available{kind=\"#{kind}\"} 1"
      refute body =~ inspect(pid)

      :ok = Task.Supervisor.terminate_child(supervisor, pid)
      LangboardSocketWeb.Telemetry.emit_task_measurements()

      assert TelemetryMetricsPrometheus.Core.scrape(reporter) =~
               "langboard_socket_runtime_tasks_active{kind=\"#{kind}\"} #{baseline}"
    end
  end

  test "an unavailable worker supervisor does not disable subsequent measurements" do
    supervisor = LangboardSocket.EditorRunSupervisor
    assert DynamicSupervisor.count_children(supervisor).active == 0
    on_exit(fn -> Supervisor.restart_child(LangboardSocket.Supervisor, supervisor) end)

    :ok = Supervisor.terminate_child(LangboardSocket.Supervisor, supervisor)
    LangboardSocketWeb.Telemetry.emit_worker_measurements()

    assert TelemetryMetricsPrometheus.Core.scrape() =~
             "langboard_socket_runtime_workers_available{kind=\"editor_ai\"} 0"

    assert {:ok, _pid} = Supervisor.restart_child(LangboardSocket.Supervisor, supervisor)
    LangboardSocketWeb.Telemetry.emit_worker_measurements()

    body = TelemetryMetricsPrometheus.Core.scrape()
    assert body =~ "langboard_socket_runtime_workers_available{kind=\"editor_ai\"} 1"
    assert body =~ "langboard_socket_runtime_workers_active{kind=\"editor_ai\"} 0"
  end
end
