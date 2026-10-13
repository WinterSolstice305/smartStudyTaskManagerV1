# Setup guide

This project is a Python client application backed by Firebase Authentication and Cloud Firestore. Setup is straightforward, but it requires a valid Firebase project, a configured `.env` file, and an environment that matches the project’s Python and package requirements.

## 1. Required software

The repository itself verifies the following requirements:

- Python 3.14 or newer (`pyproject.toml` declares `>=3.14`)
- a Firebase project with Email/Password authentication enabled
- a Firestore database for the project
- Groq API access for a local development key or backend secret
- Node.js for Firebase rules tests and emulator commands
- Flutter and Android SDK tooling only if the Android APK workflow is needed

## 2. Python environment setup

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

## 3. Dependency installation

The repository includes a Python requirements file and a `pyproject.toml` metadata file. The verified install command is:

```powershell
python -m pip install -r requirements.txt
```

The declared dependency versions are:

- `flet>=1.0.4`
- `httpx>=0.27,<1` for Groq API and Firebase Function requests
- `python-dotenv>=1.0.0,<2.0.0` in `requirements.txt`

`pyproject.toml` has stricter minimums for Flet and python-dotenv.

## 4. Environment configuration

Create a local `.env` file based on `.env.example`:

```dotenv
FIREBASE_API_KEY=replace-with-firebase-web-api-key
FIREBASE_PROJECT_ID=your-firebase-project-id
GROQ_API_KEY=replace-with-groq-api-key
GROQ_MODEL=openai/gpt-oss-20b
AI_BACKEND_URL=direct
```

`app/services/ai_config.py` explicitly loads the repository-root `.env` file with
`python-dotenv`; `.env.example` is a template and is not loaded automatically.
Existing process environment variables take precedence over values in `.env`.
The Groq client uses direct API requests and reads:

- `AI_BACKEND_URL=direct`; direct mode is the default and only mode used by the
  app. Firebase Cloud Functions are not called for AI requests.
- `GROQ_API_KEY` from the root `.env` or process environment. In the Android
  app, the user enters the key in Settings and it is saved in app-private
  storage.
- `GROQ_MODEL` for model selection (defaults to `openai/gpt-oss-20b`).

Important notes:

- `FIREBASE_API_KEY` is a web API key for the Firebase project.
- `FIREBASE_PROJECT_ID` is the Firebase project ID, not the project display name.
- `GROQ_MODEL` is optional because the code falls back to `openai/gpt-oss-20b`.
- For local desktop development, put `AI_BACKEND_URL=direct` and
  `GROQ_API_KEY=...` in the repository-root `.env`.
- For an installed APK, do not bundle `.env` or a key. Open **Settings → Study
  assistance**, enter the user's key, and select **Save key on this device**.
  The app writes it to
  `FLET_APP_STORAGE_DATA/.smart-study-task-manager/groq-config.json` inside
  Android app-private storage.
- `AI_BACKEND_URL` values other than `direct` are rejected; the app has no
  Firebase Function fallback.
- The application reads these values at runtime from environment variables and falls back to hardcoded defaults in `app/config.py`; those defaults are not a safe production configuration.

## 5. Firebase project configuration

Set up a Firebase project and then configure the following:

1. Enable Email/Password authentication.
2. Create a Firestore database in the default `firestore` location.
3. Set the project ID to the same value used in `FIREBASE_PROJECT_ID`.
4. Ensure the Firebase web API key is available for the app runtime.
5. Keep the Firestore rules in sync with `firestore.rules`.

The app itself does not use the Firebase Admin SDK. It uses the Firebase REST endpoints directly from the client.

## 6. Authentication provider setup

The app expects Firebase Email/Password sign-up and sign-in.

The repository verifies this contract in `app/services/firebase_auth.py` and in tests such as `tests/test_firebase_auth.py`.

To enable it in Firebase:

- open the Firebase project
- go to Authentication
- enable Sign-in method -> Email/Password

## 7. Firestore database setup

The app writes user-scoped collections under the pattern:

- `/users/{uid}/tasks`
- `/users/{uid}/subjects`

Task and subject documents are created under the current signed-in user’s UID,
so there is no cross-user access in normal app flows. The deployed Cloud Function maintains server-only daily usage records in the
legacy-named `_gemini_usage` collection. Keeping this collection name preserves
existing per-user request counts across the provider migration; it is not part
of the client domain model.

Create the database and deploy the rules before using the app.

## 8. Firestore security rules deployment

The repository includes `firestore.rules` and `firebase.json`.

A typical deployment command is:

```powershell
firebase login
firebase deploy --only firestore:rules
```

The rules are also validated by the Node-based test in `tests/firestore_rules.test.mjs`.

The local emulator test command used by the repo is:

```powershell
npm test
```

This uses Firebase rules unit testing to validate the rules file in an emulator context.

## 9. Groq API configuration

Create a Groq API key in the Groq Console. For local development, put these values in the repository-root `.env` file:

```dotenv
AI_BACKEND_URL=direct
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=openai/gpt-oss-20b
```

`app/services/ai_config.py` loads `.env` through an absolute path anchored to the repository, so launching `python main.py` from another current directory does not change which file is read. Existing process environment values take precedence.

The Flet Android build bundles the Python app but does not include the repository-root `.env`. After installing the APK, enter the user's Groq key in **Settings → Study assistance → Groq API key**, then select **Save key on this device**. The app writes it to `FLET_APP_STORAGE_DATA/.smart-study-task-manager/groq-config.json` within the Android app-private directory supplied by Flet. It is read at request time; no rebuild or public shared-storage permission is needed.

AI calls go directly from the client to Groq in both desktop and Android builds. The app rejects non-direct `AI_BACKEND_URL` values and does not call `generateGroq`. Cloud Functions deployment and the Firebase Blaze plan are not required for AI requests. Firebase Authentication and Firestore retain their separate project requirements for account and study-data features.

The default model is `openai/gpt-oss-20b`; override it with `GROQ_MODEL`. Application errors omit the API key and provider response body.

**Key warning:** A key entered in an APK remains accessible to someone who controls the device or extracts its app data. Do not ship an APK with a developer/shared key preloaded; ask each user to enter their own key. No live Groq API request or APK build is claimed as validated.
## 10. Desktop development startup

Start the app from the repo root:

```powershell
python main.py
```

This launches the Flet page defined in `main.py` and presents the login flow if no session is active.

## 11. Android build prerequisites

The repository contains a generated Flutter/Flet packaging layout in `build/flutter/`. From the repository root, `flet build apk` regenerates the wrapper and bundles the Python application; the local `.env` file is intentionally not part of the build. The generated project includes the Android configuration and the notification plugin integration described in [docs/NOTIFICATIONS.md](./NOTIFICATIONS.md).

The build environment needs Flet, Flutter, the Android SDK, and a Java toolchain. The installed APK needs the user's own Groq key entered in Settings; do not add a key to build arguments, source files, or APK assets.

## 12. APK build procedure

From the repository root, generate the Flet wrapper, apply the notification patch, and build the release APK:

```powershell
flet build apk
flet-android-notifications-patch --project-root build\flutter
Set-Location build\flutter
flutter pub get
flutter build apk --release --target-platform android-arm64
```

The Android settings in `pyproject.toml` produce one `arm64-v8a` APK and
exclude development files and local credentials. This excludes 32-bit ARM and
x86 devices; compressed native libraries reduce the sideloaded APK at the cost
of a somewhat larger installed footprint and slower library loading.

After installing, go to **Settings → Study assistance → Groq API key**, enter a key, and select **Save key on this device**. It is stored in the app-private Flet directory at `FLET_APP_STORAGE_DATA/.smart-study-task-manager/groq-config.json`; the user does not need to copy a file into the APK or rebuild it. This repository's build sequence has not been executed or validated in this session.
## 13. Verification commands

The project’s currently verified test command is:

```powershell
python -m unittest discover -s tests
```

The Firestore security rules test is:

```powershell
npm test
```

The Cloud Function request and Groq error-classification tests are:

```powershell
npm.cmd --prefix functions test
```

These are the commands that are actually supported by the checked-in code and tooling.

## 14. Known setup risks

- The project is configured around a client-only Firebase web API usage model; this is fine for demos and local development but not a production-safe backend boundary.
- The default Firebase API key in `app/config.py` and the default project ID are not production values.
- Do not embed a developer/shared Groq key in an Android build. Android users
  enter their own key in Settings; direct API use does not hide a key from its
  device owner.

## 15. Troubleshooting

### The app cannot authenticate

- confirm `FIREBASE_API_KEY` is set correctly in `.env`
- confirm the Firebase project has Email/Password auth enabled
- verify the Firebase project ID matches `FIREBASE_PROJECT_ID`

### Firestore access fails

- confirm the Firebase project and database are created
- deploy the rules with `firebase deploy --only firestore:rules`
- check that the user is signed in and a valid Firebase session exists

### Groq requests fail

- confirm `AI_BACKEND_URL=direct`
- on desktop, check the repository-root `.env` contains `GROQ_API_KEY`
- on Android, enter the key again in Settings if one has not been saved to
  app-private storage
- verify `GROQ_MODEL` is available to that Groq account
- use the sanitized client error to identify key access, model, rate-limit,
  timeout/network, or upstream server failures

### Android build fails

- verify Flutter and Android toolchain installation
- confirm the generated app configuration matches the project
- treat the Flutter APK path as unverified until a successful repo-local build is performed
