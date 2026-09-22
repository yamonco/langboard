defmodule LangboardSocket.TestOllamaClient do
  @moduledoc false

  def execute(token, action, data) do
    send(
      Application.fetch_env!(:langboard_socket, :ollama_test_owner),
      {:ollama_request, self(), token, action, data}
    )

    case data["model"] do
      "hold" ->
        receive do
          :release -> :ok
        end

      "fail" ->
        {:error, :unavailable}

      "denied" ->
        {:error, :forbidden}

      _ ->
        :ok
    end
  end
end
