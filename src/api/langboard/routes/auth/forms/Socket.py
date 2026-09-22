from typing import Annotated, Any, Literal
from uuid import UUID
from langboard_shared.core.routing import BaseFormModel, SocketTopic, form_model
from langboard_shared.Env import Env
from pydantic import ConfigDict, Field, model_validator


@form_model
class SocketSubscriptionAuthorizationItem(BaseFormModel):
    topic: SocketTopic
    topic_id: str = Field(min_length=1, max_length=128)


@form_model
class SocketSubscriptionAuthorizationForm(BaseFormModel):
    subscriptions: list[SocketSubscriptionAuthorizationItem] = Field(max_length=64)


@form_model
class SocketEditorDocumentAuthorizationForm(BaseFormModel):
    document_name: str = Field(min_length=1, max_length=512)
    write: bool = False


@form_model
class SocketEditorAiAuthorizationForm(BaseFormModel):
    project_uid: str = Field(min_length=11, max_length=11)
    scope_uid: str = Field(min_length=11, max_length=11)
    document_name: str = Field(min_length=1, max_length=512)


@form_model
class SocketEditorMessageForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=65536)


@form_model
class SocketEditorRunForm(SocketEditorAiAuthorizationForm):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    kind: Literal["editor_chat", "editor_copilot"]
    system: str = Field(default="", max_length=65536)
    messages: list[SocketEditorMessageForm] | None = Field(default=None, max_length=100)
    prompt: str | None = Field(default=None, min_length=1, max_length=65536)

    @model_validator(mode="after")
    def validate_input(self) -> "SocketEditorRunForm":
        if self.kind == "editor_chat":
            if not self.messages or self.prompt is not None:
                raise ValueError("Editor chat requires messages and no prompt")
            if sum(len(message.content) for message in self.messages) > 65536:
                raise ValueError("Editor chat messages exceed the input limit")
        elif self.prompt is None or self.messages is not None:
            raise ValueError("Editor copilot requires a prompt and no messages")
        return self


@form_model
class SocketEditorCancelForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    project_uid: str = Field(min_length=11, max_length=11)
    task_id: UUID
    kind: Literal["editor_chat", "editor_copilot"]


@form_model
class SocketEditorStatusForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    project_uid: str = Field(min_length=11, max_length=11)
    task_id: UUID
    kind: Literal["editor_chat", "editor_copilot"]


@form_model
class SocketEditorDocumentsAuthorizationForm(BaseFormModel):
    document_names: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(max_length=256)
    write: bool = False


@form_model
class SocketChatResumeAuthorizationForm(BaseFormModel):
    message_uid: str = Field(min_length=11, max_length=11)
    thread_id: str = Field(min_length=1, max_length=512)
    session_id: str | None = Field(default=None, max_length=512)
    approval_uid: str | None = Field(default=None, min_length=11, max_length=11)


@form_model
class SocketBoardChatRunForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    message: str = Field(max_length=65536)
    file_token: str | None = Field(default=None, min_length=32, max_length=128)
    session_uid: str | None = Field(default=None, min_length=11, max_length=11)
    scope_table: Literal["project", "project_column", "card", "project_wiki"] = "project"
    scope_uid: str | None = Field(default=None, min_length=11, max_length=11)
    api_permission_level: Literal["read", "edit", "full_access"] = "read"

    @model_validator(mode="after")
    def validate_message(self) -> "SocketBoardChatRunForm":
        if not self.message.strip() and self.file_token is None:
            raise ValueError("A message or attachment is required")
        return self


@form_model
class SocketBoardChatCancelForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID


@form_model
class SocketBoardChatStartForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    active_document_names: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(max_length=128)


@form_model
class SocketBoardChatFinishForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    status: Literal["completed", "failed", "cancelled"]
    output_text: str = Field(default="", max_length=Env.AI_STREAM_MAX_BUFFER_MB * 1024 * 1024)
    error_message: str | None = Field(default=None, max_length=1000)


@form_model
class SocketBoardChatLeaseForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)


@form_model
class SocketBoardChatPauseForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    output_text: str = Field(default="", max_length=Env.AI_STREAM_MAX_BUFFER_MB * 1024 * 1024)
    interrupt: dict[str, Any] = Field(min_length=1)


@form_model
class SocketBoardChatResumeDecision(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    rejected: bool
    instruction: str | None = Field(default=None, max_length=65536)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_decision(self) -> "SocketBoardChatResumeDecision":
        is_instruction = bool(self.instruction and self.instruction.strip())
        if sum((self.approved, self.rejected, is_instruction)) != 1:
            raise ValueError("Exactly one Graph resume decision is required")
        if self.reason and not self.rejected:
            raise ValueError("A rejection reason requires a rejected decision")
        return self


@form_model
class SocketBoardChatResumeClaimForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    message_uid: str = Field(min_length=11, max_length=11)
    thread_id: str = Field(min_length=1, max_length=512)
    session_id: str = Field(min_length=11, max_length=512)
    approval_uid: str | None = Field(default=None, min_length=11, max_length=11)
    resume: SocketBoardChatResumeDecision


@form_model
class SocketBoardChatResumeResultForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1)
    thread_id: str = Field(min_length=1, max_length=512)
    session_id: str = Field(min_length=11, max_length=512)
    response_text: str = Field(max_length=Env.AI_STREAM_MAX_BUFFER_MB * 1024 * 1024)
    interrupt: dict[str, Any] | None = None


@form_model
class SocketEditorResumeClaimForm(BaseFormModel):
    model_config = ConfigDict(extra="forbid")

    project_uid: str = Field(min_length=11, max_length=11)
    resume: SocketBoardChatResumeDecision

    @model_validator(mode="after")
    def validate_editor_decision(self) -> "SocketEditorResumeClaimForm":
        if self.resume.instruction is not None or self.resume.approved == self.resume.rejected:
            raise ValueError("An editor approval requires an approve or reject decision")
        return self
