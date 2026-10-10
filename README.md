# Smart Study Task Manager

Smart Study Task Manager is a Python/Flet desktop application for managing academic subjects, tasks, deadlines, and study planning. The app authenticates users with Firebase Email/Password and stores user-scoped task and subject data in Cloud Firestore.

## Current implementation status

Implemented and covered by repository tests:

- Firebase email/password authentication flow
- Firestore REST API integration with user-scoped document paths
- subject CRUD and task CRUD
- task filtering, sorting, and calendar helpers
- AI recommendations and study-planning chat using Gemini
- Firebase security rules and rules-unit testing

Partially implemented or unverified live workflow:

- Android APK build path (`build/flutter`) is present but not validated by a checked-in build script
- Gemini API calls are implemented and unit-tested with mocks, but live calls are not verified in this repo
- the app relies on client-side Firebase configuration and environment variables rather than a custom backend

## Technology stack

- Python: `>=3.14` (`pyproject.toml`)
- Flet: `1.0.3` in `requirements.txt`; `1.0.4` in `build/flutter/pubspec.yaml` (notable discrepancy)
- Google GenAI: `google-genai>=1.0.0,<3.0.0`
- Python dotenv: `python-dotenv>=1.0.0,<2.0.0`
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
GEMINI_MODEL=gemini-2.5-flash
```

## Environment and configuration

The application expects the following runtime values:

- `FIREBASE_API_KEY`
- `FIREBASE_PROJECT_ID`
- `GEMINI_API_KEY`
- `GEMINI_MODEL` (optional; defaults to `gemini-2.5-flash`)

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

## Android build

The repository contains a Flutter/Flet packaging layout under `build/flutter`, but there is no checked-in, validated Android APK script that is proven end-to-end in this repo. The packaging path is present and indicates intent, but it is not a confirmed, fully verified build workflow.

Best-effort guidance:

```powershell
cd build\flutter
flutter pub get
flutter build apk
```

Treat this as a development-stage command until the project’s Android workflow is locally validated.

## Documentation index

- [docs/README.md](./docs/README.md)
- [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)
- [docs/PROJECT_STRUCTURE.md](./docs/PROJECT_STRUCTURE.md)
- [docs/SETUP.md](./docs/SETUP.md)
- [docs/DATA_MODEL.md](./docs/DATA_MODEL.md)
- [docs/FIREBASE_AND_SECURITY.md](./docs/FIREBASE_AND_SECURITY.md)

## Known limitations and caveats

- The repo uses in-memory session state; re-launching the app clears the current Firebase client session.
- The app stores data under `/users/{uid}/...`, so user isolation is enforced by Firestore rules, not by a separate backend.
- The default Firebase and Gemini configuration values in source code are not safe to treat as production secrets.
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

- `GEMINI_API_KEY` is set
- the selected model name is valid
- the environment was restarted after the key was added

See the project documentation for full setup and architecture details.
