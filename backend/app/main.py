from contextlib import asynccontextmanager

import inngest.fast_api
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, select, text as sql_text

from .browser_service import browserbase_is_configured
from .composio_service import composio_is_configured
from .database import Base, SessionLocal, engine
from .inngest_service import inngest_client, inngest_functions
from .model_config import get_llm_provider, llm_is_configured
from .models import ScheduledTask, TaskSchedule, Tool
from .routers.chat import router as chat_router
from .routers.integrations import router as integrations_router
from .routers.tasks import router as tasks_router
from .schedule_service import (
    ScheduleValidationError,
    calculate_next_run_at,
    parse_schedule_text,
)
from .swiggy_service import swiggy_is_configured
from .tool_registry import TOOLS


def seed_tools():
    with SessionLocal() as database:
        for definition in TOOLS:
            existing = database.get(Tool, definition.id)
            if existing is None:
                database.add(
                    Tool(
                        id=definition.id,
                        name=definition.name,
                        description=definition.description,
                        icon=definition.icon,
                        color=definition.color,
                    )
                )
            else:
                existing.name = definition.name
                existing.description = definition.description
                existing.icon = definition.icon
                existing.color = definition.color

        database.commit()


def migrate_task_schedules():
    with SessionLocal() as database:
        tasks = database.scalars(select(ScheduledTask)).all()

        for task in tasks:
            if database.get(TaskSchedule, task.id):
                continue

            try:
                rule = parse_schedule_text(task.schedule)
            except ScheduleValidationError:
                rule = {"frequency": "daily", "time": "09:00"}

            hour = None
            minute = None

            if rule["frequency"] != "interval":
                hour, minute = [int(value) for value in rule["time"].split(":")]

            weekday_names = [
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ]
            database.add(
                TaskSchedule(
                    task_id=task.id,
                    prompt=task.title,
                    timezone="UTC",
                    schedule_kind=rule["frequency"],
                    interval_minutes=(
                        rule.get("interval_seconds", 0) // 60
                        if rule["frequency"] == "interval"
                        else None
                    ),
                    hour=hour,
                    minute=minute,
                    weekday=(
                        weekday_names.index(rule["weekday"])
                        if rule["frequency"] == "weekly"
                        else None
                    ),
                    execution_mode="assistant",
                    next_run_at=calculate_next_run_at(rule, "UTC"),
                )
            )

        database.commit()


def migrate_schema():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    statements = []

    if "browser_runs" in tables:
        statements.append(
            "ALTER TABLE browser_runs ADD COLUMN IF NOT EXISTS message_id INTEGER"
        )

    if "conversations" in tables:
        statements.append(
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS active_agent VARCHAR(30) DEFAULT 'cooper'"
        )
        statements.append(
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary TEXT"
        )
        statements.append(
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summarized_until_message_id INTEGER"
        )

    if "user_settings" in tables:
        statements.append(
            "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS questions_used INTEGER DEFAULT 0"
        )

    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(sql_text(statement))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    seed_tools()
    migrate_task_schedules()
    yield


app = FastAPI(title="Muse AI API", version="0.5.0", lifespan=lifespan)
app.include_router(chat_router)
app.include_router(integrations_router)
app.include_router(tasks_router)


inngest.fast_api.serve(app, inngest_client, inngest_functions)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "muse-ai-api",
        "llm_provider": get_llm_provider(),
        "llm": llm_is_configured(),
        "composio": composio_is_configured(),
        "browserbase": browserbase_is_configured(),
        "swiggy": swiggy_is_configured(),
    }
