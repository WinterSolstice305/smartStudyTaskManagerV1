import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class FirebaseAuthError(Exception):
    """A user-safe Firebase Authentication or configuration error."""


@dataclass(frozen=True)
class AuthSession:
    uid: str
    email: str
    id_token: str
    refresh_token: str
    expires_in: str


class FirebaseAuthService:
    _AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key.strip()
        self._session: AuthSession | None = None

    @property
    def session(self) -> AuthSession | None:
        return self._session

    async def register(self, email: str, password: str) -> AuthSession:
        return await self._authenticate(
            "signUp",
            {"email": email, "password": password, "returnSecureToken": True},
        )

    async def login(self, email: str, password: str) -> AuthSession:
        return await self._authenticate(
            "signInWithPassword",
            {"email": email, "password": password, "returnSecureToken": True},
        )

    def logout(self) -> None:
        self._session = None

    async def _authenticate(
        self, operation: str, payload: dict[str, str | bool]
    ) -> AuthSession:
        if not self._api_key or self._api_key == "YOUR_API_KEY":
            raise FirebaseAuthError(
                "Firebase is not configured. Set FIREBASE_API_KEY in the app configuration."
            )

        response = await asyncio.to_thread(self._post_json, operation, payload)
        try:
            session = AuthSession(
                uid=response["localId"],
                email=response.get("email", ""),
                id_token=response["idToken"],
                refresh_token=response["refreshToken"],
                expires_in=response["expiresIn"],
            )
        except (KeyError, TypeError) as error:
            raise FirebaseAuthError(
                "Firebase returned an incomplete authentication response."
            ) from error

        self._session = session
        return session

    def _post_json(self, operation: str, payload: dict[str, str | bool]) -> dict[str, Any]:
        url = (
            f"{self._AUTH_URL}:{operation}"
            f"?key={urllib.parse.quote(self._api_key, safe='')}"
        )
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw_response = response.read()
        except urllib.error.HTTPError as error:
            try:
                error_body = json.loads(error.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                error_body = {}
            error_details = (
                error_body.get("error") if isinstance(error_body, dict) else None
            )
            code = (
                error_details.get("message", "")
                if isinstance(error_details, dict)
                else ""
            )
            raise FirebaseAuthError(self._friendly_error(code)) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise FirebaseAuthError(
                "Could not reach Firebase. Check your internet connection and try again."
            ) from None

        try:
            result = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise FirebaseAuthError(
                "Firebase returned an invalid response. Please try again."
            ) from None
        if not isinstance(result, dict):
            raise FirebaseAuthError(
                "Firebase returned an invalid response. Please try again."
            )
        return result

    @staticmethod
    def _friendly_error(code: str) -> str:
        code = code.split(":", maxsplit=1)[0]
        messages = {
            "EMAIL_EXISTS": "An account already exists for this email.",
            "INVALID_EMAIL": "Enter a valid email address.",
            "WEAK_PASSWORD": "Choose a stronger password (at least 6 characters).",
            "INVALID_PASSWORD": "Email or password is incorrect.",
            "EMAIL_NOT_FOUND": "Email or password is incorrect.",
            "INVALID_LOGIN_CREDENTIALS": "Email or password is incorrect.",
            "USER_DISABLED": "This account has been disabled.",
            "TOO_MANY_ATTEMPTS_TRY_LATER": (
                "Too many attempts. Wait a while and try again."
            ),
            "OPERATION_NOT_ALLOWED": (
                "Email/password sign-in is not enabled for this Firebase project."
            ),
            "CONFIGURATION_NOT_FOUND": (
                "Email/password sign-in is not enabled for this Firebase project."
            ),
            "API_KEY_INVALID": (
                "Firebase API key is invalid. Check the key in Firebase project settings."
            ),
            "INVALID_API_KEY": (
                "Firebase API key is invalid. Check the key in Firebase project settings."
            ),
        }
        return messages.get(code, "Firebase Authentication failed. Please try again.")
