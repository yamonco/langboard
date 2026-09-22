defmodule LangboardSocket.SocketEventProjector do
  @moduledoc false

  alias LangboardSocket.RealtimeContract, as: Contract

  def project(%{"data" => data, "publish_models" => publish_models}) when is_map(data) do
    publish_models
    |> normalize_publish_models()
    |> project_models(data)
  end

  def project(_data), do: {:error, :invalid_socket_publish_data}

  defp normalize_publish_models(publish_models) when is_map(publish_models),
    do: {:ok, [publish_models]}

  defp normalize_publish_models(publish_models) when is_list(publish_models),
    do: {:ok, publish_models}

  defp normalize_publish_models(_publish_models), do: {:error, :invalid_publish_models}

  defp project_models({:error, reason}, _data), do: {:error, reason}

  defp project_models({:ok, publish_models}, data) do
    Enum.reduce_while(publish_models, {:ok, []}, fn publish_model, {:ok, frames} ->
      case project_model(publish_model, data) do
        {:ok, frame} -> {:cont, {:ok, [frame | frames]}}
        {:error, reason} -> {:halt, {:error, reason}}
      end
    end)
    |> case do
      {:ok, frames} -> {:ok, Enum.reverse(frames)}
      error -> error
    end
  end

  defp project_model(
         %{"topic" => topic, "topic_id" => topic_id, "event" => event} = publish_model,
         data
       )
       when is_binary(topic) and is_binary(topic_id) and topic_id != "" and is_binary(event) and
              event != "" do
    with true <- Contract.valid_topic?(topic),
         {:ok, data_keys} <- normalize_data_keys(Map.get(publish_model, "data_keys")),
         {:ok, custom_data} <- normalize_custom_data(Map.get(publish_model, "custom_data")) do
      {:ok,
       %{
         "event" => event,
         "topic" => topic,
         "topic_id" => topic_id,
         "data" => data |> Map.take(data_keys) |> Map.merge(custom_data)
       }}
    else
      _reason -> {:error, :invalid_publish_model}
    end
  end

  defp project_model(_publish_model, _data), do: {:error, :invalid_publish_model}

  defp normalize_data_keys(nil), do: {:ok, []}
  defp normalize_data_keys(""), do: {:ok, []}
  defp normalize_data_keys(data_key) when is_binary(data_key), do: {:ok, [data_key]}

  defp normalize_data_keys(data_keys) when is_list(data_keys) do
    if Enum.all?(data_keys, &is_binary/1),
      do: {:ok, data_keys},
      else: {:error, :invalid_data_keys}
  end

  defp normalize_data_keys(_data_keys), do: {:error, :invalid_data_keys}

  defp normalize_custom_data(nil), do: {:ok, %{}}
  defp normalize_custom_data(custom_data) when is_map(custom_data), do: {:ok, custom_data}
  defp normalize_custom_data(_custom_data), do: {:error, :invalid_custom_data}
end
