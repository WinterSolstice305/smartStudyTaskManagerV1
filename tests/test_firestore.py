import asyncio
import http.client
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

from app.services.firebase_auth import AuthSession, FirebaseAuthService
from app.services.firestore import (
    AuthenticationRequiredError,
    FirestoreDocument,
    FirestoreError,
    FirestoreService,
)


class FakeResponse:
    def __init__(self, data: dict[str, object] | None = None, raw: bytes | None = None):
        self._raw = json.dumps(data or {}).encode("utf-8") if raw is None else raw

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def authenticated_service() -> FirestoreService:
    auth = FirebaseAuthService("test-key")
    auth._session = AuthSession(
        uid="user-a",
        email="student@example.com",
        id_token="firebase-id-token",
        refresh_token="refresh-token",
        expires_in="3600",
    )
    return FirestoreService(auth, "test-project")


class FirestoreServiceTests(unittest.TestCase):
    def test_unauthenticated_access_is_rejected_before_request(self) -> None:
        service = FirestoreService(FirebaseAuthService("test-key"), "test-project")
        with patch("app.services.firestore.urllib.request.urlopen") as urlopen:
            with self.assertRaises(AuthenticationRequiredError):
                asyncio.run(service.list_documents("tasks"))
        urlopen.assert_not_called()

    def test_operations_use_session_uid_and_id_token(self) -> None:
        service = authenticated_service()
        with patch(
            "app.services.firestore.urllib.request.urlopen",
            return_value=FakeResponse({"documents": []}),
        ) as urlopen:
            self.assertEqual(asyncio.run(service.list_documents("tasks")), [])

        request = urlopen.call_args.args[0]
        self.assertIn("/documents/users/user-a/tasks", request.full_url)
        self.assertEqual(
            request.get_header("Authorization"), "Bearer firebase-id-token"
        )

    def test_document_operations_round_trip_data_and_use_scoped_paths(self) -> None:
        service = authenticated_service()
        document_name = (
            "projects/test-project/databases/(default)/documents/"
            "users/user-a/notes/note-1"
        )
        responses = [
            FakeResponse({"name": document_name}),
            FakeResponse(
                {
                    "name": document_name,
                    "fields": {
                        "title": {"stringValue": "Review"},
                        "done": {"booleanValue": False},
                        "details": {
                            "mapValue": {
                                "fields": {
                                    "minutes": {"integerValue": "25"},
                                    "tags": {
                                        "arrayValue": {
                                            "values": [
                                                {"stringValue": "exam"},
                                                {"nullValue": None},
                                            ]
                                        }
                                    },
                                }
                            }
                        },
                    },
                }
            ),
            FakeResponse({"name": document_name}),
            FakeResponse(raw=b""),
        ]
        with patch(
            "app.services.firestore.urllib.request.urlopen",
            side_effect=responses,
        ) as urlopen:
            created_id = asyncio.run(
                service.create_document(
                    "notes",
                    {"title": "Review", "details": {"minutes": 25}},
                    "note-1",
                )
            )
            document = asyncio.run(service.read_document("notes", created_id))
            asyncio.run(service.update_document("notes", created_id, {"done": False}))
            asyncio.run(service.delete_document("notes", created_id))

        self.assertEqual(created_id, "note-1")
        self.assertEqual(
            document,
            FirestoreDocument(
                "note-1",
                {
                    "title": "Review",
                    "done": False,
                    "details": {"minutes": 25, "tags": ["exam", None]},
                },
            ),
        )
        requests = [call.args[0] for call in urlopen.call_args_list]
        self.assertEqual([request.method for request in requests], ["POST", "GET", "PATCH", "DELETE"])
        self.assertIn("/documents/users/user-a/notes?documentId=note-1", requests[0].full_url)
        self.assertTrue(
            all(
                "/documents/users/user-a/notes/note-1" in request.full_url
                for request in requests[1:]
            )
        )
        self.assertIn("updateMask.fieldPaths", requests[2].full_url)

    def test_missing_document_returns_none(self) -> None:
        service = authenticated_service()
        http_error = urllib.error.HTTPError(
            "https://firestore.googleapis.com",
            404,
            "Not Found",
            http.client.HTTPMessage(),
            io.BytesIO(
                b'{"error":{"status":"NOT_FOUND","message":'
                b'"Document not found: projects/test-project/documents/missing"}}'
            ),
        )
        with patch(
            "app.services.firestore.urllib.request.urlopen",
            side_effect=http_error,
        ):
            self.assertIsNone(asyncio.run(service.read_document("tasks", "missing")))

    def test_permission_denied_is_reported_without_raw_response(self) -> None:
        service = authenticated_service()
        http_error = urllib.error.HTTPError(
            "https://firestore.googleapis.com",
            403,
            "Forbidden",
            http.client.HTTPMessage(),
            io.BytesIO(b'{"error":{"message":"token-secret-detail"}}'),
        )
        with patch(
            "app.services.firestore.urllib.request.urlopen",
            side_effect=http_error,
        ):
            with self.assertRaisesRegex(FirestoreError, "Security Rules") as error:
                asyncio.run(service.list_documents("tasks"))
        self.assertNotIn("token-secret-detail", str(error.exception))

    def test_malformed_response_is_reported(self) -> None:
        service = authenticated_service()
        with patch(
            "app.services.firestore.urllib.request.urlopen",
            return_value=FakeResponse(raw=b"not-json"),
        ):
            with self.assertRaisesRegex(FirestoreError, "invalid response"):
                asyncio.run(service.list_documents("tasks"))

    def test_malformed_document_data_is_reported(self) -> None:
        service = authenticated_service()
        response = FakeResponse(
            {
                "documents": [
                    {
                        "name": "projects/test-project/documents/users/user-a/tasks/1",
                        "fields": {"items": {"arrayValue": "not-an-array"}},
                    }
                ]
            }
        )
        with patch(
            "app.services.firestore.urllib.request.urlopen",
            return_value=response,
        ):
            with self.assertRaisesRegex(FirestoreError, "malformed document data"):
                asyncio.run(service.list_documents("tasks"))

    def test_database_not_found_is_not_treated_as_a_missing_document(self) -> None:
        service = authenticated_service()
        http_error = urllib.error.HTTPError(
            "https://firestore.googleapis.com",
            404,
            "Not Found",
            http.client.HTTPMessage(),
            io.BytesIO(
                b'{"error":{"status":"NOT_FOUND","message":'
                b'"Database (default) not found."}}'
            ),
        )
        with patch(
            "app.services.firestore.urllib.request.urlopen",
            side_effect=http_error,
        ):
            with self.assertRaisesRegex(FirestoreError, "database or resource"):
                asyncio.run(service.read_document("tasks", "missing"))


if __name__ == "__main__":
    unittest.main()
