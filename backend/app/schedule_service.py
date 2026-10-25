import math
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
INTERVAL_UNITS = {
    "second": 1,
    "seconds": 1,
    "minute": 60,
    "minutes": 60,
    "hour": 3600,
    "hours": 3600,
    "day": 86400,
    "days": 86400,
}


class ScheduleValidationError(ValueError):
    pass


def parse_schedule_text(value: str) -> dict[str, Any]:
    schedule = value.strip()
    normalized = schedule.lower()

    interval_match = re.fullmatch(
        r"every\s+(\d+)\s+(minute|minutes|hour|hours|day|days)",
        normalized,
    )

    if interval_match:
        amount = int(interval_match.group(1))
        unit = interval_match.group(2)

        return normalize_schedule_rule(
            {
                "frequency": "interval",
                "every": amount,
                "unit": unit,
            }
        )

    if normalized in {"every minute", "hourly", "every hour"}:
        minutes = 1 if normalized == "every minute" else 60
        return normalize_schedule_rule(
            {
                "frequency": "interval",
                "interval_minutes": minutes,
            }
        )

    if normalized.startswith("once"):
        return normalize_schedule_rule(
            {
                "frequency": "once",
                "time": _extract_schedule_time(schedule),
            }
        )

    weekday_match = re.match(
        r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        normalized,
    )

    if weekday_match:
        return normalize_schedule_rule(
            {
                "frequency": "weekly",
                "weekday": weekday_match.group(1),
                "time": _extract_schedule_time(schedule),
            }
        )

    if normalized.startswith("daily") or normalized.startswith("every day"):
        return normalize_schedule_rule(
            {
                "frequency": "daily",
                "time": _extract_schedule_time(schedule),
            }
        )

    raise ScheduleValidationError(
        "Use a schedule like 'Every day at 8:00 AM', "
        "'Every Monday at 9:00 AM', or 'Every 30 minutes'"
    )


def _extract_schedule_time(value: str) -> str:
    time_match = re.search(
        r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        value,
        re.IGNORECASE,
    )

    if not time_match:
        return "09:00"

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    period = (time_match.group(3) or "").lower()

    if minute > 59:
        raise ScheduleValidationError("Schedule minute must be between 0 and 59")

    if period:
        if hour < 1 or hour > 12:
            raise ScheduleValidationError("Schedule hour must be between 1 and 12")

        if period == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
    elif hour > 23:
        raise ScheduleValidationError("Schedule hour must be between 0 and 23")

    return f"{hour:02d}:{minute:02d}"


def normalize_schedule_rule(
    schedule_rule: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(schedule_rule, Mapping):
        raise ScheduleValidationError(
            "Schedule rule must be an object"
        )

    frequency = str(
        schedule_rule.get("frequency")
        or schedule_rule.get("type")
        or ""
    ).strip().lower()

    if frequency == "interval":
        interval_seconds = _interval_seconds(schedule_rule)

        if interval_seconds < 60:
            raise ScheduleValidationError(
                "Interval must be at least 60 seconds"
            )

        return {
            "frequency": "interval",
            "interval_seconds": interval_seconds,
        }

    if frequency == "daily":
        schedule_time = _parse_time(schedule_rule.get("time"))

        return {
            "frequency": "daily",
            "time": schedule_time.strftime("%H:%M"),
        }

    if frequency == "weekly":
        schedule_time = _parse_time(schedule_rule.get("time"))
        weekday = _parse_weekday(schedule_rule.get("weekday"))

        return {
            "frequency": "weekly",
            "time": schedule_time.strftime("%H:%M"),
            "weekday": _weekday_name(weekday),
        }

    if frequency == "once":
        schedule_time = _parse_time(schedule_rule.get("time"))

        return {
            "frequency": "once",
            "time": schedule_time.strftime("%H:%M"),
        }

    raise ScheduleValidationError("Frequency must be interval, daily, weekly, or once")


def calculate_next_run_at(
    schedule_rule: Mapping[str, Any],
    timezone_name: str | None = None,
    *,
    now: datetime | None = None,
    previous_run_at: datetime | None = None,
) -> datetime:
    rule = normalize_schedule_rule(schedule_rule)
    current_time = _aware_utc(now or datetime.now(UTC))
    selected_timezone = (
        timezone_name
        or str(schedule_rule.get("timezone") or "UTC")
    )
    timezone = _get_timezone(selected_timezone)

    if rule["frequency"] == "interval":
        return _next_interval_run(
            rule["interval_seconds"],
            current_time,
            previous_run_at,
        )

    local_now = current_time.astimezone(timezone)
    schedule_time = _parse_time(rule["time"])

    if rule["frequency"] in {"daily", "once"}:
        candidate_date = local_now.date()

        while True:
            candidate = _local_datetime(
                candidate_date,
                schedule_time,
                timezone,
            )

            if candidate.astimezone(UTC) > current_time:
                return candidate.astimezone(UTC)

            if rule["frequency"] == "once":
                candidate_date += timedelta(days=1)
                return _local_datetime(
                    candidate_date,
                    schedule_time,
                    timezone,
                ).astimezone(UTC)

            candidate_date += timedelta(days=1)

    target_weekday = _parse_weekday(rule["weekday"])
    days_until_target = (
        target_weekday - local_now.weekday()
    ) % 7
    candidate_date = (
        local_now.date()
        + timedelta(days=days_until_target)
    )

    while True:
        candidate = _local_datetime(
            candidate_date,
            schedule_time,
            timezone,
        )

        if candidate.astimezone(UTC) > current_time:
            return candidate.astimezone(UTC)

        candidate_date += timedelta(days=7)


def _next_interval_run(
    interval_seconds: int,
    now: datetime,
    previous_run_at: datetime | None,
) -> datetime:
    if previous_run_at is None:
        return now + timedelta(seconds=interval_seconds)

    anchor = _aware_utc(previous_run_at)

    if anchor > now:
        return anchor

    elapsed_seconds = (now - anchor).total_seconds()
    intervals_elapsed = math.floor(
        elapsed_seconds / interval_seconds
    ) + 1

    return anchor + timedelta(
        seconds=interval_seconds * intervals_elapsed
    )


def _interval_seconds(
    schedule_rule: Mapping[str, Any],
) -> int:
    direct_seconds = schedule_rule.get("interval_seconds")

    if direct_seconds is not None:
        return _positive_integer(
            direct_seconds,
            "interval_seconds",
        )

    direct_minutes = schedule_rule.get("interval_minutes")

    if direct_minutes is not None:
        return (
            _positive_integer(
                direct_minutes,
                "interval_minutes",
            )
            * 60
        )

    amount = schedule_rule.get("every")
    unit = str(
        schedule_rule.get("unit") or "minutes"
    ).strip().lower()

    if amount is None:
        raise ScheduleValidationError(
            "Interval schedule requires interval_seconds, "
            "interval_minutes, or every"
        )

    multiplier = INTERVAL_UNITS.get(unit)

    if multiplier is None:
        raise ScheduleValidationError(
            "Interval unit must be seconds, minutes, hours, or days"
        )

    return _positive_integer(amount, "every") * multiplier


def _positive_integer(
    value: Any,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise ScheduleValidationError(
            f"{field_name} must be a positive integer"
        )

    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ScheduleValidationError(
            f"{field_name} must be a positive integer"
        ) from error

    if number <= 0 or str(value).strip() not in {
        str(number),
        f"{number}.0",
    }:
        raise ScheduleValidationError(
            f"{field_name} must be a positive integer"
        )

    return number


def _parse_time(value: Any) -> time:
    if not isinstance(value, str):
        raise ScheduleValidationError(
            "Schedule time must use HH:MM format"
        )

    normalized = value.strip()

    try:
        parsed = datetime.strptime(
            normalized,
            "%H:%M",
        ).time()
    except ValueError as error:
        raise ScheduleValidationError(
            "Schedule time must use HH:MM format"
        ) from error

    return parsed.replace(second=0, microsecond=0)


def _parse_weekday(value: Any) -> int:
    if isinstance(value, bool):
        raise ScheduleValidationError(
            "Weekday must be a name from Monday to Sunday"
        )

    if isinstance(value, int):
        if 0 <= value <= 6:
            return value

        raise ScheduleValidationError(
            "Numeric weekday must be between 0 and 6"
        )

    normalized = str(value or "").strip().lower()

    if normalized not in WEEKDAYS:
        raise ScheduleValidationError(
            "Weekday must be a name from Monday to Sunday"
        )

    return WEEKDAYS[normalized]


def _weekday_name(weekday: int) -> str:
    return next(
        name
        for name, number in WEEKDAYS.items()
        if number == weekday
    )


def _get_timezone(timezone_name: str) -> ZoneInfo:
    normalized = timezone_name.strip()

    if not normalized:
        raise ScheduleValidationError(
            "Timezone cannot be empty"
        )

    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError as error:
        raise ScheduleValidationError(
            f"Unknown timezone: {normalized}"
        ) from error


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)


def _local_datetime(
    candidate_date: date,
    schedule_time: time,
    timezone: ZoneInfo,
) -> datetime:
    candidate = datetime.combine(
        candidate_date,
        schedule_time,
        tzinfo=timezone,
    )
    normalized = candidate.astimezone(UTC).astimezone(timezone)

    if normalized.replace(tzinfo=None) != candidate.replace(tzinfo=None):
        return normalized

    return candidate
