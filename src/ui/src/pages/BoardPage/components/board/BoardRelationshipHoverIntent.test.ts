import assert from "node:assert/strict";
import test from "node:test";
import {
    createRelationshipHoverIntent,
    RELATIONSHIP_HOVER_CLOSE_DELAY_MS,
    RELATIONSHIP_HOVER_OPEN_DELAY_MS,
} from "./BoardRelationshipHoverIntent.ts";

const createClock = () => {
    let now = 0;
    let sequence = 0;
    const timers = new Map<number, { at: number; callback: () => void }>();
    return {
        schedule(callback: () => void, delay: number) {
            const id = ++sequence;
            timers.set(id, { at: now + delay, callback });
            return id;
        },
        cancel(timer: unknown) {
            timers.delete(timer as number);
        },
        advance(duration: number) {
            const target = now + duration;
            while (true) {
                const next = [...timers].sort((left, right) => left[1].at - right[1].at)[0];
                if (!next || next[1].at > target) break;
                now = next[1].at;
                timers.delete(next[0]);
                next[1].callback();
            }
            now = target;
        },
    };
};

test("pointer dwell opens only after two continuous seconds", () => {
    const clock = createClock();
    const opened: string[] = [];
    const intent = createRelationshipHoverIntent({ onOpen: (target: string) => opened.push(target), onClose() {}, ...clock });

    intent.pointerEnter("card-a");
    clock.advance(RELATIONSHIP_HOVER_OPEN_DELAY_MS - 1);
    assert.deepEqual(opened, []);
    clock.advance(1);
    assert.deepEqual(opened, ["card-a"]);

    intent.pointerEnter("card-b");
    clock.advance(1_000);
    intent.pointerLeave();
    clock.advance(RELATIONSHIP_HOVER_OPEN_DELAY_MS);
    assert.deepEqual(opened, ["card-a"]);
});

test("an opened shortcut remains for three seconds and re-entry cancels closing", () => {
    const clock = createClock();
    let closed = 0;
    const intent = createRelationshipHoverIntent({ onOpen() {}, onClose: () => closed++, ...clock });

    intent.pointerEnter("card-a");
    clock.advance(RELATIONSHIP_HOVER_OPEN_DELAY_MS);
    intent.pointerLeave();
    clock.advance(RELATIONSHIP_HOVER_CLOSE_DELAY_MS - 1);
    assert.equal(closed, 0);
    intent.keepOpen();
    clock.advance(1);
    assert.equal(closed, 0);
    intent.pointerLeave();
    clock.advance(RELATIONSHIP_HOVER_CLOSE_DELAY_MS);
    assert.equal(closed, 1);
});

test("keyboard focus opens immediately and explicit close cancels every timer", () => {
    const clock = createClock();
    const opened: string[] = [];
    let closed = 0;
    const intent = createRelationshipHoverIntent({ onOpen: (target: string) => opened.push(target), onClose: () => closed++, ...clock });

    intent.openImmediately("card-a");
    assert.deepEqual(opened, ["card-a"]);
    intent.pointerLeave();
    intent.close();
    clock.advance(RELATIONSHIP_HOVER_CLOSE_DELAY_MS);
    assert.equal(closed, 1);
});
