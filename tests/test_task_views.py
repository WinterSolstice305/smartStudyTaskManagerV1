import unittest
from datetime import date, datetime, timezone

from app.models.task import Task
from app.ui.task_views import filter_tasks, month_grid, sort_tasks, tasks_for_date


class TaskViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = [
            Task(
                "late",
                "Zebra",
                datetime(2026, 8, 5, tzinfo=timezone.utc),
                subject_id="science",
                priority="high",
                category="exam",
                status="pending",
                tags=["lab"],
            ),
            Task(
                "soon",
                "Alpha",
                datetime(2026, 8, 1, tzinfo=timezone.utc),
                subject_id="math",
                priority="low",
                status="completed",
            ),
            Task(
                "undated",
                "Beta",
                None,
                subject_id="math",
                priority="medium",
                category="homework",
            ),
        ]

    def test_filtering_only_selects_matching_tasks(self) -> None:
        self.assertEqual(
            [task.id for task in filter_tasks(self.tasks, subject_id="math")],
            ["soon", "undated"],
        )
        self.assertEqual(
            [task.id for task in filter_tasks(self.tasks, status="completed")],
            ["soon"],
        )
        self.assertEqual(
            [task.id for task in filter_tasks(self.tasks, priority="high")],
            ["late"],
        )
        self.assertEqual(
            [task.id for task in filter_tasks(self.tasks, category="EXAM")],
            ["late"],
        )

    def test_sorting_handles_missing_deadlines_and_priority_order(self) -> None:
        self.assertEqual(
            [task.id for task in sort_tasks(self.tasks, "deadline_asc")],
            ["soon", "late", "undated"],
        )
        self.assertEqual(
            [task.id for task in sort_tasks(self.tasks, "deadline_desc")],
            ["late", "soon", "undated"],
        )
        self.assertEqual(
            [task.id for task in sort_tasks(self.tasks, "priority_high")],
            ["late", "undated", "soon"],
        )
        self.assertEqual(
            [task.id for task in sort_tasks(self.tasks, "priority_low")],
            ["soon", "undated", "late"],
        )
        self.assertEqual(
            [task.id for task in sort_tasks(self.tasks, "title")],
            ["soon", "undated", "late"],
        )

    def test_calendar_groups_only_tasks_with_matching_deadline_date(self) -> None:
        self.assertEqual(
            [task.id for task in tasks_for_date(self.tasks, date(2026, 8, 1))],
            ["soon"],
        )
        self.assertEqual(tasks_for_date(self.tasks, date(2026, 8, 2)), [])
        self.assertEqual(len(month_grid(2026, 8)) % 7, 0)
        self.assertEqual(
            [day for day in month_grid(2026, 8) if day is not None][0],
            date(2026, 8, 1),
        )


if __name__ == "__main__":
    unittest.main()
