import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from app.models.subject import Subject
from app.models.task import Task
from app.services import ai_config
from app.services import groq
from app.services.firebase_auth import AuthSession, FirebaseAuthService
from app.services.groq import (
    GroqServiceError,
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


class GroqServiceTests(unittest.TestCase):
    def test_empty_and_completed_only_lists_skip_the_api(self) -> None:
        async def exercise() -> None:
            with patch("app.services.groq._generate_text", new_callable=AsyncMock) as call:
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
                "app.services.groq._generate_text",
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

    def test_valid_key_and_mocked_http_response_produce_recommendations(self) -> None:
        requests: list[tuple[str, dict[str, object], dict[str, str]]] = []
        output = json.dumps(
            {
                "summary": "Work on the nearest deadline first.",
                "recommendations": [
                    {"task_id": "urgent", "reason": "Its deadline is approaching."}
                ],
            }
        )

        class FakeHttpClient:
            def __init__(self, *, timeout: float) -> None:
                self.timeout = timeout

            async def __aenter__(self) -> "FakeHttpClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(
                self,
                url: str,
                *,
                json: dict[str, object],
                headers: dict[str, str],
            ) -> object:
                requests.append((url, json, headers))
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": output}}]},
                    request=httpx.Request("POST", url),
                )

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
                        "AI_BACKEND_URL": "direct",
                        "GROQ_API_KEY": "test-key",
                        "GROQ_MODEL": "test-model",
                    },
                ),
                patch("app.services.groq.httpx.AsyncClient", FakeHttpClient),
            ):
                result = await generate_task_recommendations([task])

            self.assertEqual(result.recommendations[0].title, "Submit lab report")
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0][0], groq._GROQ_API_URL)
            request_body = requests[0][1]
            self.assertEqual(request_body["model"], "test-model")
            prompt = request_body["messages"][1]["content"]
            self.assertIn("deadline_status", prompt)
            self.assertEqual(
                request_body["response_format"]["type"], "json_schema"
            )
            self.assertNotIn("test-key", str(request_body))
            self.assertEqual(
                requests[0][2]["Authorization"], "Bearer test-key"
            )

        asyncio.run(exercise())

    def test_recommendations_reject_unknown_task_ids(self) -> None:
        async def exercise() -> None:
            with patch(
                "app.services.groq._generate_text",
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
                with self.assertRaisesRegex(GroqServiceError, "outside your current list"):
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
                "app.services.groq._generate_text",
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
                {"AI_BACKEND_URL": "direct"},
                clear=True,
            ), patch("app.services.ai_config._stored_api_key", return_value=""):
                with self.assertRaisesRegex(
                    GroqServiceError, "GROQ_API_KEY"
                ) as raised:
                    await chat_about_tasks("Plan my week", [])
            self.assertEqual(raised.exception.availability, "unknown")

        asyncio.run(exercise())

    def test_groq_key_is_saved_in_app_storage_and_environment_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "groq-config.json"
            with (
                patch("app.services.ai_config.storage_path", return_value=config_path),
                patch(
                    "app.services.ai_config.ensure_storage_root",
                    side_effect=lambda: Path(directory),
                ),
                patch.dict(os.environ, {}, clear=True),
            ):
                ai_config.save_groq_api_key("gsk-device-key")
                self.assertEqual(ai_config.get_groq_api_key(), "gsk-device-key")
                self.assertTrue(ai_config.groq_api_key_configured())

                os.environ["GROQ_API_KEY"] = "gsk-env-key"
                self.assertEqual(ai_config.get_groq_api_key(), "gsk-env-key")

                del os.environ["GROQ_API_KEY"]
                ai_config.clear_saved_groq_api_key()
                self.assertFalse(ai_config.groq_api_key_configured())

    def test_ai_backend_must_be_direct_and_does_not_fall_back_to_firebase(self) -> None:
        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {
                        "AI_BACKEND_URL": "https://example.test/generateGroq",
                    },
                    clear=True,
                ),
                patch("app.services.groq.httpx.AsyncClient") as http_client,
            ):
                with self.assertRaisesRegex(
                    GroqServiceError, "must be set to 'direct'"
                ):
                    await groq._generate_text(
                        "Plan my week",
                        system_instruction="Use study context.",
                        max_output_tokens=700,
                        id_token="firebase-id-token",
                    )
            http_client.assert_not_called()

        asyncio.run(exercise())

    def test_network_failure_returns_a_user_safe_error(self) -> None:
        class FakeHttpClient:
            def __init__(self, *, timeout: float) -> None:
                self.timeout = timeout

            async def __aenter__(self) -> "FakeHttpClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(self, url: str, **_: object) -> httpx.Response:
                raise httpx.ConnectError("network unavailable")

        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {
                        "AI_BACKEND_URL": "direct",
                        "GROQ_API_KEY": "test-key",
                    },
                ),
                patch("app.services.groq.httpx.AsyncClient", FakeHttpClient),
            ):
                with self.assertRaisesRegex(
                    GroqServiceError, "Could not reach the AI service"
                ) as raised:
                    await chat_about_tasks("Plan my week", [])
            self.assertEqual(raised.exception.availability, "unavailable")

        asyncio.run(exercise())

    def test_unset_backend_setting_defaults_to_direct_groq_request(self) -> None:
        requests: list[tuple[str, dict[str, object], dict[str, str]]] = []

        class FakeHttpClient:
            def __init__(self, *, timeout: float) -> None:
                self.timeout = timeout

            async def __aenter__(self) -> "FakeHttpClient":
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
                    json={"choices": [{"message": {"content": "Start with math."}}]},
                    request=httpx.Request("POST", url),
                )

        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {"GROQ_API_KEY": "test-key"},
                    clear=True,
                ),
                patch("app.services.groq.httpx.AsyncClient", FakeHttpClient),
            ):
                response = await groq._generate_text(
                    "Plan my week",
                    system_instruction="Use study context.",
                    max_output_tokens=700,
                )

            self.assertEqual(response, "Start with math.")
            self.assertEqual(requests[0][0], groq._GROQ_API_URL)
            self.assertEqual(requests[0][2]["Authorization"], "Bearer test-key")

        asyncio.run(exercise())
    def test_rate_limit_returns_a_retry_message(self) -> None:
        class FakeHttpClient:
            def __init__(self, *, timeout: float) -> None:
                self.timeout = timeout

            async def __aenter__(self) -> "FakeHttpClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(self, url: str, **_: object) -> httpx.Response:
                return httpx.Response(
                    429,
                    json={"error": {"message": "sensitive provider detail"}},
                    request=httpx.Request("POST", url),
                )

        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {
                        "AI_BACKEND_URL": "direct",
                        "GROQ_API_KEY": "sensitive-api-key",
                    },
                ),
                patch("app.services.groq.httpx.AsyncClient", FakeHttpClient),
            ):
                with self.assertRaisesRegex(
                    GroqServiceError, "quota or rate limit"
                ) as raised:
                    await chat_about_tasks("Plan my week", [])
            self.assertEqual(raised.exception.availability, "available")

        asyncio.run(exercise())

    def test_api_status_is_logged_without_error_body_or_credentials(self) -> None:
        class FakeHttpClient:
            def __init__(self, *, timeout: float) -> None:
                self.timeout = timeout

            async def __aenter__(self) -> "FakeHttpClient":
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

            async def post(self, url: str, **_: object) -> httpx.Response:
                return httpx.Response(
                    503,
                    json={"error": {"message": "sensitive-response-detail"}},
                    request=httpx.Request("POST", url),
                )

        async def exercise() -> None:
            with (
                patch.dict(
                    os.environ,
                    {
                        "AI_BACKEND_URL": "direct",
                        "GROQ_API_KEY": "sensitive-api-key",
                        "GROQ_MODEL": "test-groq-model",
                    },
                ),
                patch("app.services.groq.httpx.AsyncClient", FakeHttpClient),
                self.assertLogs(groq.logger, level="WARNING") as captured,
            ):
                with self.assertRaisesRegex(
                    GroqServiceError, "temporarily unavailable"
                ):
                    await chat_about_tasks("Plan my week", [])

            diagnostic = "\n".join(captured.output)
            self.assertIn("category=backend_or_upstream_failure", diagnostic)
            self.assertIn("status=503", diagnostic)
            self.assertNotIn("sensitive-api-key", diagnostic)
            self.assertNotIn("sensitive-response-detail", diagnostic)

        asyncio.run(exercise())

    def test_malformed_structured_response_is_rejected(self) -> None:
        async def exercise() -> None:
            with patch(
                "app.services.groq._generate_text",
                new_callable=AsyncMock,
                return_value='{"summary":"Only summary"}',
            ):
                with self.assertRaisesRegex(GroqServiceError, "incomplete recommendation"):
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
            groq._task_context(overdue, {}, now)["deadline_status"], "overdue"
        )
        self.assertEqual(
            groq._task_context(due_soon, {}, now)["deadline_status"], "due_soon"
        )
        undated_context = groq._task_context(undated, {}, now)
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
            self.assertEqual(workspace._ai_availability, "available")
            self.assertEqual(
                [entry["role"] for entry in workspace._chat_history],
                ["user", "assistant"],
            )

        asyncio.run(exercise())

    def test_failed_chat_removes_only_its_message_and_allows_retry(self) -> None:
        async def exercise() -> None:
            auth = FirebaseAuthService("test-key")
            auth._session = fake_session("user-a")
            workspace = StudyWorkspace(
                FakePage(), auth, "test-project", on_unauthenticated=lambda: None
            )
            workspace.route = "assistant"
            workspace._data_uid = "user-a"
            workspace._data_available = True
            workspace._chat_history = [
                {"id": "older-message", "role": "user", "text": "What is due?"},
                {
                    "id": "older-response",
                    "role": "assistant",
                    "text": "Review your course page.",
                },
            ]
            started = asyncio.Event()
            finish = asyncio.Event()

            async def fail_request(*_: object, **__: object) -> str:
                started.set()
                await finish.wait()
                raise GroqServiceError(
                    "Could not reach the AI service.",
                    availability="unavailable",
                )

            with patch(
                "app.ui.workspace.chat_about_tasks", side_effect=fail_request
            ) as chat:
                request = asyncio.create_task(
                    workspace._send_chat_message("What is due?")
                )
                await started.wait()
                self.assertTrue(workspace._chat_loading)
                await workspace._send_chat_message("What is due?")
                self.assertEqual(chat.await_count, 1)
                finish.set()
                await request

            self.assertFalse(workspace._chat_loading)
            self.assertEqual(
                workspace._chat_history,
                [
                    {"id": "older-message", "role": "user", "text": "What is due?"},
                    {
                        "id": "older-response",
                        "role": "assistant",
                        "text": "Review your course page.",
                    },
                ],
            )
            self.assertEqual(workspace._chat_message, "What is due?")
            self.assertIn("Could not reach", workspace._chat_error)
            self.assertEqual(workspace._ai_availability, "unavailable")

        asyncio.run(exercise())

    def test_cancelled_chat_removes_only_its_pending_message(self) -> None:
        async def exercise() -> None:
            auth = FirebaseAuthService("test-key")
            auth._session = fake_session("user-a")
            workspace = StudyWorkspace(
                FakePage(), auth, "test-project", on_unauthenticated=lambda: None
            )
            workspace._data_uid = "user-a"
            workspace._data_available = True
            workspace._chat_history = [
                {"id": "older-message", "role": "user", "text": "Earlier question"}
            ]
            started = asyncio.Event()

            async def wait_for_cancel(*_: object, **__: object) -> str:
                started.set()
                await asyncio.Event().wait()
                return "unreachable"

            with patch(
                "app.ui.workspace.chat_about_tasks", side_effect=wait_for_cancel
            ):
                request = asyncio.create_task(
                    workspace._send_chat_message("Pending question")
                )
                await started.wait()
                request.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await request

            self.assertFalse(workspace._chat_loading)
            self.assertEqual(
                workspace._chat_history,
                [
                    {"id": "older-message", "role": "user", "text": "Earlier question"}
                ],
            )
            self.assertEqual(workspace._chat_message, "Pending question")

        asyncio.run(exercise())

    def test_unexpected_chat_error_is_logged_and_recovers_composer(self) -> None:
        async def exercise() -> None:
            auth = FirebaseAuthService("test-key")
            auth._session = fake_session("user-a")
            workspace = StudyWorkspace(
                FakePage(), auth, "test-project", on_unauthenticated=lambda: None
            )
            workspace._data_uid = "user-a"
            workspace._data_available = True
            workspace._chat_history = [
                {"id": "prior", "role": "assistant", "text": "Earlier answer"}
            ]

            with (
                patch(
                    "app.ui.workspace.chat_about_tasks",
                    new_callable=AsyncMock,
                    side_effect=ValueError("provider response parse failure"),
                ),
                self.assertLogs("app.ui.workspace", level="ERROR"),
            ):
                await workspace._send_chat_message("Current question")

            self.assertFalse(workspace._chat_loading)
            self.assertEqual(
                workspace._chat_history,
                [{"id": "prior", "role": "assistant", "text": "Earlier answer"}],
            )
            self.assertEqual(workspace._chat_message, "Current question")
            self.assertIn("could not complete", workspace._chat_error)
            self.assertEqual(workspace._ai_availability, "unknown")

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
