defmodule LangboardSocketWeb.Router do
  use LangboardSocketWeb, :router

  pipeline :api do
    plug :accepts, ["json"]
  end

  scope "/", LangboardSocketWeb do
    get "/internal/metrics", MetricsController, :index
  end

  scope "/", LangboardSocketWeb do
    pipe_through :api

    get "/health", HealthController, :health
    get "/health/live", HealthController, :live
    get "/health/ready", HealthController, :ready
    post "/editor-sync/active", EditorSyncController, :active
    post "/editor-sync/clear", EditorSyncController, :clear
    post "/editor-sync/text", EditorSyncController, :text
    post "/editor-sync/text/patch", EditorSyncController, :patch_text
    post "/editor-sync/rich/patch-request", EditorSyncController, :patch_rich
  end
end
