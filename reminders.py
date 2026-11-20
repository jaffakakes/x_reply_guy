"""London posting window and checkpoints for progress-aware reply reminders."""
import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
COUNT = 33


def day_window(instant=None):
    local = (instant or datetime.now(timezone.utc)).astimezone(LONDON)
    start = datetime.combine(local.date(), time(), LONDON)
    end = datetime.combine(local.date() + timedelta(days=1), time(), LONDON)
    return start, end


def reply_pace(count, goal, instant=None):
    instant = instant or datetime.now(timezone.utc)
    start, end = day_window(instant)
    opening = start.replace(hour=10)
    active = opening <= instant < end
    elapsed = max(0, (instant - opening).total_seconds())
    expected = min(goal, math.ceil(goal * elapsed / (end - opening).total_seconds()))
    remaining = max(0, goal - count)
    hours_left = max(0, (end - max(instant, opening)).total_seconds() / 3600)
    return {"day": start.date().isoformat(), "goal": goal, "replies": count,
            "remaining": remaining, "expected": expected, "goal_met": count >= goal,
            "behind": count < expected, "active_window": active,
            "needed_per_hour": round(remaining / hours_left, 1) if hours_left else 0,
            "deadline": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}


def daily_slots(day):
    start = datetime.combine(day, time(10), LONDON)
    slots = []
    for index in range(COUNT):
        # Round the evenly spaced 26m15s intervals to the nearest minute.
        minutes = (index * 840 + 16) // 32
        due = start + timedelta(minutes=minutes)
        slots.append({"id": f"{day.isoformat()}:{index + 1}", "number": index + 1,
                      "time": due.strftime("%H:%M"),
                      "due_at": due.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")})
    return slots


def slot_by_id(slot_id):
    try:
        day, number = slot_id.split(":")
        number = int(number)
        if not 1 <= number <= COUNT:
            raise ValueError()
        return daily_slots(date.fromisoformat(day))[number - 1]
    except (ValueError, TypeError, AttributeError):
        raise ValueError("That reminder does not exist.") from None


def schedule_at(instant=None):
    instant = instant or datetime.now(timezone.utc)
    local = instant.astimezone(LONDON)
    # Midnight is the previous posting day's final slot, including its completion.
    posting_day = local.date() if local.hour >= 10 else local.date() - timedelta(days=1)
    slots = daily_slots(posting_day)
    candidates = slots + daily_slots(posting_day + timedelta(days=1))
    due = [s for s in slots if datetime.fromisoformat(s["due_at"]) <= instant]
    future = [s for s in candidates if datetime.fromisoformat(s["due_at"]) > instant]
    return {"day": posting_day.isoformat(), "timezone": "Europe/London", "total": COUNT,
            "slots": slots, "current": due[-1] if due else None,
            "next": future[0] if future else None}
