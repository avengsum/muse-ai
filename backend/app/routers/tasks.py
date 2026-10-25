import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select

from ..auth import CurrentUser, get_current_user
from ..conversation_service import ensure_conversation_access
from ..database import SessionLocal
from ..inngest_service import queue_task_event
from ..message_artifacts import schedule_artifact
from ..models import BrowserRun, Message, MessageArtifact, Notification, ScheduledTask, TaskMetadata, TaskRun, TaskSchedule, UserMemory, UserSettings
from ..schedule_service import calculate_next_run_at
from ..schemas import NotificationResponse, ScheduleConfirmationCreate, SettingsResponse, SettingsUpdate, TaskCreate, TaskResponse, TaskRunResponse, UserMemoryResponse
from ..task_runtime import apply_task_schedule, create_task_run_record, make_task_response, make_task_run_response, parse_task_input, schedule_text_from_rule, task_schedule_rule
from datetime import date
from ..model_config import _create_client_for_provider, _get_model_name_for_provider


router = APIRouter()


@router.get("/api/tasks", response_model=list[TaskResponse])
def get_tasks(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        tasks = database.scalars(
            select(ScheduledTask)
            .where(ScheduledTask.user_id == current_user.id)
            .order_by(ScheduledTask.updated_at.desc())
        ).all()
        return [make_task_response(database, task) for task in tasks]


@router.get("/api/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        task = database.get(ScheduledTask, task_id)

        if task is None or task.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Task not found")

        return make_task_response(database, task)


@router.post("/api/tasks", response_model=TaskResponse, status_code=201)
def create_task(payload: TaskCreate, current_user: CurrentUser = Depends(get_current_user)):
    values = parse_task_input(payload)

    with SessionLocal() as database:
        task = ScheduledTask(
            user_id=current_user.id,
            title=values["title"],
            schedule=values["schedule_text"],
            runs=0,
            active=True,
        )
        database.add(task)
        database.flush()
        schedule = TaskSchedule(task_id=task.id, prompt=values["prompt"])
        apply_task_schedule(schedule, values)
        database.add(schedule)
        database.commit()
        database.refresh(task)
        response = make_task_response(database, task)

    queue_task_event(task.id)
    return response


@router.post("/api/tasks/confirm", response_model=TaskResponse, status_code=201)
def confirm_schedule(
    payload: ScheduleConfirmationCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    confirmation = payload.confirmation
    rule = confirmation.get("scheduleRule")
    task_payload = confirmation.get("taskPayload")

    if not isinstance(rule, dict) or not isinstance(task_payload, dict):
        raise HTTPException(status_code=422, detail="Schedule confirmation is invalid")

    schedule_text = schedule_text_from_rule(rule)
    prompt = str(
        task_payload.get("browserTask")
        or task_payload.get("task")
        or task_payload.get("prompt")
        or confirmation.get("originalPrompt")
        or ""
    ).strip()
    execution_mode = "browser" if task_payload.get("browserTask") else "assistant"
    delivery = str(confirmation.get("delivery") or "chat").strip().lower()
    values = parse_task_input(
        TaskCreate(
            title=str(confirmation.get("title") or "Scheduled Muse AI task"),
            schedule=schedule_text,
            prompt=prompt,
            timezone=str(confirmation.get("timezone") or "UTC"),
            execution_mode=execution_mode,
        )
    )

    with SessionLocal() as database:
        artifact = None

        if payload.source_message_id is not None:
            message = database.get(Message, payload.source_message_id)

            if message is None:
                raise HTTPException(status_code=404, detail="Schedule confirmation not found")

            conversation = ensure_conversation_access(
                database,
                message.conversation_id,
                current_user.id,
            )
            artifact = database.get(MessageArtifact, message.id)

            if conversation is None or artifact is None:
                raise HTTPException(status_code=404, detail="Schedule confirmation not found")

            artifact_data = schedule_artifact(database, message.id) or {}
            existing_task_id = artifact_data.get("scheduledTaskId")

            if artifact.status == "confirmed" and existing_task_id:
                existing_task = database.get(ScheduledTask, int(existing_task_id))

                if existing_task and existing_task.user_id == current_user.id:
                    return make_task_response(database, existing_task)

            if artifact.status != "pending":
                raise HTTPException(status_code=409, detail="This schedule is no longer pending")

        task = ScheduledTask(
            user_id=current_user.id,
            title=values["title"],
            schedule=values["schedule_text"],
            runs=0,
            active=True,
        )
        database.add(task)
        database.flush()
        schedule = TaskSchedule(task_id=task.id, prompt=values["prompt"])
        apply_task_schedule(schedule, values)
        database.add(schedule)
        database.add(
            TaskMetadata(
                task_id=task.id,
                delivery=delivery[:30] or "chat",
                payload_json=json.dumps(task_payload),
                source_message_id=payload.source_message_id,
            )
        )

        if artifact:
            artifact_data = schedule_artifact(database, artifact.message_id) or confirmation
            artifact_data["scheduledTaskId"] = task.id
            artifact.data_json = json.dumps(artifact_data)
            artifact.status = "confirmed"
            artifact.updated_at = datetime.now(UTC)
            status_note = f"\n\n✅ Scheduled: {task.title} ({task.schedule})."
            if status_note.strip() not in (message.text or ""):
                message.text = f"{(message.text or '').strip()}{status_note}".strip()

        database.commit()
        database.refresh(task)
        response = make_task_response(database, task)

    queue_task_event(task.id)
    return response


@router.put("/api/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    payload: TaskCreate,
    current_user: CurrentUser = Depends(get_current_user),
):
    values = parse_task_input(payload)

    with SessionLocal() as database:
        task = database.get(ScheduledTask, task_id)

        if task is None or task.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Task not found")

        schedule = database.get(TaskSchedule, task.id)

        if schedule is None:
            schedule = TaskSchedule(task_id=task.id, prompt=values["prompt"])
            database.add(schedule)

        task.title = values["title"]
        task.schedule = values["schedule_text"]
        task.updated_at = datetime.now(UTC)
        apply_task_schedule(schedule, values)
        database.commit()
        database.refresh(task)
        response = make_task_response(database, task)

    queue_task_event(task.id)
    return response


@router.patch("/api/tasks/{task_id}/toggle", response_model=TaskResponse)
def toggle_task(task_id: int, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        task = database.get(ScheduledTask, task_id)

        if task is None or task.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Task not found")

        task.active = not task.active
        task.updated_at = datetime.now(UTC)
        schedule = database.get(TaskSchedule, task.id)

        if task.active and schedule:
            schedule.next_run_at = calculate_next_run_at(
                task_schedule_rule(schedule),
                schedule.timezone,
            )

        database.commit()
        database.refresh(task)
        response = make_task_response(database, task)

    if task.active:
        queue_task_event(task.id)

    return response


@router.post("/api/tasks/{task_id}/run", response_model=TaskRunResponse, status_code=202)
def run_task(
    task_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    with SessionLocal() as database:
        task = database.get(ScheduledTask, task_id)

        if task is None or task.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Task not found")

        active_run = database.scalar(
            select(TaskRun)
            .where(
                TaskRun.task_id == task.id,
                TaskRun.status.in_(["pending", "running"]),
            )
            .limit(1)
        )

        if active_run:
            return make_task_run_response(database, active_run)

        task_run = create_task_run_record(database, task)
        response = make_task_run_response(database, task_run)

    queue_task_event(
        task_id,
        run_now=True,
        task_run_id=task_run.id,
    )
    return response


@router.get("/api/tasks/{task_id}/runs", response_model=list[TaskRunResponse])
def get_task_runs(task_id: int, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        task = database.get(ScheduledTask, task_id)

        if task is None or task.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Task not found")

        runs = database.scalars(
            select(TaskRun)
            .where(TaskRun.task_id == task_id)
            .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
        ).all()
        return [make_task_run_response(database, task_run) for task_run in runs]


@router.get("/api/tasks/{task_id}/runs/{run_id}", response_model=TaskRunResponse)
def get_task_run(task_id: int, run_id: int, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        task_run = database.get(TaskRun, run_id)

        if (
            task_run is None
            or task_run.task_id != task_id
            or task_run.user_id != current_user.id
        ):
            raise HTTPException(status_code=404, detail="Task run not found")

        return make_task_run_response(database, task_run)


@router.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        task = database.get(ScheduledTask, task_id)

        if task is None or task.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Task not found")

        database.execute(delete(TaskRun).where(TaskRun.task_id == task_id))
        database.execute(delete(BrowserRun).where(BrowserRun.task_id == task_id))
        metadata = database.get(TaskMetadata, task_id)
        schedule = database.get(TaskSchedule, task_id)

        if metadata:
            database.delete(metadata)

        if schedule:
            database.delete(schedule)

        database.delete(task)
        database.commit()
        return {"success": True}


def get_user_settings(database, user_id: str):
    settings = database.get(UserSettings, user_id)

    if settings is None:
        settings = UserSettings(user_id=user_id)
        database.add(settings)
        database.commit()
        database.refresh(settings)

    return settings


@router.get("/api/settings", response_model=SettingsResponse)
def read_settings(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        settings = get_user_settings(database, current_user.id)
        return SettingsResponse(
            agent_name=settings.agent_name,
            accent_color=settings.accent_color,
            notifications_enabled=settings.notifications_enabled,
        )


@router.put("/api/settings", response_model=SettingsResponse)
def save_settings(
    payload: SettingsUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    agent_name = payload.agent_name.strip()
    accent_color = payload.accent_color.strip().upper()

    if not agent_name or len(agent_name) > 30:
        raise HTTPException(status_code=422, detail="Agent name must be 1 to 30 characters")

    if len(accent_color) != 7 or not accent_color.startswith("#"):
        raise HTTPException(status_code=422, detail="Accent color must be a hex color")

    try:
        int(accent_color[1:], 16)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Accent color must be a hex color") from error

    with SessionLocal() as database:
        settings = get_user_settings(database, current_user.id)
        settings.agent_name = agent_name
        settings.accent_color = accent_color
        settings.notifications_enabled = payload.notifications_enabled
        settings.updated_at = datetime.now(UTC)
        database.commit()
        return SettingsResponse(
            agent_name=settings.agent_name,
            accent_color=settings.accent_color,
            notifications_enabled=settings.notifications_enabled,
        )


@router.get("/api/user/memories", response_model=list[UserMemoryResponse])
def get_user_memories(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        memories = database.scalars(
            select(UserMemory)
            .where(
                UserMemory.user_id == current_user.id,
                UserMemory.is_active.is_(True),
            )
            .order_by(UserMemory.category, UserMemory.created_at.desc())
        ).all()
        return [
            UserMemoryResponse(id=memory.id, category=memory.category, fact=memory.fact)
            for memory in memories
        ]


@router.delete("/api/user/memories/{memory_id}")
def delete_user_memory(
    memory_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    with SessionLocal() as database:
        memory = database.get(UserMemory, memory_id)
        if memory and memory.user_id == current_user.id:
            memory.is_active = False
            database.commit()
        return {"status": "success"}


@router.get("/api/notifications", response_model=list[NotificationResponse])
def get_notifications(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        return database.scalars(
            select(Notification)
            .where(Notification.user_id == current_user.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(100)
        ).all()


@router.patch("/api/notifications/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    with SessionLocal() as database:
        notification = database.get(Notification, notification_id)

        if notification is None or notification.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Notification not found")

        notification.read = True
        database.commit()
        database.refresh(notification)
        return notification


@router.delete("/api/notifications")
def clear_notifications(current_user: CurrentUser = Depends(get_current_user)):
    with SessionLocal() as database:
        database.execute(
            delete(Notification).where(Notification.user_id == current_user.id)
        )
        database.commit()
        return {"success": True}


FALLBACK_IDEAS = [
    {
        "id": "1",
        "icon": "🏆",
        "title": "Build your AI competition entry",
        "description": "Research the rules and create your submission, demo script, and deadline checklist.",
        "prompt": "Help me research an AI competition and create my submission, demo script, and deadline checklist.",
    },
    {
        "id": "2",
        "icon": "🗂️",
        "title": "Create a money-making apps leaderboard",
        "description": "Track app names, links, categories, and reported earnings in one place.",
        "prompt": "Help me create a leaderboard of money-making apps with names, links, categories, and reported earnings.",
    },
    {
        "id": "3",
        "icon": "📹",
        "title": "Turn your app build into a Shorts series",
        "description": "Create episode ideas, video hooks, and shoot-ready scripts.",
        "prompt": "Turn my app-building journey into a Shorts series with episode ideas, hooks, and shoot-ready scripts.",
    },
    {
        "id": "4",
        "icon": "🚀",
        "title": "Build your launch post and assets",
        "description": "Generate launch copy, headlines, screenshots, and community responses.",
        "prompt": "Help me build a launch post with copy, headlines, screenshot ideas, and community responses.",
    },
]

_daily_ideas_cache: dict[str, list[dict]] = {}

DAILY_IDEAS_PROMPT = """
Generate 4 creative, high-value, actionable task ideas that a user can run today in Muse AI (an autonomous personal assistant with live web browsing, Python data/chart sandbox, Gmail/Calendar/Notion/GitHub workspace tools, and Swiggy food ordering).

Return ONLY valid JSON in this exact format:
{
  "ideas": [
    {
      "id": "idea-1",
      "icon": "⚡",
      "title": "Short catchy title (max 45 chars)",
      "description": "One-sentence explanation of what the assistant will do.",
      "prompt": "Detailed first-person instruction to send to the assistant."
    }
  ]
}
Rules:
- Return exactly 4 ideas.
- Use a single relevant emoji for "icon".
""".strip()


@router.get("/api/ideas/daily")
async def get_daily_ideas(
    force: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
):
    today_key = date.today().isoformat()
    if not force and today_key in _daily_ideas_cache:
        return _daily_ideas_cache[today_key]

    client = None
    try:
        client = _create_client_for_provider("groq")
        model_name = _get_model_name_for_provider("groq")
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": DAILY_IDEAS_PROMPT},
                {"role": "user", "content": f"Generate 4 fresh ideas for {today_key}."},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=700,
        )
        raw_content = (response.choices[0].message.content or "{}").strip()
        if raw_content.startswith("```"):
            raw_content = raw_content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        parsed = json.loads(raw_content)
        raw_list = parsed.get("ideas") if isinstance(parsed, dict) else parsed
        if not isinstance(raw_list, list) or len(raw_list) < 4:
            return FALLBACK_IDEAS

        cleaned_ideas = []
        for idx, item in enumerate(raw_list[:4], start=1):
            if not isinstance(item, dict):
                return FALLBACK_IDEAS
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            icon = str(item.get("icon") or "✨").strip()
            if not (title and description and prompt):
                return FALLBACK_IDEAS
            cleaned_ideas.append(
                {
                    "id": str(item.get("id") or f"daily-{today_key}-{idx}"),
                    "icon": icon[:4],
                    "title": title[:80],
                    "description": description[:180],
                    "prompt": prompt[:400],
                }
            )

        _daily_ideas_cache.clear()
        _daily_ideas_cache[today_key] = cleaned_ideas
        return cleaned_ideas
    except Exception:
        return FALLBACK_IDEAS
    finally:
        if client is not None:
            await client.close()