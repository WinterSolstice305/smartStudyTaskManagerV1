# Firebase and security

The application uses Firebase Authentication and Firestore directly from the client. There is no custom backend or API gateway in this repo, so all app data access is mediated by the client’s Firebase session and the Firestore security rules.

## Authentication mechanism

The app authenticates users through the Firebase Identity Toolkit REST API, implemented in `app/services/firebase_auth.py`.

### Identity Toolkit endpoints

The service calls:

- `https://identitytoolkit.googleapis.com/v1/accounts:signUp`
- `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword`

The request includes:

- a Firebase API key
- `returnSecureToken: true`
- an email and password payload

### Auth session contents

The `AuthSession` dataclass stores:

- `uid`
- `email`
- `id_token`
- `refresh_token`
- `expires_in`

This is created in memory after a successful authentication response. The session is the source of identity for all Firestore access.

### Login flow

1. User enters email/password in the login view.
2. `FirebaseAuthService.login()` sends the request.
3. Firebase returns the user’s identity data.
4. The resulting `AuthSession` is stored on the service.
5. The UI proceeds to the authenticated workspace.

### Registration flow

This mirrors the login flow, but uses the sign-up endpoint.

### Logout behavior

`FirebaseAuthService.logout()` sets `self._session = None`. The workspace then clears account state and redirects the user to the unauthenticated flow.

## Token acquisition and use

The auth service reads the Firebase ID token from the successful sign-in/sign-up response and uses it as the token passed to Firestore requests.

The Firestore service adds an `Authorization` header with the current Firebase ID token when making requests.

The current repo does not implement:

- automatic token refresh
- token expiration polling
- refresh-token rotation management
- server-side token verification

This means the app relies on Firebase being reachable and the session staying current while the client remains active.

## Firestore access method

All Firestore access is done through the REST API using urllib-based HTTP calls in `app/services/firestore.py`.

### Important details

- The base URL is `https://firestore.googleapis.com/v1`
- The path is scoped to the current user’s UID
- the code validates collection names and document IDs
- Firestore values are encoded from Python to the Firestore API’s field-value format

### User-scoped path pattern

```text
projects/{project_id}/databases/(default)/documents/users/{uid}/{collection}/{document_id}
```

This pattern is enforced by `FirestoreService._user_collection_path()` and is required for safe user isolation.

## UID-based document scoping

The app never stores task or subject documents at the project root or in a shared collection. Instead, every document is under the signed-in user’s folder.

Examples:

- `/users/user-a/tasks/task-1`
- `/users/user-a/subjects/math`

This means user A cannot access user B’s documents unless Firebase rules are bypassed.

## Security rules

The repo’s `firestore.rules` file states:

```firestore
rules_version = '2';

service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{userId} {
      allow read, write: if request.auth != null
                         && request.auth.uid == userId;

      match /{document=**} {
        allow read, write: if request.auth != null
                           && request.auth.uid == userId;
      }
    }
  }
}
```

### Rule behavior

Allowed:

- authenticated user reads/writes their own `/users/{uid}` subtree
- nested task and subject documents under that user subtree

Denied:

- unauthenticated access to any user data
- access to another user’s `/users/{otherUid}` subtree
- writes without a valid `request.auth.uid`

## Allowed and denied operations

### Allowed in practice

- create subject under `users/{uid}/subjects/...`
- update subject under the same UID path
- list tasks/subjects for the current user
- delete a task or subject for the current user
- read the user’s own `/users/{uid}` document

### Denied by rules

- any read or write to a document outside the current user’s UID path
- any request from an unauthenticated client
- any cross-user mutation

## Error handling

The Firestore service maps common Firebase errors to user-safe messages:

- `401` or `403` → `Firestore denied access...` with a generic explanation
- `404` on database/resource lookup → project or database configuration error
- missing Firestore documents when `allow_not_found=True` are treated as `None`

The auth service translates common backend errors into human-safe strings like:

- invalid credentials
- email already exists
- invalid API key
- disabled account

Sensitive raw Firebase details are intentionally filtered out before surfacing errors to the UI.

## Firebase configuration requirements

A developer must provide:

- a Firebase project with the correct project ID
- a valid Firebase web API key
- Email/Password auth enabled
- a Firestore database created for the project
- Firebase rules deployed from `firestore.rules`

The app’s configuration reads these values from environment variables, but it also contains default values in `app/config.py`; those defaults are not a safe production configuration and should not be used outside local development.

## Security testing procedures

The repository includes a Node-based rule test at `tests/firestore_rules.test.mjs`.

It validates:

- authenticated reads/writes succeed for the matching user
- cross-user access fails
- unauthenticated access fails
- user documents and nested task/subject data stay isolated

The repo’s test command is:

```powershell
npm test
```

This uses Firebase rules unit testing and the repo’s `firestore.rules` file to evaluate security behavior in a simulated Firestore environment.

## Known security and trust limitations

This project is client-driven and therefore has important caveats:

- the Firebase API key is embedded in the client runtime model
- the app is not protected by a backend service layer
- security relies on Firestore rules and the authenticated user’s UID
- Android builds can expose keys more easily than desktop/local development settings

These are not new vulnerabilities in the code itself, but they are meaningful design constraints for production readiness.
