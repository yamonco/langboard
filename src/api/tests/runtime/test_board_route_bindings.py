def test_card_and_change_feed_routes_have_distinct_handlers(monkeypatch):
    monkeypatch.setenv("PROJECT_NAME", "langboard")

    from langboard.routes.board import BoardApi
    from langboard_shared.core.routing import AppRouter

    endpoints = {
        route.path: route.endpoint
        for route in AppRouter.api.routes
        if route.path in {"/board/{project_uid}/cards", "/board/{project_uid}/change-feed"}
    }

    assert endpoints == {
        "/board/{project_uid}/cards": BoardApi.get_project_cards,
        "/board/{project_uid}/change-feed": BoardApi.get_board_change_feed,
    }
