defmodule LangboardSocket.SocketEventProjectorTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.SocketEventProjector

  test "preserves Node data-key selection and custom-data precedence" do
    queue_data = %{
      "data" => %{"card" => %{"uid" => "card-1"}, "ignored" => true},
      "publish_models" => [
        %{
          "topic" => "board",
          "topic_id" => "board-1",
          "event" => "board:card:updated",
          "data_keys" => "card",
          "custom_data" => %{"card" => "override", "source" => "test"}
        },
        %{
          "topic" => "global",
          "topic_id" => "all",
          "event" => "global:event",
          "data_keys" => []
        }
      ]
    }

    assert {:ok, frames} = SocketEventProjector.project(queue_data)

    assert frames == [
             %{
               "topic" => "board",
               "topic_id" => "board-1",
               "event" => "board:card:updated",
               "data" => %{"card" => "override", "source" => "test"}
             },
             %{
               "topic" => "global",
               "topic_id" => "all",
               "event" => "global:event",
               "data" => %{}
             }
           ]
  end

  test "accepts the single publish-model shape" do
    assert {:ok, [%{"data" => %{"value" => 1}}]} =
             SocketEventProjector.project(%{
               "data" => %{"value" => 1},
               "publish_models" => %{
                 "topic" => "board",
                 "topic_id" => "board-1",
                 "event" => "event",
                 "data_keys" => ["value"]
               }
             })
  end

  test "rejects invalid publish models without partial fanout" do
    assert {:error, :invalid_publish_model} =
             SocketEventProjector.project(%{
               "data" => %{},
               "publish_models" => [
                 %{"topic" => "unknown", "topic_id" => "id", "event" => "event"}
               ]
             })
  end
end
