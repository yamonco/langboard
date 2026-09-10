from langboard_shared.domain.services.factory.BotService import ActionSuggestionCandidate, BotDraft, BotService


def test_generated_action_suggestions_are_selected_from_the_authorized_catalog() -> None:
    candidates: list[ActionSuggestionCandidate] = [
        {
            "source": "api",
            "name": "create_card",
            "label": "create_card",
            "description": "Create a card",
            "api_names": ["create_card"],
            "risk": "medium",
            "confidence": 0,
            "already_selected": False,
            "reason": "",
        }
    ]

    suggestions = BotService.select_generated_action_candidates(
        candidates,
        [
            {"ref": "api:create_card", "reason": "The prompt asks to create cards.", "confidence": 120},
            {"ref": "api:create_card", "reason": "Duplicate", "confidence": 10},
            {"ref": "api:delete_project", "reason": "Unknown", "confidence": 90},
        ],
        limit=8,
    )

    assert suggestions == [
        {
            **candidates[0],
            "reason": "The prompt asks to create cards.",
            "confidence": 100,
        }
    ]


def test_generated_bot_draft_cannot_replace_existing_credentials() -> None:
    fallback: BotDraft = {
        "bot_name": "Assistant",
        "bot_uname": "assistant",
        "value_patch": {"system_prompt": "Original"},
        "suggestions": [],
    }

    service = object.__new__(BotService)
    draft = service.merge_generated_bot_draft(
        fallback,
        {
            "value_patch": {"system_prompt": "Generated prompt", "api_key": "replacement"},
            "suggestions": [],
        },
        [],
    )

    assert draft["bot_name"] == "Assistant"
    assert draft["value_patch"] == {"system_prompt": "Generated prompt"}
    assert "api_key" not in draft["value_patch"]
