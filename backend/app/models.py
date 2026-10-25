from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def current_time():
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(120),
        default="New chat",
    )

    active_agent: Mapped[str] = mapped_column(
        String(30),
        default="cooper",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )
    
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    summarized_until_message_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    conversation_id: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )

    sender: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )


class MessageArtifact(Base):
    __tablename__ = "message_artifacts"

    message_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    data_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    conversation_id: Mapped[str] = mapped_column(String(100), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatch_mode: Mapped[str] = mapped_column(String(20), default="inngest")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    result_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(100), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=current_time)


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )

    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(200))
    icon: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(20))


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(100),
        index=True,
    )

    title: Mapped[str] = mapped_column(String(160))
    schedule: Mapped[str] = mapped_column(String(120))
    runs: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class TaskSchedule(Base):
    __tablename__ = "task_schedules"

    task_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    prompt: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    schedule_kind: Mapped[str] = mapped_column(String(20), default="daily")
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(20), default="assistant")
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class TaskMetadata(Base):
    __tablename__ = "task_metadata"

    task_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery: Mapped[str] = mapped_column(String(30), default="chat")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    source_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    browser_run_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class BrowserRun(Base):
    __tablename__ = "browser_runs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    provider_run_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
    )
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    user_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    composio_session_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(30), default="Cooper")
    accent_color: Mapped[str] = mapped_column(String(20), default="#2563EB")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    questions_used: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class UserMemory(Base):
    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general", index=True)
    fact: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="info")
    read: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )


class SwiggyOAuthState(Base):
    __tablename__ = "swiggy_oauth_states"

    state: Mapped[str] = mapped_column(String(160), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    code_verifier_encrypted: Mapped[str] = mapped_column(Text)
    client_id: Mapped[str] = mapped_column(String(200))
    app_callback_url: Mapped[str] = mapped_column(Text)
    used: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )


class SwiggyConnection(Base):
    __tablename__ = "swiggy_connections"

    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scope: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class PushToken(Base):
    __tablename__ = "push_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True)
    platform: Mapped[str] = mapped_column(String(20), default="unknown")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )


class FoodOrder(Base):
    __tablename__ = "food_orders"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True)
    conversation_id: Mapped[str] = mapped_column(String(100), index=True)
    message_id: Mapped[int] = mapped_column(Integer, index=True)
    swiggy_order_id: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="PLACED")
    last_notified_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=current_time,
        onupdate=current_time,
    )
