# Android deadline notifications

The app uses `flet-android-notifications` for Android-local scheduling. The
desktop app remains functional without the Android extension; notification
preferences and reconciliation are no-ops outside Android.

## Android packaging

The extension uses Android alarm scheduling and needs the generated Flutter
project to be patched after `flet build` regenerates it. From the repository
root:

```powershell
flet build apk
flet-android-notifications-patch --project-root build\flutter
Set-Location build\flutter
flutter build apk --release --target-platform android-arm64
```

The project declares `POST_NOTIFICATIONS` and `RECEIVE_BOOT_COMPLETED` in
`pyproject.toml`. The patch step adds the notification receivers and the
desugaring configuration required by the extension. Repeat the patch step
after every `flet build` that regenerates `build/flutter`.
The Android Flet settings target a single `arm64-v8a` APK and exclude
development and local-only files. Native-library compression reduces the
sideloaded APK but can increase installed size and library load time.

## Runtime behavior

Notifications are disabled by default until the user enables them in Settings.
Enabling the master switch requests Android notification permission. The app
schedules inexact, idle-tolerant reminders 24 hours and 1 hour before a
deadline when those options are enabled. Each task also has an `Alarm at due
time` checkbox, enabled by default for new tasks. The deadline-time alert is
scheduled only for incomplete tasks with that preference enabled and while
the Settings master switch, deadline-alert option, and Android notification
permission allow notifications.

Tasks saved before this option existed default to alarm-disabled, avoiding
unexpected deadline notifications for historical tasks. Tasks without a
deadline, completed tasks, and tasks whose deadline is already past do not
receive a newly scheduled deadline-time alert. If a selected deadline is
already past when saving, the app reports that no alarm was scheduled.

Schedule IDs are derived from the task ID and event type. A local JSON state
file stores preferences and schedule metadata; the task cache remains the
authoritative local task snapshot. Reconciliation runs after authenticated data
loads and when the app resumes, and cancels schedules for completed, deleted,
or changed tasks. Editing a deadline replaces its scheduled notification;
disabling the task option cancels the deadline-time alert. The existing
24-hour/1-hour settings continue to control those reminders separately.

If the app was not running when an alarm-enabled incomplete task reached its
deadline, Android can deliver the pre-scheduled event without querying
Firebase. If a deadline was changed or a task was completed while the app was
closed, the next app startup/resume reconciliation cancels stale schedules.
The app does not claim delivery confirmation from Android.

The extension intentionally uses inexact scheduling and does not request exact
alarm access. Delivery timing can therefore vary by Android device power and
OEM policies; this is a local deadline notification, not a guaranteed
full-volume alarm.

Schedules are device-local. Each Android device needs notification permission,
the Settings master/deadline switches, and a reconciliation while signed in;
an alarm accepted on one device is not evidence that another device has it.
