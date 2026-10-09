import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from "@firebase/rules-unit-testing";
import {
  collection,
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  setDoc,
  updateDoc,
} from "firebase/firestore";

test("Firestore CRUD persists and isolates user subject and task data", async () => {
  const rules = await readFile(new URL("../firestore.rules", import.meta.url), "utf8");
  const environment = await initializeTestEnvironment({
    projectId: "demo-smart-study-task-manager",
    firestore: { rules },
  });

  try {
    const userA = environment.authenticatedContext("user-a").firestore();
    const userB = environment.authenticatedContext("user-b").firestore();
    const unauthenticated = environment.unauthenticatedContext().firestore();
    const userADoc = doc(userA, "users/user-a");
    const userASubject = doc(userA, "users/user-a/subjects/subject-a");
    const userATask = doc(userA, "users/user-a/tasks/task-a");
    const userBSubject = doc(userB, "users/user-b/subjects/subject-b");
    const userBTask = doc(userB, "users/user-b/tasks/task-b");

    await assertSucceeds(setDoc(userADoc, { displayName: "A" }));
    await assertSucceeds(getDoc(userADoc));
    await assertSucceeds(
      setDoc(userASubject, { title: "Subject A", created_at: "2026-01-01T00:00:00Z" }),
    );
    await assertSucceeds(
      setDoc(userATask, {
        title: "Task A",
        subject_id: "subject-a",
        deadline: "2026-12-01T00:00:00Z",
        status: "pending",
      }),
    );
    await assertSucceeds(updateDoc(userATask, { status: "completed" }));

    const userASecondSession = environment.authenticatedContext("user-a").firestore();
    assert.equal(
      (
        await assertSucceeds(
          getDoc(doc(userASecondSession, "users/user-a/tasks/task-a")),
        )
      ).data().status,
      "completed",
    );
    assert.deepEqual(
      (
        await assertSucceeds(
          getDocs(collection(userASecondSession, "users/user-a/subjects")),
        )
      ).docs.map((subject) => subject.id),
      ["subject-a"],
    );

    await assertFails(getDoc(doc(userB, "users/user-a/subjects/subject-a")));
    await assertFails(
      updateDoc(doc(userB, "users/user-a/subjects/subject-a"), { title: "B" }),
    );
    await assertFails(deleteDoc(doc(userB, "users/user-a/subjects/subject-a")));
    await assertFails(getDoc(doc(userB, "users/user-a/tasks/task-a")));
    await assertFails(
      updateDoc(doc(userB, "users/user-a/tasks/task-a"), { title: "B" }),
    );
    await assertFails(deleteDoc(doc(userB, "users/user-a/tasks/task-a")));
    await assertFails(getDoc(doc(userA, "users/user-b/subjects/subject-b")));
    await assertFails(getDoc(doc(userA, "users/user-b/tasks/task-b")));
    await assertFails(
      updateDoc(doc(userA, "users/user-b/subjects/subject-b"), { title: "A" }),
    );
    await assertFails(deleteDoc(doc(userA, "users/user-b/subjects/subject-b")));
    await assertFails(
      updateDoc(doc(userA, "users/user-b/tasks/task-b"), { title: "A" }),
    );
    await assertFails(deleteDoc(doc(userA, "users/user-b/tasks/task-b")));

    assert.deepEqual(
      (await assertSucceeds(getDocs(collection(userB, "users/user-b/subjects"))))
        .docs,
      [],
    );
    assert.deepEqual(
      (await assertSucceeds(getDocs(collection(userB, "users/user-b/tasks")))).docs,
      [],
    );
    await assertSucceeds(
      setDoc(userBSubject, { title: "Subject B", created_at: "2026-01-01T00:00:00Z" }),
    );
    await assertSucceeds(setDoc(userBTask, { title: "Task B" }));
    assert.deepEqual(
      (await assertSucceeds(getDocs(collection(userA, "users/user-a/subjects"))))
        .docs.map((subject) => subject.id),
      ["subject-a"],
    );
    assert.deepEqual(
      (await assertSucceeds(getDocs(collection(userA, "users/user-a/tasks"))))
        .docs.map((task) => task.id),
      ["task-a"],
    );

    await assertFails(getDoc(doc(unauthenticated, "users/user-a")));
    await assertFails(
      setDoc(doc(unauthenticated, "users/user-b/tasks/task-unauthenticated"), {}),
    );

    await assertSucceeds(deleteDoc(userATask));
    await assertSucceeds(deleteDoc(userASubject));
    assert.equal((await assertSucceeds(getDoc(userATask))).exists(), false);
    assert.equal((await assertSucceeds(getDoc(userASubject))).exists(), false);
  } finally {
    await environment.cleanup();
  }
});
