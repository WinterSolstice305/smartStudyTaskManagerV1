import asyncio
import http.client
import io
import json
import urllib.error
import unittest
from unittest.mock import patch

from app.services.firebase_auth import (
    AuthSession,
    FirebaseAuthError,
    FirebaseAuthService,
)


class FakeResponse:
    def __init__(self, data: dict[str, str]) -> None:
        self._data = json.dumps(data).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


class FirebaseAuthServiceTests(unittest.TestCase):
    def test_login_stores_authenticated_uid_and_tokens(self) -> None:
        service = FirebaseAuthService("test-key")
        response = {
            "localId": "firebase-uid",
            "email": "student@example.com",
            "idToken": "id-token",
            "refreshToken": "refresh-token",
            "expiresIn": "3600",
        }
        with patch(
            "app.services.firebase_auth.urllib.request.urlopen",
            return_value=FakeResponse(response),
        ):
            session = asyncio.run(service.login("student@example.com", "password"))

        self.assertEqual(session.uid, "firebase-uid")
        self.assertEqual(service.session, session)

    def test_firebase_auth_error_is_mapped_to_human_readable_message(self) -> None:
        service = FirebaseAuthService("test-key")
        body = json.dumps({"error": {"message": "EMAIL_EXISTS"}}).encode("utf-8")
        http_error = urllib.error.HTTPError(
            "https://firebase.invalid",
            400,
            "Bad Request",
            http.client.HTTPMessage(),
            io.BytesIO(body),
        )

        with patch(
            "app.services.firebase_auth.urllib.request.urlopen",
            side_effect=http_error,
        ):
            with self.assertRaisesRegex(
                FirebaseAuthError, "An account already exists"
            ):
                asyncio.run(service.register("student@example.com", "password"))

    def test_logout_clears_local_session(self) -> None:
        service = FirebaseAuthService("test-key")
        service._session = AuthSession(
            uid="firebase-uid",
            email="student@example.com",
            id_token="id-token",
            refresh_token="refresh-token",
            expires_in="3600",
        )

        service.logout()

        self.assertIsNone(service.session)


if __name__ == "__main__":
    unittest.main()
