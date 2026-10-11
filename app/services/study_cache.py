"""Small device-local snapshot cache used to render study data before refresh."""

import json
from pathlib import Path

from app.models.subject import Subject
from app.models.task import Task


class StudyCache:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path.home() / ".smart-study-task-manager" / "study-cache.json"

    def load(self, uid: str) -> tuple[list[Task], list[Subject]] | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            user_data = payload.get(uid) if isinstance(payload, dict) else None
            if not isinstance(user_data, dict):
                return None
            tasks = [Task.from_firestore(item["id"], item["data"]) for item in user_data["tasks"]]
            subjects = [Subject.from_firestore(item["id"], item["data"]) for item in user_data["subjects"]]
            return tasks, subjects
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def save(self, uid: str, tasks: list[Task], subjects: list[Subject]) -> None:
        try:
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            payload[uid] = {
                "tasks": [{"id": task.id, "data": task.to_firestore()} for task in tasks],
                "subjects": [{"id": subject.id, "data": subject.to_firestore()} for subject in subjects],
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self._path)
        except OSError:
            pass

    def clear(self, uid: str) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and uid in payload:
                del payload[uid]
                self._path.write_text(json.dumps(payload), encoding="utf-8")
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
