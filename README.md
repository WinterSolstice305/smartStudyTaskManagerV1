# Smart Study Task Manager

Smart Study Task Manager is a Python/Flet desktop application for managing academic subjects, tasks, deadlines, and study planning. The app authenticates users with Firebase Email/Password and stores user-scoped task and subject data in Cloud Firestore.

## Current implementation status

Implemented and covered by repository tests:

- Firebase email/password authentication flow
- Firestore REST API integration with user-scoped document paths
- subject CRUD and task CRUD
- task filtering, sorting, and calendar helpers
- AI recommendations and study-planning chat using Gemini
- a responsive monthly calendar, calendar-based optional task deadlines, and
  collapsible task filters
- light and dark appearance settings with a locally persisted theme preference
- visible loading, slow-network status, retry feedback, and startup/data-load logs
- Firebase security rules and rules-unit testing

Partially implemented or unverified live workflow:

- Android APK build path (`build/flutter`) is present but not validated by a checked-in build script
- Gemini API calls are implemented and unit-tested with mocks, but live calls are not verified in this repo
- Firebase Authentication and Firestore data access remain client-side; Gemini
  requests use an authenticated Firebase Cloud Function

## Technology stack

- Python: `>=3.14` (`pyproject.toml`)
- Flet: `>=1.0.4` in `requirements.txt` and `pyproject.toml`; Android wrapper uses `1.0.4`
- Google GenAI: `google-genai>=2.29.0` in `pyproject.toml`; the `requirements.txt`
  install path allows `>=1.0.0,<3.0.0`
- Python dotenv: `python-dotenv>=1.2.4` in `pyproject.toml`; the
  `requirements.txt` install path allows `>=1.0.0,<2.0.0`
- Firebase Authentication + Firestore REST API
- Gemini API for AI recommendations/chat
- Firebase rules-unit testing for security validation

## Prerequisites

- Python 3.14+
- A Firebase project with Email/Password auth enabled
- A Firestore database for the project
- A Gemini API key from Google AI Studio
- Node.js for Firebase rules tests
- Flutter/Android SDK only for APK packaging work

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

Then populate your local `.env` file with real values, not placeholders:

```dotenv
FIREBASE_API_KEY=your-firebase-web-api-key
FIREBASE_PROJECT_ID=your-firebase-project-id
GEMINI_API_KEY=your-gemini-key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_BACKEND_URL=direct
```

## Environment and configuration

The application expects the following runtime values:

- `FIREBASE_API_KEY`
- `FIREBASE_PROJECT_ID`
- `GEMINI_API_KEY` only for local direct mode; deployed requests use the
  Firebase function secret
- `GEMINI_MODEL` (optional; defaults to `gemini-3.8-flash`)
- `GEMINI_BACKEND_URL` (optional; defaults to the Firebase Cloud Function
  derived from `FIREBASE_PROJECT_ID`; set to `direct` only for local development)

See `.env.example` for the sanitized template, and see [docs/SETUP.md](./docs/SETUP.md) for setup details.

## Running the app

```powershell
python main.py
```

The app starts in login mode and transitions into the authenticated workspace after sign-in.

## Running tests

Verified Python test command:

```powershell
python -m unittest discover -s tests
```

Firebase rules test command:

```powershell
npm test
```

Firebase Cloud Function unit tests:

```powershell
npm.cmd --prefix functions test
```

## Android build

The repository contains a Flutter/Flet packaging layout under `build/flutter`, but there is no checked-in, validated Android APK script that is proven end-to-end in this repo. The packaging path is present and indicates intent, but it is not a confirmed, fully verified build workflow.

Best-effort guidance:

```powershell
cd build\flutter
flutter pub get
flutter build apk
```

Treat this as a development-stage command until the project’s Android workflow is locally validated.

Do not include a local `.env` containing `GEMINI_API_KEY` in an APK. Packaged
clients should use the authenticated Cloud Function; the direct mode is for
local development only.

## Documentation index

- [docs/README.md](./docs/README.md)
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)
- [docs/PROJECT_STRUCTURE.md](./docs/PROJECT_STRUCTURE.md)
- [docs/SETUP.md](./docs/SETUP.md)
- [docs/DATA_MODEL.md](./docs/DATA_MODEL.md)
- [docs/FIREBASE_AND_SECURITY.md](./docs/FIREBASE_AND_SECURITY.md)

## Known limitations and caveats

- After a successful sign-in, the app stores the refresh token locally and
  attempts to restore the Firebase session at the next launch. Logging out
  removes that saved session.
- The app also keeps a per-user local task/subject snapshot to render while a
  startup refresh is in progress. This snapshot is a convenience cache, not an
  offline editing mode.
- The app stores data under `/users/{uid}/...`, so user isolation is enforced by Firestore rules, not by a separate backend.
- The default Firebase API key and project ID in source are demo configuration,
  not a production configuration.
- Gemini requests default to an authenticated Firebase Cloud Function with a
  per-user daily request limit. For local-only development, `GEMINI_BACKEND_URL=direct`
  opts into direct Google API requests using `GEMINI_API_KEY`. Never set that mode
  or bundle the private key in an Android APK.
- The repository currently validates behavior with unit tests and Firebase rule tests, but the live Gemini API and Android APK build are not fully validated in a production-like environment.

## Troubleshooting

If login fails, confirm:

- `FIREBASE_API_KEY` is set
- Email/Password auth is enabled in Firebase
- the Firebase project ID matches the one declared in `.env`

If Firestore fails, confirm:

- the database exists
- the security rules were deployed
- the current user is authenticated and has the correct UID-scoped path

If Gemini requests fail, confirm:

- a trusted function is deployed for the Firebase project, or use
  `GEMINI_BACKEND_URL=direct` for local-only development
- `GEMINI_API_KEY` is set in the trusted function secret store (or local `.env`
  when using direct mode)
- the selected model name is valid
- the environment was restarted after the key was added

See the project documentation for full setup and architecture details.
