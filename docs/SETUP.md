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

The verified dependency versions are:

- `flet==1.0.3`
- `google-genai>=1.0.0,<3.0.0`
- `python-dotenv>=1.0.0,<2.0.0`

There is a version mismatch between the Python runtime manifest and the Flutter packaging file:

- `requirements.txt` pins `flet==1.0.3`
- `build/flutter/pubspec.yaml` pins `flet: 1.0.4`

This inconsistency is real and should be treated as a known repository discrepancy rather than silently normalized.

## 4. Environment configuration

Create a local `.env` file based on `.env.example`:

```dotenv
FIREBASE_API_KEY=replace-with-firebase-web-api-key
FIREBASE_PROJECT_ID=your-firebase-project-id
GEMINI_API_KEY=replace-with-gemini-api-key
GEMINI_MODEL=gemini-2.5-flash
```

This is the configuration used by:

- `app/config.py` for Firebase and project defaults
- `app/services/gemini.py` for Gemini API requests

Important notes:

- `FIREBASE_API_KEY` is a web API key for the Firebase project.
- `FIREBASE_PROJECT_ID` is the Firebase project ID, not the project display name.
- `GEMINI_MODEL` is optional because the code falls back to `gemini-2.5-flash`.
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

No other collection path is used by the app logic. Documents are created under the current signed-in user’s UID, so there is no cross-user access in normal app flows.

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

In Google AI Studio, create a Gemini API key. Then add it to the `.env` file and restart the app after the change.

The implementation in `app/services/gemini.py` expects these environment variables:

- `GEMINI_API_KEY`
- `GEMINI_MODEL` (optional)

The default model is `gemini-2.5-flash`.

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

These are the commands that are actually supported by the checked-in code and tooling.

## 14. Known setup risks

- The project is configured around a client-only Firebase web API usage model; this is fine for demos and local development but not a production-safe backend boundary.
- The default Firebase API key in `app/config.py` and the default project ID are not production values.
- The repo currently contains a known version mismatch between the Python dependency and the Flutter packaging config.
- The Gemini key should never be embedded in Android builds or any other shipped artifact.

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

- confirm `GEMINI_API_KEY` is set
- verify the model name is available in your project
- check the app logs for `GeminiServiceError` messages

### Android build fails

- verify Flutter and Android toolchain installation
- confirm the generated app configuration matches the project
- treat the Flutter APK path as unverified until a successful repo-local build is performed
