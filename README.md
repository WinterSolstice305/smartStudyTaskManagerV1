# smartStudyTaskManagerV1

## Gemini AI setup

Install the project dependencies from the project directory:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Create a Gemini Developer API key in Google AI Studio and set it in `.env`:

```dotenv
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
GEMINI_MODEL=gemini-2.5-flash
```

The model setting is optional and defaults to `gemini-2.5-flash`; set
`GEMINI_MODEL` to another model enabled for your API project to change it.
When copying `.env.example`, replace `YOUR_GEMINI_MODEL` with
`gemini-2.5-flash` (or omit `GEMINI_MODEL` to use the default). Restart the app
after changing `.env`. The API key is required for live AI requests. The
automated tests use mocked Gemini responses and do not use quota.

`app.services.gemini.generate_task_recommendations(tasks, subjects=None)`
returns a summary and up to five validated recommendations for incomplete
tasks. `app.services.gemini.chat_about_tasks(message, tasks, subjects=None)`
returns a single-turn workload/planning answer. The service has no Firestore
write access; it receives the current authenticated user's already-loaded
task snapshot. Requests are asynchronous, bounded in size, and have a 25-second
timeout.

Run the Python tests with:

```powershell
python -m unittest discover -s tests
```

### Manual AI smoke checklist

1. Set a valid key, sign in, and create tasks with varied deadlines, priorities,
   subjects, and completion states. Request recommendations; check completed
   tasks are excluded and overdue/near-deadline tasks are identified correctly.
2. Complete all tasks and request recommendations. Check the empty-state
   message appears without an API request.
3. Ask the chatbot which task is due first and what to study next. Check it uses
   the visible tasks and acknowledges missing deadlines or subject details.
4. Remove the API key and restart. Request recommendations and send a chat
   message; check a useful configuration error appears and normal task
   create/edit/complete/delete still works.
5. Restore the key, then test offline access and (if available) a rate-limited
   API response. Check the error is readable and the retry action works.
6. Sign in as User A and make an AI request; log out, sign in as User B, and
   repeat. Check each request only includes that user's task snapshot. Confirm
   AI actions do not change tasks in Firestore.
7. While each request is loading, try to submit it again and navigate around.
   Check a loading indicator is shown, duplicate submission is blocked, and the
   rest of the UI/task management remains usable.

These are manual steps, not completed live checks. Automated tests cover
mocked valid SDK responses, incomplete/completed and empty tasks, context use,
malformed output, missing configuration, network/rate-limit errors, account
switching, AI read-only behavior, and duplicate-request responsiveness. A live
Gemini API call and Android APK build have not been tested.

The Gemini API key embedded in an Android APK can be extracted. This
environment-variable setup is for local development and demos only; protect
production Android requests behind a trusted authenticated backend or
server-side proxy. No such backend is included in this project.