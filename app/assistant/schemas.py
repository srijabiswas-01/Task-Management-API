from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AssistantReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AssistantAsk(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: int | None = None
    view: str | None = Field(default=None, max_length=40)
    workspace_id: int | None = None
    project_id: int | None = None


class AssistantConversationRead(AssistantReadModel):
    id: int
    title: str
    context_view: str | None
    workspace_id: int | None
    project_id: int | None
    updated_at: datetime


class AssistantMessageRead(AssistantReadModel):
    id: int
    role: str
    body: str
    model: str | None
    created_at: datetime


class AssistantConversationDetail(AssistantConversationRead):
    messages: list[AssistantMessageRead]


class AssistantBootstrap(BaseModel):
    access_label: str
    scope_description: str
    suggestions: list[str]
