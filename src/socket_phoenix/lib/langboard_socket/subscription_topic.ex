defmodule LangboardSocket.SubscriptionTopic do
  @moduledoc false

  def name(topic, topic_id) when is_binary(topic) and is_binary(topic_id),
    do: topic <> ":" <> topic_id
end
