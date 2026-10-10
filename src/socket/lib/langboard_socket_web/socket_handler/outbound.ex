defmodule LangboardSocketWeb.SocketHandler.Outbound do
  @moduledoc false

  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocketWeb.Telemetry

  def push_payload(payload, state) do
    queue_length = message_queue_length()

    if queue_length >= state.max_outbound_queue do
      Telemetry.emit_slow_client(queue_length)
      {:stop, :normal, Contract.close_code!("try_again_later"), state}
    else
      encoded = Jason.encode!(payload)
      Telemetry.emit_outbound(byte_size(encoded), queue_length)
      {:push, {:text, encoded}, state}
    end
  end

  def push_payloads(payloads, state) do
    queue_length = message_queue_length()

    if queue_length + length(payloads) > state.max_outbound_queue do
      Telemetry.emit_slow_client(queue_length)
      {:stop, :normal, Contract.close_code!("try_again_later"), state}
    else
      messages =
        Enum.map(payloads, fn payload ->
          encoded = Jason.encode!(payload)
          Telemetry.emit_outbound(byte_size(encoded), queue_length)
          {:text, encoded}
        end)

      {:push, messages, state}
    end
  end

  defp message_queue_length do
    case Process.info(self(), :message_queue_len) do
      {:message_queue_len, length} -> length
      nil -> 0
    end
  end

  def push_frame({_opcode, payload} = frame, state) do
    queue_length = message_queue_length()

    if queue_length >= state.max_outbound_queue do
      Telemetry.emit_slow_client(queue_length)
      {:stop, :normal, Contract.close_code!("try_again_later"), state}
    else
      Telemetry.emit_outbound(byte_size(payload), queue_length)
      {:push, frame, state}
    end
  end

  def push_frames(frames, state) do
    queue_length = message_queue_length()

    if queue_length + length(frames) > state.max_outbound_queue do
      Telemetry.emit_slow_client(queue_length)
      {:stop, :normal, Contract.close_code!("try_again_later"), state}
    else
      Enum.each(frames, fn {_opcode, payload} ->
        Telemetry.emit_outbound(byte_size(payload), queue_length)
      end)

      {:push, frames, state}
    end
  end
end
