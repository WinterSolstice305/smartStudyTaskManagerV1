from calendar import monthrange
from datetime import date, datetime, timezone

from app.models.task import Task


PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
LOW_PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2}


def filter_tasks(
    tasks: list[Task],
    *,
    subject_id: str = "",
    status: str = "",
    priority: str = "",
    category: str = "",
) -> list[Task]:
    return [
        task
        for task in tasks
        if (not subject_id or task.subject_id == subject_id)
        and (not status or task.status == status)
        and (not priority or task.priority == priority)
        and (not category or task.category.casefold() == category.casefold())
    ]


def sort_tasks(tasks: list[Task], ordering: str) -> list[Task]:
    if ordering == "deadline_asc":
        return sorted(
            tasks,
            key=lambda task: (
                task.deadline is None,
                task.deadline or datetime.max.replace(tzinfo=timezone.utc),
                task.title.casefold(),
            ),
        )
    if ordering == "deadline_desc":
        return sorted(
            tasks,
            key=lambda task: (
                task.deadline is not None,
                task.deadline or datetime.min.replace(tzinfo=timezone.utc),
                task.title.casefold(),
            ),
            reverse=True,
        )
    if ordering == "priority_high":
        return sorted(
            tasks,
            key=lambda task: (
                PRIORITY_RANK.get(task.priority.casefold(), 3),
                task.title.casefold(),
            ),
        )
    if ordering == "priority_low":
        return sorted(
            tasks,
            key=lambda task: (
                LOW_PRIORITY_RANK.get(task.priority.casefold(), 3),
                task.title.casefold(),
            ),
        )
    if ordering == "title":
        return sorted(tasks, key=lambda task: task.title.casefold())
    return list(tasks)


def tasks_for_date(tasks: list[Task], selected_date: date) -> list[Task]:
    return [
        task for task in tasks
        if task.deadline is not None
        and task.deadline.astimezone().date() == selected_date
    ]


def month_grid(year: int, month: int) -> list[date | None]:
    first_weekday, number_of_days = monthrange(year, month)
    leading_blanks = (first_weekday + 1) % 7
    cells: list[date | None] = [None] * leading_blanks
    cells.extend(date(year, month, day) for day in range(1, number_of_days + 1))
    cells.extend([None] * ((7 - len(cells) % 7) % 7))
    return cells
