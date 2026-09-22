import assert from "node:assert/strict";
import { test } from "node:test";
import { getBoardChatStore } from "./BoardChatStore.ts";

class TestStorage implements Storage {
    private readonly data = new Map<string, string>();

    get length(): number {
        return this.data.size;
    }

    clear(): void {
        this.data.clear();
    }

    getItem(key: string): string | null {
        return this.data.get(key) ?? null;
    }

    key(index: number): string | null {
        return [...this.data.keys()][index] ?? null;
    }

    removeItem(key: string): void {
        this.data.delete(key);
    }

    setItem(key: string, value: string): void {
        this.data.set(key, value);
    }
}

test("pending Board chat task stays scoped to the user, project, and tab", () => {
    const firstTab = new TestStorage();
    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: firstTab });
    const store = getBoardChatStore();

    store.setPendingTaskId("user-a", "project-a", "task-a");
    const createdAt = store.getPendingTask("user-a", "project-a")?.createdAt;
    assert.equal(store.getPendingTask("user-a", "project-a")?.taskId, "task-a");
    assert.equal(typeof createdAt, "number");
    assert.equal(store.getPendingTask("user-b", "project-a"), null);
    assert.equal(store.getPendingTask("user-a", "project-b"), null);

    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: new TestStorage() });
    assert.equal(store.getPendingTask("user-a", "project-a"), null);
    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: firstTab });
    assert.deepEqual(store.getPendingTask("user-a", "project-a"), { taskId: "task-a", createdAt });

    store.setPendingTaskId("user-a", "project-a", null);
    assert.equal(store.getPendingTask("user-a", "project-a"), null);
});

test("legacy pending task IDs gain a stable recovery timestamp", () => {
    const storage = new TestStorage();
    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: storage });
    storage.setItem("board:user-a:project-a:chat:pending-task", "legacy-task");

    const store = getBoardChatStore();
    const first = store.getPendingTask("user-a", "project-a");
    const second = store.getPendingTask("user-a", "project-a");
    assert.deepEqual(second, first);
    assert.equal(first?.taskId, "legacy-task");
});

test("invalid structured pending tasks are discarded", () => {
    const storage = new TestStorage();
    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: storage });
    const key = "board:user-a:project-a:chat:pending-task";
    storage.setItem(key, JSON.stringify({ taskId: "task-a", createdAt: "invalid" }));

    assert.equal(getBoardChatStore().getPendingTask("user-a", "project-a"), null);
    assert.equal(storage.getItem(key), null);
});
