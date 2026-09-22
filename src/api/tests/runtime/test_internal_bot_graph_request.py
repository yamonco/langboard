from json import dumps as json_dumps
import pytest
from langboard_shared.ai.InternalBotGraphRequest import (
    build_board_chat_bot_request,
    build_editor_graph_request,
    build_internal_bot_graph_request,
    build_internal_bot_langflow_request,
)
from langboard_shared.core.security import AuthSecurity
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBot import InternalBot, InternalBotType
from langboard_shared.domain.models.InternalBotRun import InternalBotRun, InternalBotRunKind, InternalBotRunStatus
from langboard_shared.domain.models.ProjectAssignedInternalBot import ProjectAssignedInternalBot
from langboard_shared.domain.models.ProjectChatSession import ProjectChatSession
from langboard_shared.domain.models.User import User


def create_bot(value: object) -> InternalBot:
    return InternalBot.model_construct(
        id=SnowflakeID(11),
        bot_type=InternalBotType.ProjectChat,
        platform=BotPlatform.Default,
        platform_running_type=BotPlatformRunningType.Default,
        value=json_dumps(value),
    )


def create_user() -> User:
    return User.model_construct(id=SnowflakeID(7))


def test_graph_request_preserves_context_and_server_owned_token() -> None:
    bot = create_bot(
        {
            "agent_llm": "configured-llm",
            "system_prompt": "Configured prompt",
            "api_names": ["get_card_details"],
            "api_approval_policy": {"read": "allow", "edit": "ask"},
            "approval_request": {"enabled": True},
            "comfort_tool_names": ["card_lookup"],
            "comfort_tool_definitions": {
                "card_lookup": {
                    "label": "Card lookup",
                    "description": "Look up the current card",
                    "api_names": ["get_card_details", "get_card_comments"],
                },
                "broken_tool": {"description": 4},
            },
        }
    )
    rest_data = {
        "api_permission_level": "edit",
        "api_approval_policy": {"read": "allow", "edit": "allow"},
        "chat_scope": "card",
        "card_uid": "card-1",
    }

    request = build_internal_bot_graph_request(
        bot,
        create_user(),
        "Summarize the card",
        "session-1",
        "project-1",
        rest_data,
        run_id="task-1",
        thread_scope="session",
        tweaks={"Prompt": {"prompt": "Scope prompt"}},
        file_path="uploads/example.txt",
    )

    assert request["thread_id"] == f"{bot.get_uid()}:7:project-1:session-1"
    assert request["session"] == request["session_id"] == "session-1"
    assert request["uid"] == bot.get_uid()
    assert request["input_value"] == "Summarize the card"
    assert request["tweaks"]["Prompt"] == {"prompt": "Scope prompt"}
    assert request["tweaks"]["LangboardFile"] == {"path": "uploads/example.txt"}
    assert request["tweaks"]["LangboardCalledVariablesComponent"]["rest_data"] == rest_data
    assert request["tweaks"]["LangboardCalledVariablesComponent"]["current_runner_data"] == {
        "uid": create_user().get_uid()
    }
    token = request["tweaks"]["LangboardCalledVariablesComponent"]["app_api_token"]
    assert AuthSecurity.decode_access_token(token)["api_permission_level"] == "edit"
    assert request["tweaks"]["Graph"]["system_prompt"].startswith("Configured prompt")
    assert request["tweaks"]["Graph"]["system_prompt"].endswith("Scope prompt")
    assert request["tweaks"]["Graph"]["api_names"] == ["get_card_details", "get_card_comments"]
    assert request["tweaks"]["Graph"]["api_approval_policy"] == {"read": "allow", "edit": "allow"}
    assert request["tweaks"]["Graph"]["approval_request"] == {"enabled": True}


@pytest.mark.parametrize("prompt_tweak", [None, "Invalid shape", {}, {"prompt": None}, {"prompt": 5}, {"prompt": ""}])
def test_graph_request_ignores_empty_or_invalid_context_prompt(prompt_tweak: object) -> None:
    request = build_internal_bot_graph_request(
        create_bot({"system_prompt": "Configured prompt"}),
        create_user(),
        "Hello",
        "session-1",
        "project-1",
        {},
        tweaks={"Prompt": prompt_tweak},
    )

    assert request["tweaks"]["Graph"]["system_prompt"] == "Configured prompt"


def test_project_prompt_override_and_run_thread_identity() -> None:
    bot = create_bot({"system_prompt": "Default prompt"})
    assignment = ProjectAssignedInternalBot.model_construct(prompt="Project prompt", use_default_prompt=False)

    request = build_internal_bot_graph_request(
        bot,
        create_user(),
        "Hello",
        "session-1",
        "project-1",
        {},
        assignment=assignment,
        run_id="task-1",
    )

    assert request["tweaks"]["Graph"]["system_prompt"] == "Project prompt"
    assert request["thread_id"] == f"{bot.get_uid()}:7:project-1:session-1:task-1"

    assignment.use_default_prompt = True
    default_request = build_internal_bot_graph_request(
        bot, create_user(), "Hello", "session-1", "project-1", {}, assignment=assignment
    )
    assert default_request["tweaks"]["Graph"]["system_prompt"] == "Default prompt"


def test_file_only_message_can_be_prepared() -> None:
    request = build_internal_bot_graph_request(
        create_bot({}), create_user(), "", "session-1", "project-1", {}, file_path="uploads/example.txt"
    )

    assert request["input_value"] == ""
    assert request["tweaks"]["LangboardFile"] == {"path": "uploads/example.txt"}


@pytest.mark.parametrize(
    ("kind", "bot_type", "scope_table", "document_type", "scope_key", "payload", "expected_input"),
    [
        (
            InternalBotRunKind.EditorChat,
            InternalBotType.EditorChat,
            "card",
            "card",
            "card_uid",
            {"messages": [{"role": "user", "content": "Draft"}, {"role": "assistant", "content": "Reply"}]},
            "user: Draft\nassistant: Reply",
        ),
        (
            InternalBotRunKind.EditorCopilot,
            InternalBotType.EditorCopilot,
            "project_wiki",
            "wiki",
            "project_wiki_uid",
            {"prompt": "Continue this sentence"},
            "Continue this sentence",
        ),
    ],
)
def test_editor_graph_request_binds_persisted_scope_and_matches_node_input(
    kind: InternalBotRunKind,
    bot_type: InternalBotType,
    scope_table: str,
    document_type: str,
    scope_key: str,
    payload: dict[str, object],
    expected_input: str,
) -> None:
    scope_uid = SnowflakeID(29).to_short_code()
    run = InternalBotRun.model_construct(
        user_id=SnowflakeID(7),
        project_id=SnowflakeID(13),
        internal_bot_id=SnowflakeID(11),
        kind=kind,
        status=InternalBotRunStatus.Streaming,
        attempt=1,
        client_task_id="editor-task-1",
        scope_table=scope_table,
        scope_uid=scope_uid,
        request_payload={
            **payload,
            "system": "Current editor context",
            "document_name": f"{document_type}:{scope_uid}:description",
        },
    )
    bot = create_bot({"system_prompt": "Bot prompt"})
    bot.bot_type = bot_type
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=run.project_id, internal_bot_id=bot.id, use_default_prompt=True
    )

    request = build_editor_graph_request(run, bot, create_user(), assignment)

    project_uid = run.project_id.to_short_code()
    session_id = f"{create_user().get_uid()}-{project_uid}"
    assert request["input_value"] == expected_input
    assert request["session_id"] == session_id
    assert request["thread_id"] == f"{bot.get_uid()}:7:{project_uid}:{session_id}:editor-task-1"
    assert request["tweaks"]["Prompt"] == {"prompt": "Current editor context"}
    assert request["tweaks"]["Graph"]["system_prompt"] == "Bot prompt\n\nCurrent editor context"
    assert request["tweaks"]["LangboardCalledVariablesComponent"]["rest_data"] == {
        "project_uid": project_uid,
        scope_key: scope_uid,
        "document_name": f"{document_type}:{scope_uid}:description",
        "origin_type": "editor",
    }

    run.client_task_id = "editor-task-2"
    concurrent_request = build_editor_graph_request(run, bot, create_user(), assignment)
    assert concurrent_request["session_id"] == request["session_id"]
    assert concurrent_request["thread_id"] != request["thread_id"]

    run.client_task_id = ""
    with pytest.raises(ValueError, match="not bound"):
        build_editor_graph_request(run, bot, create_user(), assignment)
    run.client_task_id = "editor-task-1"

    assignment.project_id = SnowflakeID(99)
    with pytest.raises(ValueError, match="not bound"):
        build_editor_graph_request(run, bot, create_user(), assignment)


def test_invalid_bot_configuration_fails_before_a_graph_request_is_accepted() -> None:
    bot = create_bot({})
    bot.value = "{bad json"
    with pytest.raises(ValueError, match="settings are invalid"):
        build_internal_bot_graph_request(bot, create_user(), "Hello", "session-1", "project-1", {})

    bot = create_bot({})
    bot.platform = BotPlatform.Langflow
    with pytest.raises(ValueError, match="default Graph platform"):
        build_internal_bot_graph_request(bot, create_user(), "Hello", "session-1", "project-1", {})


def create_board_chat_run(scope_table: str = "card") -> tuple[InternalBotRun, ProjectChatSession]:
    run = InternalBotRun.model_construct(
        id=SnowflakeID(31),
        user_id=SnowflakeID(7),
        project_id=SnowflakeID(13),
        internal_bot_id=SnowflakeID(11),
        chat_session_id=SnowflakeID(17),
        chat_history_id=SnowflakeID(19),
        kind=InternalBotRunKind.BoardChat,
        status=InternalBotRunStatus.Streaming,
        attempt=1,
        scope_table=scope_table,
        scope_uid=SnowflakeID(29).to_short_code() if scope_table != "project" else None,
        client_task_id="task-1",
        request_payload={"message": "Summarize the card", "api_permission_level": "edit"},
    )
    project_session = ProjectChatSession.model_construct(
        id=SnowflakeID(23), project_id=SnowflakeID(13), chat_session_id=SnowflakeID(17)
    )
    return run, project_session


def test_board_chat_graph_request_uses_persisted_identity_and_server_context() -> None:
    run, project_session = create_board_chat_run()
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=SnowflakeID(13), internal_bot_id=SnowflakeID(11), prompt="Project prompt", use_default_prompt=False
    )
    active_documents = [{"document_name": "card:description", "type": "card"}]
    scope_context = {"card_uid": run.scope_uid, "title": "Current card"}

    request = build_board_chat_bot_request(
        run,
        create_bot({"system_prompt": "Default prompt"}),
        create_user(),
        project_session,
        assignment,
        scope_context=scope_context,
        active_collaborative_documents=active_documents,
    )

    assert run.chat_session_id is not None
    assert run.chat_history_id is not None
    rest_data = request["tweaks"]["LangboardCalledVariablesComponent"]["rest_data"]
    assert rest_data["project_uid"] == run.project_id.to_short_code()
    assert rest_data["chat_scope"] == "card"
    assert rest_data["card_uid"] == run.scope_uid
    assert rest_data["scope_context"] == scope_context
    assert rest_data["chat_session_uid"] == run.chat_session_id.to_short_code()
    assert rest_data["project_chat_session_uid"] == project_session.get_uid()
    assert rest_data["chat_history_uid"] == run.chat_history_id.to_short_code()
    assert rest_data["active_collaborative_documents"] == active_documents
    assert "active collaborative draft" in rest_data["collaborative_edit_instruction"]
    assert rest_data["api_approval_policy"] == {"read": "allow", "create": "ask", "edit": "ask"}
    assert request["thread_id"] == (
        f"{SnowflakeID(11).to_short_code()}:7:{run.project_id.to_short_code()}:{project_session.get_uid()}"
    )
    assert request["tweaks"]["Graph"]["system_prompt"] == "Project prompt"
    assert request["tweaks"]["Graph"]["api_approval_policy"] == rest_data["api_approval_policy"]
    assert (
        AuthSecurity.decode_access_token(request["tweaks"]["LangboardCalledVariablesComponent"]["app_api_token"])[
            "api_permission_level"
        ]
        == "edit"
    )


def test_board_chat_langflow_request_preserves_scope_and_server_owned_credentials() -> None:
    run, project_session = create_board_chat_run()
    bot = create_bot({})
    bot.platform = BotPlatform.Langflow
    bot.platform_running_type = BotPlatformRunningType.Endpoint
    bot.api_url = "https://langflow.example.test/"
    bot.api_key = "server-only-key"
    bot.value = "/api/v1/run/flow"
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=run.project_id, internal_bot_id=bot.id, use_default_prompt=True
    )
    scope_context = {"card_uid": run.scope_uid, "title": "Current card"}

    request = build_board_chat_bot_request(
        run,
        bot,
        create_user(),
        project_session,
        assignment,
        scope_context=scope_context,
        active_collaborative_documents=[{"document_name": "card:description", "type": "card"}],
    )

    assert request["url"] == "https://langflow.example.test/api/v1/run/flow?stream=true"
    assert request["api_key"] == "server-only-key"
    assert request["session_id"] == project_session.get_uid()
    assert request["thread_id"] == (f"{bot.get_uid()}:7:{run.project_id.to_short_code()}:{project_session.get_uid()}")
    body = request["request_body"]
    assert body["input_value"] == "Summarize the card"
    assert body["run_type"] == "internal_bot"
    assert "api_key" not in body
    variables = body["tweaks"]["LangboardCalledVariablesComponent"]
    assert run.chat_history_id is not None
    assert variables["rest_data"]["scope_context"] == scope_context
    assert variables["rest_data"]["chat_history_uid"] == run.chat_history_id.to_short_code()
    assert variables["rest_data"]["active_collaborative_documents"] == [
        {"document_name": "card:description", "type": "card"}
    ]
    assert AuthSecurity.decode_access_token(variables["app_api_token"])["api_permission_level"] == "edit"


def test_board_chat_langflow_request_uses_persisted_attachment_identity() -> None:
    run, project_session = create_board_chat_run()
    run.request_payload["message"] = ""
    run.request_payload["attachment"] = {
        "file_id": "file-id",
        "path": "user/file.pdf",
        "token": "opaque-token",
    }
    bot = create_bot({})
    bot.platform = BotPlatform.Langflow
    bot.platform_running_type = BotPlatformRunningType.Endpoint
    bot.api_url = "https://langflow.example.test"
    bot.api_key = "server-only-key"
    bot.value = "/api/v1/run/flow"
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=run.project_id, internal_bot_id=bot.id, use_default_prompt=True
    )

    request = build_board_chat_bot_request(
        run,
        bot,
        create_user(),
        project_session,
        assignment,
        scope_context={"card_uid": run.scope_uid, "title": "Current card"},
        active_collaborative_documents=[],
    )

    assert request["request_body"]["input_value"] == ""
    assert request["request_body"]["tweaks"]["LangboardFile"] == {"path": "user/file.pdf"}


def test_langflow_request_rejects_unsupported_platform_or_missing_endpoint() -> None:
    bot = create_bot({})
    bot.platform = BotPlatform.N8N
    with pytest.raises(ValueError, match="Langflow endpoint platform"):
        build_internal_bot_langflow_request(bot, create_user(), "Hello", "session-1", "project-1", {})

    bot.platform = BotPlatform.Langflow
    bot.platform_running_type = BotPlatformRunningType.Endpoint
    bot.api_url = ""
    bot.value = "/api/v1/run/flow"
    with pytest.raises(ValueError, match="missing its user, session, or endpoint"):
        build_internal_bot_langflow_request(
            bot, create_user(), "Hello", "session-1", "project-1", {"api_permission_level": "read"}
        )


def test_board_chat_graph_request_rejects_missing_context_and_foreign_session() -> None:
    run, project_session = create_board_chat_run()
    bot = create_bot({})
    user = create_user()
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=SnowflakeID(13), internal_bot_id=SnowflakeID(11), use_default_prompt=True
    )

    with pytest.raises(ValueError, match="Matching card chat context is required"):
        build_board_chat_bot_request(
            run, bot, user, project_session, assignment, scope_context=None, active_collaborative_documents=[]
        )

    with pytest.raises(ValueError, match="Matching card chat context is required"):
        build_board_chat_bot_request(
            run,
            bot,
            user,
            project_session,
            assignment,
            scope_context={"card_uid": "another-card"},
            active_collaborative_documents=[],
        )

    assignment.project_id = SnowflakeID(99)
    with pytest.raises(ValueError, match="not bound"):
        build_board_chat_bot_request(
            run,
            bot,
            user,
            project_session,
            assignment,
            scope_context={"card_uid": run.scope_uid},
            active_collaborative_documents=[],
        )
    assignment.project_id = run.project_id

    project_session.chat_session_id = SnowflakeID(99)
    with pytest.raises(ValueError, match="not bound"):
        build_board_chat_bot_request(
            run, bot, user, project_session, assignment, scope_context={}, active_collaborative_documents=[]
        )


def test_board_chat_graph_request_rejects_invalid_payload_and_scope() -> None:
    run, project_session = create_board_chat_run("project")
    bot = create_bot({})
    user = create_user()
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=SnowflakeID(13), internal_bot_id=SnowflakeID(11), use_default_prompt=True
    )

    request = build_board_chat_bot_request(
        run, bot, user, project_session, assignment, scope_context=None, active_collaborative_documents=[]
    )
    assert request["tweaks"]["Graph"]["api_approval_policy"] == {
        "read": "allow",
        "create": "ask",
        "edit": "ask",
    }

    run.status = InternalBotRunStatus.Accepted
    with pytest.raises(ValueError, match="not bound"):
        build_board_chat_bot_request(
            run, bot, user, project_session, assignment, scope_context=None, active_collaborative_documents=[]
        )
    run.status = InternalBotRunStatus.Streaming

    run.request_payload["api_permission_level"] = "unknown"
    with pytest.raises(ValueError, match="payload is invalid"):
        build_board_chat_bot_request(
            run, bot, user, project_session, assignment, scope_context=None, active_collaborative_documents=[]
        )

    run.request_payload["api_permission_level"] = "edit"
    run.request_payload["file_path"] = "/tmp/unverified"
    with pytest.raises(ValueError, match="attachment execution is not supported"):
        build_board_chat_bot_request(
            run, bot, user, project_session, assignment, scope_context=None, active_collaborative_documents=[]
        )


@pytest.mark.parametrize(
    ("permission_level", "expected_policy"),
    [
        ("read", {"read": "allow"}),
        ("edit", {"read": "allow", "create": "ask", "edit": "ask"}),
        ("full_access", {"read": "allow", "create": "ask", "edit": "ask", "delete": "ask"}),
    ],
)
def test_board_chat_graph_request_preserves_permission_policy(
    permission_level: str, expected_policy: dict[str, str]
) -> None:
    run, project_session = create_board_chat_run("project")
    run.request_payload["api_permission_level"] = permission_level
    assignment = ProjectAssignedInternalBot.model_construct(
        project_id=run.project_id, internal_bot_id=run.internal_bot_id, use_default_prompt=True
    )

    request = build_board_chat_bot_request(
        run,
        create_bot({}),
        create_user(),
        project_session,
        assignment,
        scope_context=None,
        active_collaborative_documents=[],
    )

    assert request["tweaks"]["Graph"]["api_approval_policy"] == expected_policy
