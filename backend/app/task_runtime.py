from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from .ai_service import generate_reply
from .browser_runtime import create_browser_record, wait_for_browser_agent_task
from .conversation_service import get_agent_session
from .database import SessionLocal
from .memory_service import get_user_memory_context
from .models import (
    BrowserRun, PushToken, ScheduledTask, TaskMetadata, TaskRun, TaskSchedule, UserSettings,
)
from .notification_service import add_notification, send_expo_push
from .runtime_utils import as_utc, log_internal_error, public_error
from .schedule_service import ScheduleValidationError, calculate_next_run_at, parse_schedule_text
from .schemas import TaskCreate, TaskResponse, TaskRunResponse


def task_schedule_rule(task_schedule: TaskSchedule):
    if task_schedule.schedule_kind == "interval":
        return {
            "frequency": "interval",
            "interval_minutes": task_schedule.interval_minutes or 60,
        }

    rule = {
        "frequency": task_schedule.schedule_kind,
        "time": f"{task_schedule.hour or 0:02d}:{task_schedule.minute or 0:02d}",
    }

    if task_schedule.schedule_kind == "weekly":
        rule["weekday"] = task_schedule.weekday or 0

    return rule


def make_task_response(database, task: ScheduledTask):
    schedule = database.get(TaskSchedule, task.id)
    metadata = database.get(TaskMetadata, task.id)
    latest_run = database.scalar(
        select(TaskRun)
        .where(TaskRun.task_id == task.id)
        .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
        .limit(1)
    )

    return TaskResponse(
        id=task.id,
        title=task.title,
        schedule=task.schedule,
        prompt=schedule.prompt if schedule else task.title,
        timezone=schedule.timezone if schedule else "UTC",
        execution_mode=schedule.execution_mode if schedule else "assistant",
        delivery=metadata.delivery if metadata else "chat",
        next_run_at=schedule.next_run_at if schedule else None,
        last_run_at=schedule.last_run_at if schedule else None,
        last_run_status=latest_run.status if latest_run else None,
        last_run_result=latest_run.result if latest_run else None,
        last_run_error=latest_run.error if latest_run else None,
        runs=task.runs,
        active=task.active,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def schedule_text_from_rule(rule: dict[str, Any]):
    frequency = rule.get("frequency")
    schedule_time = str(rule.get("time") or "09:00")

    if frequency == "once":
        return f"Once at {schedule_time}"

    if frequency == "interval":
        return f"Every {int(rule.get('interval_minutes') or 60)} minutes"

    if frequency == "weekly":
        weekday = str(rule.get("weekday") or "monday").capitalize()
        return f"Every {weekday} at {schedule_time}"

    return f"Every day at {schedule_time}"


def make_task_run_response(database, task_run: TaskRun):
    preview_url = None

    if task_run.browser_run_id:
        browser_run = database.get(BrowserRun, task_run.browser_run_id)
        preview_url = browser_run.preview_url if browser_run else None

    return TaskRunResponse(
        id=task_run.id,
        task_id=task_run.task_id,
        status=task_run.status,
        result=task_run.result,
        error=task_run.error,
        browser_run_id=task_run.browser_run_id,
        browser_preview_url=preview_url,
        created_at=task_run.created_at,
        started_at=task_run.started_at,
        finished_at=task_run.finished_at,
    )


def create_task_run_record(database, task: ScheduledTask):
    task_run = TaskRun(
        task_id=task.id,
        user_id=task.user_id,
        status="pending",
    )
    database.add(task_run)
    database.commit()
    database.refresh(task_run)
    return task_run


def complete_task_run(database, task_run, task, schedule, result):
    from .models import Conversation, Message

    now = datetime.now(UTC)
    task_run.status = "completed"
    task_run.result = result
    task_run.error = None
    task_run.finished_at = now
    task.runs += 1
    task.updated_at = now
    schedule.last_run_at = now

    metadata = database.get(TaskMetadata, task.id)
    target_conversation_id = None
    if metadata and metadata.source_message_id:
        source_msg = database.get(Message, metadata.source_message_id)
        if source_msg:
            target_conversation_id = source_msg.conversation_id

    if not target_conversation_id:
        latest_conv = database.scalar(
            select(Conversation)
            .where(Conversation.user_id == task.user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        if latest_conv:
            target_conversation_id = latest_conv.id

    if target_conversation_id and (not metadata or metadata.delivery == "chat"):
        database.add(
            Message(
                conversation_id=target_conversation_id,
                sender="agent",
                text=f"📋 **{task.title}**\n\n{result}",
            )
        )
        conv = database.get(Conversation, target_conversation_id)
        if conv:
            conv.updated_at = now

    add_notification(
        database,
        task.user_id,
        f"{task.title} completed",
        result,
        "success",
    )

    if schedule.schedule_kind == "once":
        task.active = False
        schedule.next_run_at = None
    elif not schedule.next_run_at or as_utc(schedule.next_run_at) <= now:
        schedule.next_run_at = calculate_next_run_at(
            task_schedule_rule(schedule),
            schedule.timezone,
            now=now,
            previous_run_at=now,
        )

    database.commit()
    settings = database.get(UserSettings, task.user_id)
    if not settings or settings.notifications_enabled:
        tokens = [
            row.token
            for row in database.scalars(
                select(PushToken).where(PushToken.user_id == task.user_id)
            ).all()
        ]
        send_expo_push(
            tokens,
            f"{task.title} completed",
            str(result)[:180],
            {
                "type": "task_completed",
                "task_id": task.id,
                "conversation_id": target_conversation_id,
            },
        )

def fail_task_run(database, task_run_id: int, error: Exception):
    error_id = log_internal_error(
        "Scheduled task failed",
        task_run_id=task_run_id,
    )
    database.rollback()
    task_run = database.get(TaskRun, task_run_id)

    if task_run:
        task_run.status = "failed"
        task_run.error = public_error("The task could not be completed.", error_id)
        task_run.finished_at = datetime.now(UTC)
        task = database.get(ScheduledTask, task_run.task_id)

        if task:
            add_notification(
                database,
                task.user_id,
                f"{task.title} failed",
                task_run.error,
                "error",
            )

        database.commit()
        settings = database.get(UserSettings, task.user_id) if task else None
        if task and (not settings or settings.notifications_enabled):
            tokens = [
                row.token
                for row in database.scalars(
                    select(PushToken).where(PushToken.user_id == task.user_id)
                ).all()
            ]
            send_expo_push(
                tokens,
                f"{task.title} failed",
                task_run.error[:180],
                {"type": "task_failed", "task_id": task.id},
            )


def execute_task_run(task_run_id: int):
    with SessionLocal() as database:
        task_run = database.get(TaskRun, task_run_id)

        if task_run is None:
            return

        task = database.get(ScheduledTask, task_run.task_id)
        schedule = database.get(TaskSchedule, task_run.task_id)
        metadata = database.get(TaskMetadata, task_run.task_id)

        if task is None or schedule is None:
            fail_task_run(database, task_run_id, RuntimeError("Task configuration is missing"))
            return

        task_run.status = "running"
        task_run.started_at = datetime.now(UTC)
        database.commit()

        user_id = task.user_id
        task_id = task.id
        task_title = task.title
        prompt = schedule.prompt
        execution_mode = schedule.execution_mode
        delivery = metadata.delivery if metadata else "chat"

    try:
        if execution_mode == "browser":
            with SessionLocal() as database:
                browser_run = create_browser_record(
                    database,
                    user_id,
                    prompt,
                    task_id=task_id,
                )
                task_run = database.get(TaskRun, task_run_id)
                task_run.browser_run_id = browser_run.id
                database.commit()

            result = wait_for_browser_agent_task(browser_run.id)

            if result is None:
                with SessionLocal() as database:
                    task_run = database.get(TaskRun, task_run_id)
                    task_run.status = "paused"
                    task_run.result = "Browser task paused for your input."
                    add_notification(
                        database,
                        user_id,
                        f"{task_title} needs input",
                        task_run.result,
                        "action",
                    )
                    database.commit()
                return

            if delivery != "chat":
                with SessionLocal() as database:
                    session = get_agent_session(database, user_id)
                    composio_session_id = session.session_id if session else None
                    memory_context = get_user_memory_context(database, user_id)

                delivery_result = generate_reply(
                    [
                        {
                            "role": "user",
                            "content": (
                                "APPROVED SCHEDULED TASK:\n"
                                f"Deliver this completed result through {delivery} "
                                "using the destination in the original task.\n\n"
                                f"Original task: {prompt}\n\n"
                                f"Result: {result}"
                            ),
                        }
                    ],
                    composio_session_id,
                    timezone=schedule.timezone,
                    memory_context=memory_context,
                )
                result = f"{result}\n\n{delivery_result}"
        else:
            from .browser_runtime import run_browser_for_agent

            with SessionLocal() as database:
                session = get_agent_session(database, user_id)
                composio_session_id = session.session_id if session else None
                memory_context = get_user_memory_context(database, user_id)

            delivery_instruction = ""
            if delivery != "chat":
                delivery_instruction = (
                    f"\nDeliver the final result through {delivery} "
                    "using the connected tool requested in the task."
                )

            browser_handler = lambda task_str, emit, cancel: run_browser_for_agent(
                user_id, None, task_str, emit, cancel
            )

            result = generate_reply(
                [
                    {
                        "role": "user",
                        "content": (
                            f"APPROVED SCHEDULED TASK:\n{prompt}"
                            f"{delivery_instruction}"
                        ),
                    }
                ],
                composio_session_id,
                timezone=schedule.timezone,
                browser_handler=browser_handler,
                memory_context=memory_context,
            )

        with SessionLocal() as database:
            task_run = database.get(TaskRun, task_run_id)
            task = database.get(ScheduledTask, task_id)
            schedule = database.get(TaskSchedule, task_id)

            if task_run is None or task is None or schedule is None:
                raise RuntimeError("Task configuration was removed while running")

            complete_task_run(database, task_run, task, schedule, result)
    except Exception as error:
        with SessionLocal() as database:
            fail_task_run(database, task_run_id, error)


def parse_task_input(payload: TaskCreate):
    title = payload.title.strip()
    schedule_text = payload.schedule.strip() or "Every day at 9:00 AM"
    prompt = (payload.prompt or title).strip()
    timezone_name = payload.timezone.strip() or "UTC"
    execution_mode = payload.execution_mode.strip().lower()

    if not title:
        raise HTTPException(status_code=422, detail="Task title is required")

    if not prompt:
        raise HTTPException(status_code=422, detail="Task instructions are required")

    if execution_mode not in {"assistant", "browser"}:
        raise HTTPException(status_code=422, detail="Execution mode must be assistant or browser")

    try:
        rule = parse_schedule_text(schedule_text)
        next_run_at = calculate_next_run_at(rule, timezone_name)
    except ScheduleValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

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

    return {
        "title": title,
        "schedule_text": schedule_text,
        "prompt": prompt,
        "timezone": timezone_name,
        "execution_mode": execution_mode,
        "schedule_kind": rule["frequency"],
        "interval_minutes": (
            rule.get("interval_seconds", 0) // 60
            if rule["frequency"] == "interval"
            else None
        ),
        "hour": hour,
        "minute": minute,
        "weekday": (
            weekday_names.index(rule["weekday"])
            if rule["frequency"] == "weekly"
            else None
        ),
        "next_run_at": next_run_at,
    }


def apply_task_schedule(schedule: TaskSchedule, values: dict):
    schedule.prompt = values["prompt"]
    schedule.timezone = values["timezone"]
    schedule.execution_mode = values["execution_mode"]
    schedule.schedule_kind = values["schedule_kind"]
    schedule.interval_minutes = values["interval_minutes"]
    schedule.hour = values["hour"]
    schedule.minute = values["minute"]
    schedule.weekday = values["weekday"]
    schedule.next_run_at = values["next_run_at"]
    schedule.updated_at = datetime.now(UTC)
