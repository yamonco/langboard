defmodule LangboardSocketWeb.SocketHandler.Subscriptions do
  @moduledoc false

  import LangboardSocketWeb.SocketHandler.Outbound,
    only: [push_frame: 2, push_payloads: 2]

  alias LangboardSocket.RealtimeContract, as: Contract
  alias LangboardSocket.SubscriptionTopic
  alias LangboardSocketWeb.SocketHandler.State
  alias LangboardSocketWeb.Telemetry

  @board_topic Contract.topic!("board")
  @max_topic_ids Contract.protocol_limit!("max_topic_ids")
  @max_topic_id_bytes Contract.protocol_limit!("max_topic_id_bytes")

  def handle_subscribe(%{"topic" => topic, "topic_id" => topic_ids}, state)
      when is_binary(topic) do
    cond do
      not valid_topic_ids?(topic_ids) ->
        {:stop, :normal, Contract.close_code!("invalid_data"), state}

      not Contract.valid_topic?(topic) ->
        push_frame(encode_message(Contract.event!("subscribed"), topic, []), state)

      true ->
        requested_ids = normalize_topic_ids(topic_ids)

        case state.authorization_client.authorize_subscriptions(
               state.authorization_token,
               topic,
               requested_ids
             ) do
          {:ok, accepted} ->
            new_subscriptions = MapSet.new(accepted, &{topic, &1})

            rejected =
              requested_ids
              |> MapSet.new(&{topic, &1})
              |> MapSet.difference(new_subscriptions)

            state = remove(state, rejected)

            new_subscriptions
            |> MapSet.difference(state.subscriptions)
            |> Enum.each(&subscribe/1)

            added_count =
              new_subscriptions
              |> MapSet.difference(state.subscriptions)
              |> MapSet.size()

            Telemetry.emit_subscription_change(added_count)

            next_state = %{
              state
              | subscriptions: MapSet.union(state.subscriptions, new_subscriptions)
            }

            push_frame(
              encode_message(Contract.event!("subscribed"), topic, accepted),
              next_state
            )

          {:error, reason} ->
            {:stop, :normal, authorization_close_code(reason), state}
        end
    end
  end

  def handle_subscribe(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  def handle_unsubscribe(%{"topic" => topic, "topic_id" => topic_ids}, state)
      when is_binary(topic) do
    if valid_topic_ids?(topic_ids) do
      requested_ids = normalize_topic_ids(topic_ids)
      requested = MapSet.new(requested_ids, &{topic, &1})
      next_state = remove(state, requested)

      push_frame(
        encode_message(Contract.event!("unsubscribed"), topic, requested_ids),
        next_state
      )
    else
      {:stop, :normal, Contract.close_code!("invalid_data"), state}
    end
  end

  def handle_unsubscribe(_payload, state),
    do: {:stop, :normal, Contract.close_code!("invalid_data"), state}

  def revoke(topic, topic_id, state) do
    next_state = remove(state, MapSet.new([{topic, topic_id}]))

    push_payloads(
      [
        %{
          event: Contract.event!("subscription_revoked"),
          topic: topic,
          topic_id: topic_id,
          data: %{}
        },
        %{event: Contract.event!("unsubscribed"), topic: topic, topic_id: [topic_id]}
      ],
      next_state
    )
  end

  def handle_board_authorization_error(topic_id, close_code, state) do
    if close_code == Contract.close_code!("forbidden") and
         MapSet.member?(state.subscriptions, {@board_topic, topic_id}) do
      revoke(@board_topic, topic_id, state)
    else
      {:stop, :normal, close_code, state}
    end
  end

  def authorize_board_command(topic_id, state) do
    with true <- MapSet.member?(state.subscriptions, {@board_topic, topic_id}),
         {:ok, accepted} <-
           state.authorization_client.authorize_subscriptions(
             state.authorization_token,
             @board_topic,
             [topic_id]
           ),
         true <- topic_id in accepted do
      :ok
    else
      false -> {:error, Contract.close_code!("forbidden")}
      {:error, reason} -> {:error, authorization_close_code(reason)}
    end
  end

  def subscribe({topic, topic_id}) do
    Phoenix.PubSub.subscribe(LangboardSocket.PubSub, SubscriptionTopic.name(topic, topic_id))
  end

  def encode_message(event, topic, topic_ids) do
    {:text, Jason.encode!(%{event: event, topic: topic, topic_id: topic_ids})}
  end

  def authorization_close_code(:expired_token), do: Contract.close_code!("expired_token")
  def authorization_close_code(:unauthorized), do: Contract.close_code!("unauthorized")
  def authorization_close_code(_reason), do: Contract.close_code!("internal_error")

  defp remove(state, requested) do
    removed = MapSet.intersection(state.subscriptions, requested)
    Enum.each(removed, &unsubscribe/1)
    Telemetry.emit_subscription_change(-MapSet.size(removed))

    state
    |> Map.put(:subscriptions, MapSet.difference(state.subscriptions, removed))
    |> State.cancel_board_queries_for(removed)
  end

  defp normalize_topic_ids(topic_id) when is_binary(topic_id) and topic_id != "", do: [topic_id]

  defp normalize_topic_ids(topic_ids) when is_list(topic_ids) do
    Enum.filter(topic_ids, &(is_binary(&1) and &1 != ""))
  end

  defp normalize_topic_ids(_topic_ids), do: []

  defp valid_topic_ids?(topic_id) when is_binary(topic_id),
    do: valid_topic_id?(topic_id)

  defp valid_topic_ids?(topic_ids) when is_list(topic_ids) do
    length(topic_ids) <= @max_topic_ids and Enum.all?(topic_ids, &valid_topic_id?/1)
  end

  defp valid_topic_ids?(_topic_ids), do: false

  defp valid_topic_id?(topic_id) when is_binary(topic_id) do
    topic_id != "" and byte_size(topic_id) <= @max_topic_id_bytes
  end

  defp valid_topic_id?(_topic_id), do: false

  defp unsubscribe({topic, topic_id}) do
    Phoenix.PubSub.unsubscribe(LangboardSocket.PubSub, SubscriptionTopic.name(topic, topic_id))
  end
end
