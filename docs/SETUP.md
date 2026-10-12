# Setup guide

This project is a Python client application backed by Firebase Authentication and Cloud Firestore. Setup is straightforward, but it requires a valid Firebase project, a configured `.env` file, and an environment that matches the project’s Python and package requirements.

## 1. Required software

The repository itself verifies the following requirements:

- Python 3.14 or newer (`pyproject.toml` declares `>=3.14`)
- a Firebase project with Email/Password authentication enabled
- a Firestore database for the project
- Google AI Studio access for a Gemini API key
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
- `google-genai>=1.0.0,<3.0.0` in `requirements.txt`
- `python-dotenv>=1.0.0,<2.0.0` in `requirements.txt`

`pyproject.toml` currently has stricter minimums for Google GenAI (`>=2.29.0`)
and python-dotenv (`>=1.2.4`).

## 4. Environment configuration

Create a local `.env` file based on `.env.example`:

```dotenv
FIREBASE_API_KEY=replace-with-firebase-web-api-key
FIREBASE_PROJECT_ID=your-firebase-project-id
GEMINI_API_KEY=replace-with-gemini-api-key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_BACKEND_URL=direct
```

`app/services/gemini.py` explicitly loads the repository-root `.env` file with
`python-dotenv`; `.env.example` is a template and is not loaded automatically.
Existing process environment variables take precedence over values in `.env`.
The current Gemini client reads:

- `GEMINI_BACKEND_URL` to select the Cloud Function URL, or `direct` for
  local-only calls to Google
- `GEMINI_API_KEY` only when `GEMINI_BACKEND_URL=direct`; deployed functions
  read the key from Firebase Secret Manager
- `GEMINI_MODEL` for model selection (the client sends this only in direct mode;
  deployed functions configure it server-side)

Important notes:

- `FIREBASE_API_KEY` is a web API key for the Firebase project.
- `FIREBASE_PROJECT_ID` is the Firebase project ID, not the project display name.
- `GEMINI_MODEL` is optional because the code falls back to `gemini-3.8-flash`.
- In local `.env`, use `GEMINI_BACKEND_URL=direct` for local-only requests. Leave
  it unset in packaged clients to use
  `https://us-central1-<project>.cloudfunctions.net/generateGemini`.
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
so there is no cross-user access in normal app flows. The deployed Cloud
Function separately maintains a server-only `_gemini_usage` collection for AI
rate limiting; it is not part of the client domain model.

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

## 9. Gemini API configuration

For local-only development, create a Gemini API key in Google AI Studio, set
`GEMINI_BACKEND_URL=direct` and add the key to the root `.env` file. Never
commit or distribute this key.

The default model is `gemini-3.8-flash`, which is listed in Google's current
[Gemini API model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash).
Model availability, project quota, key restrictions, and network access still
depend on the configured Google project. Sanitized application logs report the
HTTP status category and model, but intentionally omit the API key and response
body.

The app defaults to an authenticated Firebase Cloud Function; its URL is derived
from `FIREBASE_PROJECT_ID` and can be overridden with `GEMINI_BACKEND_URL`.
The function verifies Firebase ID tokens, applies a per-user daily request
limit, and keeps `GEMINI_API_KEY` in Firebase Secret Manager. The Android client
does not need the Gemini key. Do not set `GEMINI_BACKEND_URL=direct`, bundle a
repository `.env`, or pass the Gemini key as an APK build variable.

To deploy the backend, use a Firebase project with Cloud Functions and Firestore
enabled, install the function dependencies, set the secret, and deploy:

```powershell
Set-Location functions
npm install
Set-Location ..
firebase functions:secrets:set GEMINI_API_KEY
firebase deploy --only functions:generateGemini
```

The deployed function defaults to `gemini-3.8-flash`. To select another model,
set `GEMINI_MODEL` in `functions/.env` before deploying; do not put the API key
in that file.

Cloud Functions deployment requires an eligible Firebase/Google Cloud billing
plan. The project's function service account must be able to access Firestore
for the daily usage counter. No live deployment or Android APK has been
validated from this repository.

## 10. Desktop development startup

Start the app from the repo root:

```powershell
python main.py
```

This launches the Flet page defined in `main.py` and presents the login flow if no session is active.

## 11. Android build prerequisites

The repository contains a Flutter/Flet packaging layout in `build/flutter/`. That directory includes:

- `pubspec.yaml`
- Android project structure
- `google-services.json` at the repo root (not verified as automatically wired to the build output)

The build artifacts indicate Android packaging is intended, but the repo does not include a validated end-to-end APK command or CI step. The app is primarily a Python desktop/Flet app in its current source state.

If Android packaging is needed, the environment should include:

- Flutter SDK
- Android SDK
- Java toolchain
- Android device/emulator setup or signed build configuration

## 12. APK build procedure

The repository does not contain a checked-in, validated APK build script. The packaging metadata in `build/flutter/pubspec.yaml` suggests a Flutter/Flet app, but the exact command has not been proven in this repo.

The following is the best current guidance, not a validated build certificate:

```powershell
cd build\flutter
flutter pub get
flutter build apk
```

This should be treated as a best-effort workflow until the repo’s packaging steps are explicitly validated.

## 13. Verification commands

The project’s currently verified test command is:

```powershell
python -m unittest discover -s tests
```

The Firestore security rules test is:

```powershell
npm test
```

The Cloud Function request and Gemini error-classification tests are:

```powershell
npm.cmd --prefix functions test
```

These are the commands that are actually supported by the checked-in code and tooling.

## 14. Known setup risks

- The project is configured around a client-only Firebase web API usage model; this is fine for demos and local development but not a production-safe backend boundary.
- The default Firebase API key in `app/config.py` and the default project ID are not production values.
- The Gemini key should never be embedded in Android builds or any other shipped artifact.
- Direct Google API requests are intended only for local development; Android
  clients must use the authenticated Cloud Function.

## 15. Troubleshooting

### The app cannot authenticate

- confirm `FIREBASE_API_KEY` is set correctly in `.env`
- confirm the Firebase project has Email/Password auth enabled
- verify the Firebase project ID matches `FIREBASE_PROJECT_ID`

### Firestore access fails

- confirm the Firebase project and database are created
- deploy the rules with `firebase deploy --only firestore:rules`
- check that the user is signed in and a valid Firebase session exists

### Gemini requests fail

- for local direct mode, set `GEMINI_BACKEND_URL=direct` and confirm `.env`
  contains `GEMINI_API_KEY` (the app loads `.env`, not `.env.example`)
- otherwise, verify the Firebase Cloud Function is deployed and the app's
  Firebase project ID matches its project
- verify the configured backend `GEMINI_MODEL` exists and is enabled
- use the sanitized application log category/status to distinguish missing
  configuration, key access, model, quota/rate-limit, timeout/network, and
  upstream server failures
- do not copy the development key to the device or APK; the Cloud Function reads
  the deployed secret and reports sanitized failure categories in its logs

### Android build fails

- verify Flutter and Android toolchain installation
- confirm the generated app configuration matches the project
- treat the Flutter APK path as unverified until a successful repo-local build is performed
