import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.local_store import LocalStore
from app.services.study_cache import StudyCache


class FirebaseAuthError(Exception):
    """A user-safe Firebase Authentication or configuration error."""


@dataclass(frozen=True)
class AuthSession:
    uid: str
    email: str
    id_token: str
    refresh_token: str
    expires_in: str
    is_guest: bool = False


class FirebaseAuthService:
    _AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts"
    _TOKEN_URL = "https://securetoken.googleapis.com/v1/token"

    def __init__(self, api_key: str, session_path: Path | None = None) -> None:
        self._api_key = api_key.strip()
        self._session: AuthSession | None = None
        self._session_path = session_path or (
            Path.home() / ".smart-study-task-manager" / "session.json"
        )
        self._guest_store = LocalStore()
        self._study_cache = StudyCache()

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

    async def login_as_guest(self) -> AuthSession:
        self._session = AuthSession("guest", "", "", "", "0", is_guest=True)
        return self._session

    async def restore_session(self) -> AuthSession | None:
        """Restore a saved session, using its locally cached token when offline.

        This never authenticates a new user offline. It only restores a session
        that was previously authenticated and persisted on this device.
        """
        try:
            saved = json.loads(self._session_path.read_text(encoding="utf-8"))
            refresh_token = saved["refresh_token"]
            email = saved.get("email", "")
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            return None
        if not isinstance(refresh_token, str) or not refresh_token:
            return None
        try:
            response = await asyncio.to_thread(self._refresh, refresh_token)
            session = AuthSession(
                uid=response["user_id"], email=email, id_token=response["id_token"],
                refresh_token=response["refresh_token"], expires_in=response["expires_in"],
            )
        except (FirebaseAuthError, KeyError, TypeError):
            # A refresh needs connectivity. If the previously issued ID token
            # is still valid, it can authorize only locally cached data.
            id_token = saved.get("id_token", "")
            uid = saved.get("uid", "")
            expires_at = saved.get("expires_at", 0)
            if not isinstance(id_token, str) or not id_token or not isinstance(uid, str) or not uid:
                return None
            session = AuthSession(
                uid=uid,
                email=email,
                id_token=id_token,
                refresh_token=refresh_token,
                expires_in=str(max(0, int(expires_at - datetime.now(timezone.utc).timestamp())))
                if isinstance(expires_at, (int, float)) else "0",
            )
            self._session = session
            return session
        self._session = session
        self._guest_store.clear()
        self._study_cache.clear("guest")
        self._save_session(session)
        return session

    def logout(self) -> None:
        self._session = None
        self._clear_saved_session()

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
        self._guest_store.clear()
        self._study_cache.clear("guest")
        self._save_session(session)
        return session

    def _refresh(self, refresh_token: str) -> dict[str, Any]:
        url = f"{self._TOKEN_URL}?key={urllib.parse.quote(self._api_key, safe='')}"
        request = urllib.request.Request(
            url,
            data=urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FirebaseAuthError("Could not restore the saved session.") from error
        if not isinstance(payload, dict):
            raise FirebaseAuthError("Firebase returned an invalid session response.")
        return payload

    def _save_session(self, session: AuthSession) -> None:
        try:
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                lifetime = max(0, int(session.expires_in))
            except (TypeError, ValueError):
                lifetime = 3600
            self._session_path.write_text(
                json.dumps({
                    "uid": session.uid,
                    "email": session.email,
                    "id_token": session.id_token,
                    "refresh_token": session.refresh_token,
                    "expires_at": datetime.now(timezone.utc).timestamp() + lifetime,
                }),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _clear_saved_session(self) -> None:
        try:
            self._session_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

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
