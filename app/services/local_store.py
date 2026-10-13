"""Small device-local document store used by offline guest mode."""

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from app.services.storage import ensure_storage_root, storage_path


logger = logging.getLogger(__name__)


class LocalStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or storage_path("guest-data.json")

    def create(self, collection: str, data: dict[str, Any], document_id: str | None = None) -> str:
        payload = self._read()
        documents = payload.setdefault(collection, {})
        document_id = document_id or uuid.uuid4().hex
        if document_id in documents:
            raise ValueError(f"Document '{document_id}' already exists.")
        documents[document_id] = dict(data)
        self._write(payload)
        return document_id

    def read(self, collection: str, document_id: str) -> Any:
        from app.services.firestore import FirestoreDocument
        data = self._read().get(collection, {}).get(document_id)
        return FirestoreDocument(document_id, dict(data)) if isinstance(data, dict) else None

    def update(self, collection: str, document_id: str, data: dict[str, Any]) -> None:
        payload = self._read()
        documents = payload.setdefault(collection, {})
        if document_id not in documents:
            raise KeyError(document_id)
        documents[document_id].update(data)
        self._write(payload)

    def delete(self, collection: str, document_id: str) -> None:
        payload = self._read()
        documents = payload.setdefault(collection, {})
        if document_id not in documents:
            raise KeyError(document_id)
        del documents[document_id]
        self._write(payload)

    def list(self, collection: str) -> list[Any]:
        from app.services.firestore import FirestoreDocument
        documents = self._read().get(collection, {})
        return [FirestoreDocument(key, dict(value)) for key, value in documents.items()]

    def replace(self, collection: str, documents: dict[str, dict[str, Any]]) -> None:
        payload = self._read()
        payload[collection] = {key: dict(value) for key, value in documents.items()}
        self._write(payload)

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except FileNotFoundError:
            pass
        except PermissionError as error:
            logger.error("Local store read permission denied for %s", self._path)
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            logger.warning("Local store read failed for %s: %s", self._path, error)
        return {}

    def _write(self, payload: dict[str, Any]) -> None:
        if self._path.parent == storage_path("guest-data.json").parent:
            ensure_storage_root()
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(self._path)
