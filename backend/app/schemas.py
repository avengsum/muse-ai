from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    timezone: str = "UTC"
    callback_url: Optional[str] = None


class AgentRunResponse(BaseModel):
    id: str
    status: str
    conversation_id: str
    result_message_id: Optional[int] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class AgentRunEventResponse(BaseModel):
    sequence: int
    kind: str
    payload: dict[str, Any]
    created_at: datetime


class BrowserRunResponse(BaseModel):
    id: str
    status: str
    preview_url: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class MessageResponse(BaseModel):
    id: int
    conversation_id: str
    sender: str
    text: str
    created_at: datetime
    browser: Optional[BrowserRunResponse] = None
    sandbox: Optional[dict[str, Any]] = None
    schedule_confirmation: Optional[dict[str, Any]] = None
    schedule_status: Optional[str] = None
    connect_cta: Optional[dict[str, str]] = None
    swiggy_cta: Optional[dict[str, str]] = None
    food_confirmation: Optional[dict[str, Any]] = None
    food_status: Optional[str] = None
    food_order_id: Optional[str] = None
    tool_approval: Optional[dict[str, Any]] = None
    tool_approval_status: Optional[str] = None
    activity: list[str] = []
    scratchpad: Optional[dict[str, Any]] = None
    active_specialist: Optional[str] = None
    

class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ToolResponse(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    color: str
    connected: bool
    account: Optional[str] = None


class ToolConnectRequest(BaseModel):
    callback_url: str


class ToolConnectResponse(BaseModel):
    request_id: str
    redirect_url: str


class TaskCreate(BaseModel):
    title: str
    schedule: str
    prompt: Optional[str] = None
    timezone: str = "UTC"
    execution_mode: str = "assistant"


class ScheduleConfirmationCreate(BaseModel):
    confirmation: dict[str, Any]
    source_message_id: Optional[int] = None


class ScheduleMessageUpdate(BaseModel):
    status: str


class SettingsUpdate(BaseModel):
    agent_name: str
    accent_color: str
    notifications_enabled: bool


class SettingsResponse(SettingsUpdate):
    pass


class UserMemoryResponse(BaseModel):
    id: int
    category: str
    fact: str


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    kind: str
    read: bool
    created_at: datetime


class TaskResponse(BaseModel):
    id: int
    title: str
    schedule: str
    prompt: str
    timezone: str
    execution_mode: str
    delivery: str = "chat"
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_run_result: Optional[str] = None
    last_run_error: Optional[str] = None
    runs: int
    active: bool
    created_at: datetime
    updated_at: datetime


class TaskRunResponse(BaseModel):
    id: int
    task_id: int
    status: str
    result: Optional[str] = None
    error: Optional[str] = None
    browser_run_id: Optional[str] = None
    browser_preview_url: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class BrowserRunCreate(BaseModel):
    task: str
    conversation_id: Optional[str] = None


class BrowserRunResume(BaseModel):
    message: str = "Continue now that the requested input is complete."


class SwiggyOAuthStartResponse(BaseModel):
    authorization_url: str
    callback_url: str


class PushTokenCreate(BaseModel):
    token: str
    platform: str = "unknown"