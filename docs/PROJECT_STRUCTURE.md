# Project structure

This repository is a compact Python/Flet application. The significant runtime code is under `app/`, with the entry point in the repo root and unit tests under `tests/`.

## Repository tree

```text
.
├── .env.example
├── .gitignore
├── README.md
├── firebase.json
├── firestore.rules
├── functions/
│   ├── index.js
│   ├── package.json
│   ├── src/groq.js
│   └── test/groq.test.js
├── main.py
├── package.json
├── pyproject.toml
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── subject.py
│   │   └── task.py
│   ├── services/
│   │   ├── ai_config.py
│   │   ├── __init__.py
│   │   ├── firebase_auth.py
│   │   ├── firestore.py
│   │   ├── groq.py
│   │   ├── notifications.py
│   │   ├── study_cache.py
│   │   ├── subject_service.py
│   │   └── task_service.py
│   └── ui/
│       ├── __init__.py
│       ├── home.py
│       ├── login.py
│       ├── register.py
│       ├── task_views.py
│       ├── theme.py
│       └── workspace.py
├── tests/
│   ├── __init__.py
│   ├── firestore_rules.test.mjs
│   ├── test_firebase_auth.py
│   ├── test_firestore.py
│   ├── test_groq.py
│   ├── test_models_services.py
│   └── test_task_views.py
└── docs/
    ├── ARCHITECTURE.md
    ├── DATA_MODEL.md
    ├── FIREBASE_AND_SECURITY.md
    ├── PROJECT_STRUCTURE.md
    ├── SETUP.md
    └── README.md
```

The tree above excludes generated folders such as `.venv/`, `build/`, and `node_modules/` because they are tooling artifacts and not source-of-truth project code.

## Root-level files and folders

### `main.py`

Entry point for the application. It creates the auth service, the workspace, and the routing callbacks for login/register/home screens.

### `README.md`

The developer-facing overview and quick-start instructions. This repository has a README, but it is not the complete project documentation; the docs folder supplements it.

### `pyproject.toml`

Declares the Python project metadata and an upper-level requirement of `>=3.14`.

### `requirements.txt`

The Python dependency manifest used for standard installation. It includes:

- `flet>=1.0.4`
- `httpx>=0.27,<1`
- `python-dotenv>=1.0.0,<2.0.0`

### `firebase.json`

Firebase configuration file that points at `firestore.rules`, declares the
Node.js 20 Cloud Functions source directory, and defines local Functions and
Firestore emulator ports.

### `firestore.rules`

Rules file enabling UID-scoped access for each authenticated user under `/users/{userId}`.

### `package.json`

Node-based tooling for Firebase rules tests. It executes Firestore rules tests with `firebase-tools` and `@firebase/rules-unit-testing`.

### `.env.example`

Sanitized template for required environment variables.

## `app/`

### `app/config.py`

Reads Firebase and Groq environment variables. It also contains default placeholder values, which should not be treated as production-safe configuration.

### `app/models/`

Contains the domain models and validation helpers.

#### `app/models/common.py`

Defines:

- `require_text()`
- `parse_datetime()`
- `parse_optional_datetime()`
- `now_utc()`

These are shared by the domain models so that timestamps and values are normalized consistently.

#### `app/models/subject.py`

Defines the `Subject` dataclass. It validates IDs, titles, color values, descriptions, and timestamps before serializing to Firestore.

#### `app/models/task.py`

Defines the `Task` dataclass. It covers deadlines, status, priority, category, tags, and timestamps.

#### `app/models/__init__.py`

Defines `ModelValidationError` and `DocumentNotFoundError` used across the app.

## `app/services/`

### `app/services/firebase_auth.py`

Wraps Firebase Identity Toolkit calls for sign up and login. It also translates common Firebase API failures into readable user messages.

It saves only the email and refresh token at the platform-private storage path
`storage_root()/session.json`, then uses Firebase Secure Token to
restore a session on startup. Logout removes that file. This is the only
authentication implementation in the app and is used by the UI and Firestore
service.

### `app/services/firestore.py`

Provides a typed REST wrapper around Firestore. It validates document IDs, scopes paths to a user, encodes Python data to Firestore field representations, and reads lists and individual documents.

This is a core runtime dependency for all task and subject persistence.

### `app/services/subject_service.py`

A service wrapper around subjects. It validates updates, checks for task references before deletion, and raises `SubjectInUseError` when the subject is still assigned.

### `app/services/task_service.py`

A service wrapper for task CRUD. It ensures the assigned subject exists when creating or reassigning a task, performs update validation, and leaves `updated_at` in sync.

### `app/services/notifications.py`

Reconciles task notification preferences with Android-local scheduled events.
Stable IDs and app-private state support idempotent rescheduling and removal
when tasks change, complete, or are deleted. Deadline-time events require the
task's `alarm_enabled` preference as well as the Settings notification options.

### `app/services/groq.py`

Implements the AI planner functionality. It contains:

- `generate_task_recommendations()`
- `chat_about_tasks()`
- Groq request formatting and error handling
- local deadline sorting utilities

It sends direct Groq Chat Completions requests in both desktop and Android
builds. `GROQ_API_KEY` comes from the repository-root `.env` or the key saved
in app-private storage through Settings on Android. AI does not depend on
Firebase Cloud Functions.

### `app/services/ai_config.py`

Loads the repository-root `.env`, resolves the direct-mode Groq key, and
persists an Android user's key in the Flet app-private data directory.

### `app/services/study_cache.py`

Maintains a best-effort per-user snapshot at
`storage_root()/study-cache.json`. On Android, `storage_root()` is based on
Flet's `FLET_APP_STORAGE_DATA` app-private directory; desktop retains the
existing home-directory location. The workspace can render this
snapshot during its initial Firestore refresh; it is not an offline sync or
write queue.

## `app/ui/`

### `app/ui/login.py`

The signed-out login screen. It collects email and password, triggers Firebase login, and then calls the authentication callback.

### `app/ui/register.py`

The registration screen. It validates the email/password form and calls Firebase registration.

### `app/ui/workspace.py`

The main screen manager and primary UI controller. It owns the dashboard, tasks view, calendar, settings, profile data, filters, and AI controls.

This is the most important file in `app/ui` and is the central orchestration layer for the app.

### `app/ui/task_views.py`

Contains task filtering, sorting, and calendar helpers used by the workspace.

### `app/ui/theme.py`

Defines the light/dark palettes and persists the selected `dark_mode` value at
`storage_root()/preferences.json`.

### `app/services/storage.py`

Resolves persistent local storage through Flet's app-private Android storage
environment, with a desktop home-directory fallback. It centralizes directory
creation and reports permission failures without exposing credentials.

## `functions/`

### `functions/index.js`

Contains an optional authenticated `generateGroq` proxy, but the Python client
does not call it. Deploying Cloud Functions is not required for AI requests.

### `functions/src/groq.js`

Contains request-size validation and Groq error classification used by the
function. `functions/test/groq.test.js` exercises these helpers.

### `app/ui/home.py`

A simple logged-in page that is not the primary app route in the current implementation. It exists as a helper/screen, but the main application flow uses `StudyWorkspace` instead.

## `tests/`

The repo contains Python unit tests and a Firestore security rules test.

### Python tests

- `test_firebase_auth.py` verifies auth translation and token storage.
- `test_firestore.py` verifies Firestore request scoping, malformed responses, and permission checks.
- `test_groq.py` verifies AI prompt context, rate-limit handling, and read-only behavior.
- `test_models_services.py` verifies `Subject` and `Task` validation and CRUD logic.
- `test_task_views.py` validates sorting/filtering utilities.
- `test_workspace_ui.py` validates workspace loading, cache, calendar, and
  persisted-appearance behavior.

### `firestore_rules.test.mjs`

Validates the Firestore rules using `@firebase/rules-unit-testing`. This is the repo’s security-focused configuration test.

## Active vs inactive code

The code currently in active use includes:

- `main.py`
- `app/config.py`
- `app/services/*`
- `app/ui/workspace.py`
- `app/models/*`
- the tests under `tests/`

The following are present but are not the primary runtime flow for the app as implemented:

- `app/ui/home.py` is a screen helper rather than the active screen manager
- the Flutter packaging directory under `build/flutter` is build infrastructure, not the runtime app source
- `node_modules/` and `.venv/` are dependency artifacts and not part of the repository’s source design

## Relevant current limitations

- The Cloud Function's usage counter is an operational record, not application
  data, and requires the function service account to access Firestore.
- Local session, cache, and appearance files are best-effort; a device with
  access to the user's profile may access their cached study data or refresh
  token.
- The project contains an actual Firebase API key default in `app/config.py` and should not be used in production.
- Android packaging is present as a Flutter/Flet build layout, but there is no validated end-to-end APK build command checked in by the repo itself.
