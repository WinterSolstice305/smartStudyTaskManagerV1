import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.models.subject import Subject
from app.models.task import Task
from app.services import gemini
from app.services.firebase_auth import AuthSession, FirebaseAuthService
from app.services.gemini import (
    GeminiServiceError,
    TaskRecommendationResult,
    chat_about_tasks,
    generate_task_recommendations,
)
from app.ui.workspace import StudyWorkspace


def make_task(
    task_id: str,
    title: str,
    *,
    status: str = "pending",
    deadline: datetime | None = None,
    subject_id: str | None = None,
) -> Task:
    return Task(
        id=task_id,
        title=title,
        deadline=deadline,
        description=f"Details for {title}",
        subject_id=subject_id,
        status=status,
    )


def fake_subject() -> Subject:
    return Subject(
        id="math",
        title="Mathematics",
        color="#2196F3",
        description="",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def fake_session(uid: str) -> AuthSession:
    return AuthSession(
        uid=uid,
        email=f"{uid}@example.com",
        id_token=f"token-{uid}",
        refresh_token=f"refresh-{uid}",
        expires_in="3600",
    )


class FakePage:
    def clean(self) -> None:
        return None

    def add(self, *_: object) -> None:
        return None


class GeminiServiceTests(unittest.TestCase):
    def test_empty_and_completed_only_lists_skip_the_api(self) -> None:
        async def exercise() -> None:
            with patch("app.services.gemini._generate_text", new_callable=AsyncMock) as call:
                empty = await generate_task_recommendations([])
                completed = await generate_task_recommendations(
                    [make_task("done", "Completed essay", status="completed")]
                )
            self.assertIn("no incomplete tasks", empty.summary.casefold())
            self.assertEqual(empty.recommendations, ())
            self.assertIn("no incomplete tasks", completed.summary.casefold())
            call.assert_not_awaited()

        asyncio.run(exercise())

    def test_recommendations_use_only_incomplete_task_ids_and_titles(self) -> None:
        tasks = [
            make_task("open", "Review calculus", subject_id="math"),
            make_task("done", "Finished essay", status="completed"),
        ]

        async def exercise() -> None:
            response = json.dumps(
                {
                    "summary": "Start with the open task.",
                    "recommendations": [
                        {"task_id": "open", "reason": "It is still unfinished."}
                    ],
                }
            )
            with patch(
                "app.services.gemini._generate_text",
                new_callable=AsyncMock,
                return_value=response,
            ) as call:
                result = await generate_task_recommendations(tasks, [fake_subject()])

            self.assertEqual(result.summary, "Start with the open task.")
            self.assertEqual(len(result.recommendations), 1)
            self.assertEqual(result.recommendations[0].task_id, "open")
            self.assertEqual(result.recommendations[0].title, "Review calculus")
            prompt = call.await_args.args[0]
            self.assertIn("Review calculus", prompt)
            self.assertNotIn("Finished essay", prompt)
            self.assertIn("Mathematics", prompt)

        asyncio.run(exercise())

    def test_valid_key_and_mocked_sdk_response_produce_recommendations(self) -> None:
        sdk_calls: list[dict[str, object]] = []
        output = json.dumps(
            {
                "summary": "Work on the nearest deadline first.",
                "recommendations": [
                    {"task_id": "urgent", "reason": "Its deadline is approaching."}
                ],
            }
        )

        class FakeAsyncClient:
            class Models:
                async def generate_content(self, **kwargs: object) -> object:
                    sdk_calls.append(kwargs)
                    return SimpleNamespace(text=output)

            models = Models()

            async def __aenter__(self) -> "FakeAsyncClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

        class FakeClient:
            def __init__(self, **kwargs: object) -> None:
                self.api_key = kwargs["api_key"]
                self.aio = FakeAsyncClient()

        async def exercise() -> None:
            task = make_task(
                "urgent",
                "Submit lab report",
                deadline=datetime(2026, 10, 1, tzinfo=timezone.utc),
            )
            with (
                patch.dict(
                    os.environ,
                    {
                        "GEMINI_BACKEND_URL": "direct",
                        "GEMINI_API_KEY": "test-key",
                        "GEMINI_MODEL": "test-flash",
                    },
                ),
                patch("app.services.gemini.genai.Client", FakeClient),
            ):
                result = await generate_task_recommendations([task])

            self.assertEqual(result.recommendations[0].title, "Submit lab report")
            self.assertEqual(len(sdk_calls), 1)
            self.assertEqual(sdk_calls[0]["model"], "test-flash")
            self.assertIn("deadline_status", sdk_calls[0]["contents"])
            self.assertEqual(
                sdk_calls[0]["config"].response_mime_type, "application/json"
            )
            self.assertNotIn("test-key", sdk_calls[0]["contents"])

        asyncio.run(exercise())

    def test_recommendations_reject_unknown_task_ids(self) -> None:
        async def exercise() -> None:
            with patch(
                "app.services.gemini._generate_text",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {
                        "summary": "A recommendation.",
                        "recommendations": [
                            {"task_id": "invented", "reason": "Do this task."}
                        ],
                    }
                ),
            ):
                with self.assertRaisesRegex(GeminiServiceError, "outside your current list"):
                    await generate_task_recommendations(
                        [make_task("real", "Real task")]
                    )

        asyncio.run(exercise())

    def test_chat_uses_supplied_context_and_omits_completed_tasks(self) -> None:
        tasks = [
            make_task("active", "Read chapter 4", subject_id="math"),
            make_task("done", "Completed lab", status="completed"),
        ]

        async def exercise() -> None:
            with patch(
                "app.services.gemini._generate_text",
                new_callable=AsyncMock,
                return_value="Start with chapter 4.",
            ) as call:
                response = await chat_about_tasks(
                    "What should I study?", tasks, [fake_subject()]
                )
            self.assertEqual(response, "Start with chapter 4.")
            prompt = call.await_args.args[0]
            self.assertIn("Read chapter 4", prompt)
            self.assertNotIn("Completed lab", prompt)
            self.assertIn("Mathematics", prompt)
            self.assertIn("What should I study?", prompt)

        asyncio.run(exercise())

    def test_missing_api_key_returns_a_user_safe_error(self) -> None:
        async def exercise() -> None:
            with patch.dict(
                os.environ,
                {"GEMINI_BACKEND_URL": "direct"},
                clear=True,
            ):
                with self.assertRaisesRegex(GeminiServiceError, "GEMINI_API_KEY"):
                    await chat_about_tasks("Plan my week", [])

        asyncio.run(exercise())

    def test_network_failure_returns_a_user_safe_error(self) -> None:
        class FakeAsyncClient:
            models = SimpleNamespace(
                generate_content=AsyncMock(
                    side_effect=httpx.ConnectError("network unavailable")
                )
            )

            async def __aenter__(self) -> "FakeAsyncClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

        class FakeClient:
            def __init__(self, **_: object) -> None:
                self.aio = FakeAsyncClient()

        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {
                        "GEMINI_BACKEND_URL": "direct",
                        "GEMINI_API_KEY": "test-key",
                    },
                ),
                patch("app.services.gemini.genai.Client", FakeClient),
            ):
                with self.assertRaisesRegex(GeminiServiceError, "Could not reach Gemini"):
                    await chat_about_tasks("Plan my week", [])

        asyncio.run(exercise())

    def test_backend_requests_use_firebase_bearer_token_without_client_key(self) -> None:
        requests: list[
            tuple[str, dict[str, object], dict[str, str]]
        ] = []

        class FakeBackendClient:
            def __init__(self, *, timeout: float) -> None:
                self.timeout = timeout

            async def __aenter__(self) -> "FakeBackendClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(
                self,
                url: str,
                *,
                json: dict[str, object],
                headers: dict[str, str],
            ) -> httpx.Response:
                requests.append((url, json, headers))
                return httpx.Response(
                    200,
                    json={"text": "Plan one focused study block."},
                    request=httpx.Request("POST", url),
                )

        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {
                        "GEMINI_BACKEND_URL": "https://ai.example.test/generateGemini",
                        "GEMINI_API_KEY": "must-not-be-used",
                    },
                ),
                patch(
                    "app.services.gemini.httpx.AsyncClient",
                    FakeBackendClient,
                ),
            ):
                response = await gemini._generate_text(
                    "Plan my week",
                    system_instruction="Use study context.",
                    max_output_tokens=700,
                    id_token="firebase-id-token",
                )

            self.assertEqual(response, "Plan one focused study block.")
            self.assertEqual(requests[0][0], "https://ai.example.test/generateGemini")
            request_headers = requests[0][2]
            self.assertEqual(
                request_headers["Authorization"], "Bearer firebase-id-token"
            )
            request_body = requests[0][1]
            self.assertNotIn("must-not-be-used", str(request_body))

        asyncio.run(exercise())

    def test_backend_quota_error_is_actionable_and_logs_no_response_body(self) -> None:
        class FakeBackendClient:
            def __init__(self, *, timeout: float) -> None:
                self.timeout = timeout

            async def __aenter__(self) -> "FakeBackendClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(
                self,
                url: str,
                *,
                json: dict[str, object],
                headers: dict[str, str],
            ) -> httpx.Response:
                _ = json, headers
                return httpx.Response(
                    429,
                    json={
                        "error": {
                            "code": "GEMINI_DAILY_LIMIT",
                            "message": "sensitive-backend-detail",
                        }
                    },
                    request=httpx.Request("POST", url),
                )

        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {"GEMINI_BACKEND_URL": "https://ai.example.test/generateGemini"},
                ),
                patch("app.services.gemini.httpx.AsyncClient", FakeBackendClient),
                self.assertLogs(gemini.logger, level="WARNING") as captured,
            ):
                with self.assertRaisesRegex(
                    GeminiServiceError, "today's AI request limit"
                ):
                    await gemini._generate_text(
                        "Plan my week",
                        system_instruction="Use study context.",
                        max_output_tokens=700,
                        id_token="firebase-id-token",
                    )

            diagnostic = "\n".join(captured.output)
            self.assertIn("category=user_daily_limit", diagnostic)
            self.assertIn("status=429", diagnostic)
            self.assertNotIn("sensitive-backend-detail", diagnostic)

        asyncio.run(exercise())

    def test_rate_limit_returns_a_retry_message(self) -> None:
        class FakeAPIError(Exception):
            code = 429

        class FakeAsyncClient:
            class Models:
                async def generate_content(self, **_: object) -> object:
                    raise FakeAPIError()

            models = Models()

            async def __aenter__(self) -> "FakeAsyncClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

        class FakeClient:
            def __init__(self, **_: object) -> None:
                self.aio = FakeAsyncClient()

        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {
                        "GEMINI_BACKEND_URL": "direct",
                        "GEMINI_API_KEY": "test-key",
                    },
                ),
                patch("app.services.gemini.genai.Client", FakeClient),
                patch.object(gemini.errors, "APIError", FakeAPIError),
            ):
                with self.assertRaisesRegex(GeminiServiceError, "quota or rate limit"):
                    await chat_about_tasks("Plan my week", [])

        asyncio.run(exercise())

    def test_api_status_is_logged_without_error_body_or_credentials(self) -> None:
        api_error = gemini.errors.APIError(
            503,
            {
                "error": {
                    "status": "UNAVAILABLE",
                    "message": "sensitive-response-detail",
                }
            },
        )

        class FakeAsyncClient:
            class Models:
                async def generate_content(self, **_: object) -> object:
                    raise api_error

            models = Models()

            async def __aenter__(self) -> "FakeAsyncClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

        class FakeClient:
            def __init__(self, **_: object) -> None:
                self.aio = FakeAsyncClient()

        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {
                        "GEMINI_BACKEND_URL": "direct",
                        "GEMINI_API_KEY": "sensitive-api-key",
                        "GEMINI_MODEL": "gemini-3.8-flash",
                    },
                ),
                patch("app.services.gemini.genai.Client", FakeClient),
                self.assertLogs(gemini.logger, level="WARNING") as captured,
            ):
                with self.assertRaisesRegex(
                    GeminiServiceError, "temporarily unavailable"
                ):
                    await chat_about_tasks("Plan my week", [])

            diagnostic = "\n".join(captured.output)
            self.assertIn("category=upstream_server", diagnostic)
            self.assertIn("status=503", diagnostic)
            self.assertIn("model=gemini-3.8-flash", diagnostic)
            self.assertNotIn("sensitive-api-key", diagnostic)
            self.assertNotIn("sensitive-response-detail", diagnostic)

        asyncio.run(exercise())

    def test_malformed_structured_response_is_rejected(self) -> None:
        async def exercise() -> None:
            with patch(
                "app.services.gemini._generate_text",
                new_callable=AsyncMock,
                return_value='{"summary":"Only summary"}',
            ):
                with self.assertRaisesRegex(GeminiServiceError, "incomplete recommendation"):
                    await generate_task_recommendations(
                        [make_task("one", "Study")]
                    )

        asyncio.run(exercise())

    def test_deadline_facts_are_computed_from_local_time(self) -> None:
        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        overdue = make_task("late", "Overdue", deadline=now - timedelta(days=2))
        due_soon = make_task("soon", "Due soon", deadline=now + timedelta(days=3))
        undated = make_task("none", "No deadline")

        self.assertEqual(
            gemini._task_context(overdue, {}, now)["deadline_status"], "overdue"
        )
        self.assertEqual(
            gemini._task_context(due_soon, {}, now)["deadline_status"], "due_soon"
        )
        undated_context = gemini._task_context(undated, {}, now)
        self.assertEqual(undated_context["deadline_status"], "no_deadline")
        self.assertIsNone(undated_context["seconds_until_deadline"])

    def test_user_switch_loads_only_the_new_users_tasks_for_ai(self) -> None:
        async def exercise() -> None:
            auth = FirebaseAuthService("test-key")
            auth._session = fake_session("user-a")
            workspace = StudyWorkspace(
                FakePage(), auth, "test-project", on_unauthenticated=lambda: None
            )
            task_a = make_task("task-a", "User A assignment")
            task_b = make_task("task-b", "User B assignment")
            workspace._load_data = AsyncMock(return_value=([task_a], []))
            await workspace.show("home")

            auth._session = fake_session("user-b")
            workspace._load_data = AsyncMock(return_value=([task_b], []))
            await workspace.show("home")

            with patch(
                "app.ui.workspace.generate_task_recommendations",
                new_callable=AsyncMock,
                return_value=TaskRecommendationResult("Done.", ()),
            ) as recommend:
                await workspace._request_recommendations()
            self.assertEqual(recommend.await_args.args[0], (task_b,))
            self.assertEqual(
                recommend.await_args.kwargs["id_token"], "token-user-b"
            )
            self.assertNotIn(task_a, recommend.await_args.args[0])

        asyncio.run(exercise())

    def test_dashboard_ai_request_is_async_and_blocks_duplicates(self) -> None:
        async def exercise() -> None:
            auth = FirebaseAuthService("test-key")
            auth._session = fake_session("user-a")
            workspace = StudyWorkspace(
                FakePage(), auth, "test-project", on_unauthenticated=lambda: None
            )
            workspace._data_uid = "user-a"
            workspace._data_available = True
            workspace.task_cache = [make_task("task-a", "Review notes")]
            started = asyncio.Event()
            finish = asyncio.Event()

            async def delayed_recommendation(
                tasks: object,
                subjects: object,
                *,
                id_token: str | None = None,
            ) -> TaskRecommendationResult:
                _ = tasks, subjects
                self.assertEqual(id_token, "token-user-a")
                started.set()
                await finish.wait()
                return TaskRecommendationResult("Done.", ())

            with patch(
                "app.ui.workspace.generate_task_recommendations",
                side_effect=delayed_recommendation,
            ) as recommend:
                request = asyncio.create_task(workspace._request_recommendations())
                await started.wait()
                self.assertTrue(workspace._recommendation_loading)
                await workspace._request_recommendations()
                self.assertEqual(recommend.await_count, 1)
                finish.set()
                await request

            self.assertFalse(workspace._recommendation_loading)

        asyncio.run(exercise())

    def test_ai_is_disabled_when_user_task_data_failed_to_load(self) -> None:
        async def exercise() -> None:
            auth = FirebaseAuthService("test-key")
            auth._session = fake_session("user-a")
            workspace = StudyWorkspace(
                FakePage(), auth, "test-project", on_unauthenticated=lambda: None
            )
            workspace._data_uid = "user-a"
            workspace._data_available = False
            with (
                patch(
                    "app.ui.workspace.generate_task_recommendations",
                    new_callable=AsyncMock,
                ) as recommendations,
                patch(
                    "app.ui.workspace.chat_about_tasks", new_callable=AsyncMock
                ) as chat,
            ):
                await workspace._request_recommendations()
                await workspace._send_chat_message("What is due?")

            recommendations.assert_not_awaited()
            chat.assert_not_awaited()

        asyncio.run(exercise())

    def test_ai_requests_do_not_write_to_firestore(self) -> None:
        async def exercise() -> None:
            auth = FirebaseAuthService("test-key")
            auth._session = fake_session("user-a")
            workspace = StudyWorkspace(
                FakePage(), auth, "test-project", on_unauthenticated=lambda: None
            )
            workspace._data_uid = "user-a"
            workspace._data_available = True
            workspace.task_cache = [make_task("task-a", "Review notes")]
            workspace.subject_cache = [fake_subject()]
            with (
                patch(
                    "app.ui.workspace.generate_task_recommendations",
                    new_callable=AsyncMock,
                    return_value=TaskRecommendationResult("Try review.", ()),
                ),
                patch(
                    "app.ui.workspace.chat_about_tasks",
                    new_callable=AsyncMock,
                    return_value="Review notes next.",
                ),
                patch.object(
                    workspace.firestore, "create_document", new_callable=AsyncMock
                ) as create,
                patch.object(
                    workspace.firestore, "update_document", new_callable=AsyncMock
                ) as update,
                patch.object(
                    workspace.firestore, "delete_document", new_callable=AsyncMock
                ) as delete,
            ):
                await workspace._request_recommendations()
                await workspace._send_chat_message("What next?")

            create.assert_not_awaited()
            update.assert_not_awaited()
            delete.assert_not_awaited()

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
