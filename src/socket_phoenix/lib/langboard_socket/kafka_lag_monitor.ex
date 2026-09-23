defmodule LangboardSocket.KafkaLagMonitor do
  @moduledoc false

  use GenServer

  def start_link(options) do
    name = Keyword.get(options, :name, __MODULE__)
    GenServer.start_link(__MODULE__, options, name: name)
  end

  def ready? do
    not LangboardSocket.KafkaIngress.enabled?() or ready?(__MODULE__)
  end

  def ready?(server) do
    GenServer.call(server, :ready?)
  catch
    :exit, _reason -> false
  end

  @doc false
  def refresh(server), do: GenServer.call(server, :refresh)

  @impl true
  def init(options) do
    state = %{
      config: Keyword.fetch!(options, :config),
      fetch_lag: Keyword.get(options, :fetch_lag, &LangboardSocket.KafkaOffsetClient.lag/1),
      poll_interval_ms: Keyword.fetch!(options, :poll_interval_ms),
      ready?: false
    }

    schedule_refresh(Keyword.get(options, :initial_delay_ms, 0))
    {:ok, state}
  end

  @impl true
  def handle_call(:ready?, _from, state), do: {:reply, state.ready?, state}

  def handle_call(:refresh, _from, state) do
    {result, state} = refresh_state(state)
    {:reply, result, state}
  end

  @impl true
  def handle_info(:refresh, state) do
    {_result, state} = refresh_state(state)
    schedule_refresh(state.poll_interval_ms)
    {:noreply, state}
  end

  defp refresh_state(state) do
    case state.fetch_lag.(state.config) do
      {:ok, lag} when is_integer(lag) and lag >= 0 ->
        emit_measurement(lag, true)
        {{:ok, lag}, %{state | ready?: state.ready? or lag == 0}}

      _error ->
        emit_measurement(0, false)
        {{:error, :unavailable}, %{state | ready?: false}}
    end
  end

  defp emit_measurement(lag, available?) do
    :telemetry.execute(
      [:langboard_socket, :kafka, :lag],
      %{count: lag, available: if(available?, do: 1, else: 0)},
      %{}
    )
  end

  defp schedule_refresh(delay_ms), do: Process.send_after(self(), :refresh, delay_ms)
end
