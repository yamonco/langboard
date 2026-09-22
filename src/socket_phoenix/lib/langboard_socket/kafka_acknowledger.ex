defmodule LangboardSocket.KafkaAcknowledger do
  @moduledoc false

  @behaviour Broadway.Acknowledger

  alias Broadway.Message

  def wrap(%Message{acknowledger: {BroadwayKafka.Acknowledger, ack_ref, ack_data}} = message) do
    %{message | acknowledger: {__MODULE__, ack_ref, ack_data}}
  end

  def wrap(%Message{} = message), do: message

  @impl true
  def ack(ack_ref, successful, failed) do
    if Enum.all?(failed, &dead_letter_persisted?/1) do
      BroadwayKafka.Acknowledger.ack(
        ack_ref,
        Enum.map(successful, &restore_acknowledger(&1, ack_ref)),
        Enum.map(failed, &restore_acknowledger(&1, ack_ref))
      )
    else
      stop_source_producer(ack_ref)
    end
  end

  defp dead_letter_persisted?(%Message{metadata: metadata}),
    do: Map.get(metadata, :dead_letter_persisted, false)

  defp restore_acknowledger(
         %Message{acknowledger: {__MODULE__, _ack_ref, ack_data}} = message,
         ack_ref
       ) do
    %{message | acknowledger: {BroadwayKafka.Acknowledger, ack_ref, ack_data}}
  end

  defp stop_source_producer({producer, _key}) when is_pid(producer) do
    GenStage.stop(producer, :dead_letter_unavailable, 5_000)
  catch
    :exit, _reason -> :ok
  end
end
