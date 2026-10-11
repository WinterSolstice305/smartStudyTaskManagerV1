import asyncio
import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from app.services.firebase_auth import FirebaseAuthService


logger = logging.getLogger(__name__)


class FirestoreError(Exception):
    """A user-safe Firestore or authentication-state error."""


class AuthenticationRequiredError(FirestoreError):
    """Raised when a Firestore operation has no authenticated user."""


@dataclass(frozen=True)
class FirestoreDocument:
    document_id: str
    data: dict[str, Any]


class FirestoreService:
    _API_URL = "https://firestore.googleapis.com/v1"

    def __init__(self, auth: FirebaseAuthService, project_id: str) -> None:
        self._auth = auth
        self._project_id = project_id.strip()
        if not self._project_id or "/" in self._project_id:
            raise ValueError("A valid Firebase project ID is required.")

    async def create_document(
        self,
        collection: str,
        data: dict[str, Any],
        document_id: str | None = None,
    ) -> str:
        collection_path = self._user_collection_path(collection)
        query: dict[str, str | int] = {}
        if document_id is not None:
            query["documentId"] = self._validate_document_id(document_id)
        response = await asyncio.to_thread(
            self._request,
            "POST",
            collection_path,
            {"fields": self._encode_fields(data)},
            query,
        )
        if response is None:
            raise FirestoreError("Firestore returned an empty document response.")
        name = response.get("name")
        if not isinstance(name, str) or not name.rsplit("/", 1)[-1]:
            raise FirestoreError("Firestore returned an incomplete document response.")
        return name.rsplit("/", 1)[-1]

    async def read_document(
        self, collection: str, document_id: str
    ) -> FirestoreDocument | None:
        path = self._document_path(collection, document_id)
        response = await asyncio.to_thread(
            self._request, "GET", path, None, None, True
        )
        if response is None:
            return None
        return self._decode_document(response)

    async def update_document(
        self, collection: str, document_id: str, data: dict[str, Any]
    ) -> None:
        path = self._document_path(collection, document_id)
        fields = self._encode_fields(data)
        if not fields:
            raise ValueError("Provide at least one field to update.")
        query = [
            ("updateMask.fieldPaths", self._field_path(name)) for name in fields
        ]
        await asyncio.to_thread(
            self._request,
            "PATCH",
            path,
            {"fields": fields},
            query,
        )

    async def delete_document(self, collection: str, document_id: str) -> None:
        path = self._document_path(collection, document_id)
        await asyncio.to_thread(self._request, "DELETE", path, None, None)

    async def list_documents(
        self, collection: str
    ) -> list[FirestoreDocument]:
        started_at = perf_counter()
        path = self._user_collection_path(collection)
        documents: list[FirestoreDocument] = []
        page_token: str | None = None
        while True:
            query: dict[str, str | int] = {"pageSize": 1000}
            if page_token:
                query["pageToken"] = page_token
            try:
                response = await asyncio.to_thread(
                    self._request, "GET", path, None, query
                )
            except FirestoreError:
                logger.warning(
                    "Firestore could not load collection %s after %.2f seconds.",
                    collection,
                    perf_counter() - started_at,
                )
                raise
            if response is None:
                raise FirestoreError("Firestore returned an empty document list.")
            raw_documents = response.get("documents", [])
            if not isinstance(raw_documents, list):
                raise FirestoreError("Firestore returned an invalid document list.")
            if not all(isinstance(document, dict) for document in raw_documents):
                raise FirestoreError("Firestore returned an invalid document list.")
            documents.extend(self._decode_document(doc) for doc in raw_documents)
            page_token = response.get("nextPageToken")
            if not isinstance(page_token, str) or not page_token:
                logger.info(
                    "Firestore loaded collection %s (%d documents) in %.2f seconds.",
                    collection,
                    len(documents),
                    perf_counter() - started_at,
                )
                return documents

    def _user_collection_path(self, collection: str) -> str:
        session = self._auth.session
        if session is None:
            raise AuthenticationRequiredError(
                "Sign in before accessing Firestore data."
            )
        if not session.uid or not session.id_token:
            raise AuthenticationRequiredError(
                "Your Firebase session is invalid. Sign in again."
            )
        collection = self._validate_segment(collection, "collection")
        return (
            f"projects/{urllib.parse.quote(self._project_id, safe='')}"
            "/databases/(default)/documents/users/"
            f"{urllib.parse.quote(session.uid, safe='')}/{urllib.parse.quote(collection, safe='')}"
        )

    def _document_path(self, collection: str, document_id: str) -> str:
        return (
            f"{self._user_collection_path(collection)}/"
            f"{urllib.parse.quote(self._validate_document_id(document_id), safe='')}"
        )

    @staticmethod
    def _validate_segment(value: str, label: str) -> str:
        if not isinstance(value, str) or not value or "/" in value:
            raise ValueError(f"A valid Firestore {label} name is required.")
        return value

    @classmethod
    def _validate_document_id(cls, document_id: str) -> str:
        document_id = cls._validate_segment(document_id, "document")
        if document_id in {".", ".."}:
            raise ValueError("A valid Firestore document name is required.")
        return document_id

    def _request(
        self,
        method: str,
        resource_path: str,
        body: dict[str, Any] | None,
        query: dict[str, str | int] | list[tuple[str, str]] | None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        session = self._auth.session
        if session is None or not session.id_token:
            raise AuthenticationRequiredError(
                "Your Firebase session is no longer valid. Sign in again."
            )

        url = f"{self._API_URL}/{resource_path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={
                "Authorization": f"Bearer {session.id_token}",
                "Content-Type": "application/json",
            },
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw_response = response.read()
        except urllib.error.HTTPError as error:
            try:
                error_body = json.loads(error.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                error_body = {}
            details = (
                error_body.get("error") if isinstance(error_body, dict) else None
            )
            error_status = (
                details.get("status") if isinstance(details, dict) else None
            )
            error_message = (
                details.get("message") if isinstance(details, dict) else None
            )
            if (
                error.code == 404
                and allow_not_found
                and error_status == "NOT_FOUND"
                and isinstance(error_message, str)
                and error_message.startswith("Document not found:")
            ):
                return None
            if error.code in (401, 403):
                raise FirestoreError(
                    "Firestore denied access. Your session may have expired, or "
                    "Firestore Security Rules may not allow this operation."
                ) from None
            if error.code == 404:
                raise FirestoreError(
                    "Firestore database or resource was not found. Check the project "
                    "and database configuration."
                ) from None
            raise FirestoreError(
                f"Firestore request failed (HTTP {error.code}). Check the Firebase "
                "project configuration and try again."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise FirestoreError(
                "Could not reach Firestore. Check your internet connection and try again."
            ) from None

        if method == "DELETE" and not raw_response:
            return {}
        try:
            result = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise FirestoreError(
                "Firestore returned an invalid response. Please try again."
            ) from None
        if not isinstance(result, dict):
            raise FirestoreError(
                "Firestore returned an invalid response. Please try again."
            )
        return result

    @classmethod
    def _encode_fields(cls, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict) or not all(
            isinstance(key, str) and key for key in data
        ):
            raise ValueError("Firestore document data must use non-empty string fields.")
        return {key: cls._encode_value(value) for key, value in data.items()}

    @classmethod
    def _encode_value(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {"nullValue": None}
        if isinstance(value, bool):
            return {"booleanValue": value}
        if isinstance(value, int):
            return {"integerValue": str(value)}
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Firestore numbers must be finite.")
            return {"doubleValue": value}
        if isinstance(value, str):
            return {"stringValue": value}
        if isinstance(value, list):
            return {"arrayValue": {"values": [cls._encode_value(item) for item in value]}}
        if isinstance(value, dict):
            if not all(isinstance(key, str) and key for key in value):
                raise ValueError("Firestore map fields must use non-empty string names.")
            return {
                "mapValue": {
                    "fields": {
                        key: cls._encode_value(item) for key, item in value.items()
                    }
                }
            }
        raise ValueError(f"Unsupported Firestore value type: {type(value).__name__}.")

    @staticmethod
    def _decode_document(response: dict[str, Any]) -> FirestoreDocument:
        name = response.get("name")
        fields = response.get("fields", {})
        if not isinstance(name, str) or not name.rsplit("/", 1)[-1]:
            raise FirestoreError("Firestore returned an incomplete document response.")
        if not isinstance(fields, dict):
            raise FirestoreError("Firestore returned malformed document data.")
        try:
            data = {
                key: FirestoreService._decode_value(value)
                for key, value in fields.items()
            }
        except (KeyError, TypeError, ValueError) as error:
            raise FirestoreError("Firestore returned malformed document data.") from error
        return FirestoreDocument(document_id=name.rsplit("/", 1)[-1], data=data)

    @classmethod
    def _decode_value(cls, value: Any) -> Any:
        if not isinstance(value, dict) or len(value) != 1:
            raise ValueError("Malformed Firestore value.")
        value_type, item = next(iter(value.items()))
        if value_type == "nullValue":
            if item is not None:
                raise ValueError("Malformed Firestore null.")
            return None
        if value_type == "booleanValue" and isinstance(item, bool):
            return item
        if value_type == "stringValue" and isinstance(item, str):
            return item
        if value_type == "integerValue":
            return int(item)
        if value_type == "doubleValue":
            number = float(item)
            if not math.isfinite(number):
                raise ValueError("Malformed Firestore number.")
            return number
        if value_type == "arrayValue":
            if not isinstance(item, dict):
                raise ValueError("Malformed Firestore array.")
            items = item.get("values", [])
            if not isinstance(items, list):
                raise ValueError("Malformed Firestore array.")
            return [cls._decode_value(child) for child in items]
        if value_type == "mapValue":
            if not isinstance(item, dict):
                raise ValueError("Malformed Firestore map.")
            fields = item.get("fields", {})
            if not isinstance(fields, dict):
                raise ValueError("Malformed Firestore map.")
            return {key: cls._decode_value(child) for key, child in fields.items()}
        if value_type == "timestampValue" and isinstance(item, str):
            return item
        raise ValueError("Unsupported Firestore value.")

    @staticmethod
    def _field_path(field: str) -> str:
        escaped = field.replace("\\", "\\\\").replace("`", "\\`")
        return f"`{escaped}`"
