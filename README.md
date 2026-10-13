# Smart Study Task Manager

Smart Study Task Manager is a Python/Flet desktop application for managing academic subjects, tasks, deadlines, and study planning. The app authenticates users with Firebase Email/Password and stores user-scoped task and subject data in Cloud Firestore.

## Current implementation status

Implemented and covered by repository tests:

- Firebase email/password authentication flow
- Firestore REST API integration with user-scoped document paths
- subject CRUD and task CRUD
- task filtering, sorting, and calendar helpers
- AI recommendations and study-planning chat using Groq
- a responsive monthly calendar, calendar-based optional task deadlines, and
  collapsible task filters
- light and dark appearance settings with a locally persisted theme preference
- visible loading, slow-network status, retry feedback, and startup/data-load logs
- Firebase security rules and rules-unit testing
- pull-to-refresh support for the Home, Tasks, and Calendar screens using Flet scroll overscroll events and a safe study-cache cleanup guard that clears only the disposable local snapshot cache

Partially implemented or unverified live workflow:

- Android APK build path (`build/flutter`) is present but not validated by a checked-in build script
- Local development and packaged APKs call Groq directly. Android users enter
  their own key in Settings; no Firebase Cloud Function is required for AI.

## Technology stack

- Python: `>=3.14` (`pyproject.toml`)
- Flet: `>=1.0.4` in `requirements.txt` and `pyproject.toml`; Android wrapper uses `1.0.4`
- HTTPX: `httpx>=0.27,<1` for direct Groq Chat Completions calls
- Python dotenv: `python-dotenv>=1.2.4` in `pyproject.toml`; the
  `requirements.txt` install path allows `>=1.0.0,<2.0.0`
- Firebase Authentication + Firestore REST API
- Groq API for AI recommendations/chat
- Firebase rules-unit testing for security validation

## Prerequisites

- Python 3.14+
- A Firebase project with Email/Password auth enabled
- A Firestore database for the project
- A Groq API key for local development and AI use in an installed APK
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
GROQ_API_KEY=your-groq-key
GROQ_MODEL=openai/gpt-oss-20b
AI_BACKEND_URL=direct
```

## Environment and configuration

The application expects the following runtime values:

- `FIREBASE_API_KEY`
- `FIREBASE_PROJECT_ID`
- `GROQ_API_KEY` for local development; never commit or package this key
- `GROQ_MODEL` (optional; defaults to `openai/gpt-oss-20b`)
- `AI_BACKEND_URL=direct` selects the direct Groq API. Direct mode is the
  default and only AI mode supported by the app.
- On Android, configure a key in **Settings → Study assistance → Groq API
  key**; it is stored in the app-private data directory.

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

The Flet Android build configuration targets one `arm64-v8a` APK, excludes development-only files, and uses compressed native-library packaging to reduce the sideloaded APK size. This excludes 32-bit ARM and x86 devices; legacy native packaging can increase installed size and library load time.

From the repository root, generate the Android wrapper and then build the APK:

```powershell
flet build apk
flet-android-notifications-patch --project-root build\flutter
Set-Location build\flutter
flutter pub get
flutter build apk --release --target-platform android-arm64
```

The project has a Flet-generated wrapper and notification patch step; the APK
workflow has not been validated end to end. After installing
the APK, open **Settings → Study assistance**, enter the user's Groq API key,
and save it on that device. The key is written to the app-private file
`FLET_APP_STORAGE_DATA/.smart-study-task-manager/groq-config.json`; Android does
not expose this directory as a regular Downloads folder.

Do not include `.env` or a key in APK assets or source. A user-supplied key is
still extractable by someone with control of that device or APK runtime, so
distribute only builds that ask each user to supply their own key.

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
- Groq requests go directly from the client to the Groq API. Firebase Cloud
  Functions and Blaze billing are not required for AI requests. Each client
  supplies its own key, which is not a server-side secret once entered in an
  APK.
- The repository currently validates behavior with unit tests and Firebase rule tests; the live Groq API and Android APK build are not validated in a production-like environment.

## Troubleshooting

If login fails, confirm:

- `FIREBASE_API_KEY` is set
- Email/Password auth is enabled in Firebase
- the Firebase project ID matches the one declared in `.env`

If Firestore fails, confirm:

- the database exists
- the security rules were deployed
- the current user is authenticated and has the correct UID-scoped path

If Groq requests fail, confirm:

- `AI_BACKEND_URL=direct`
- `GROQ_API_KEY` is set in the repository-root `.env` for local development,
  or was entered in the installed APK's Study assistance Settings
- the selected model name is valid
- the environment was restarted after the key was added

See the project documentation for full setup and architecture details.
