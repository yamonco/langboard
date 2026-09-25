import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
    calculateChecklistProgress,
    calculateChecklistProgressFromCounts,
    calculateDeadlinePressure,
    DEADLINE_PRESSURE_WINDOW_MS,
    getDeadlinePressureLevel,
} from "./BoardColumnCardStatus.ts";

describe("board column card status", () => {
    it("calculates checklist completion and hides progress without items", () => {
        assert.deepEqual(calculateChecklistProgress([]), { completed: 0, total: 0, ratio: 0 });
        assert.deepEqual(calculateChecklistProgress([{ is_checked: true }, { is_checked: false }]), {
            completed: 1,
            total: 2,
            ratio: 0.5,
        });
    });

    it("uses bounded board summary counts without detail hydration", () => {
        assert.deepEqual(calculateChecklistProgressFromCounts(7, 8), { completed: 7, total: 8, ratio: 0.875 });
        assert.deepEqual(calculateChecklistProgressFromCounts(0, 0), { completed: 0, total: 0, ratio: 0 });
        assert.deepEqual(calculateChecklistProgressFromCounts(9, 8), { completed: 8, total: 8, ratio: 1 });
    });

    it("ramps deadline pressure across seven days and suppresses completed cards", () => {
        const now = new Date("2026-09-17T00:00:00.000Z");

        assert.equal(calculateDeadlinePressure({ deadlineAt: undefined, now }), 0);
        assert.equal(calculateDeadlinePressure({ deadlineAt: new Date(now.getTime() + DEADLINE_PRESSURE_WINDOW_MS), now }), 0);
        assert.equal(calculateDeadlinePressure({ deadlineAt: new Date(now.getTime() + DEADLINE_PRESSURE_WINDOW_MS / 2), now }), 0.5);
        assert.equal(calculateDeadlinePressure({ deadlineAt: new Date(now.getTime() - 1), now }), 1);
        assert.equal(calculateDeadlinePressure({ deadlineAt: now, isCompleted: true, now }), 0);
    });

    it("classifies deadline pressure without treating the whole final week as urgent", () => {
        const now = new Date("2026-09-17T00:00:00.000Z");
        const at = (days: number) => new Date(now.getTime() + days * 24 * 60 * 60 * 1000);

        assert.equal(getDeadlinePressureLevel({ deadlineAt: at(4), now }), "none");
        assert.equal(getDeadlinePressureLevel({ deadlineAt: at(2.5), now }), "near");
        assert.equal(getDeadlinePressureLevel({ deadlineAt: at(1.5), now }), "due-soon");
        assert.equal(getDeadlinePressureLevel({ deadlineAt: at(0.5), now }), "critical");
        assert.equal(getDeadlinePressureLevel({ deadlineAt: at(-0.1), now }), "overdue");
        assert.equal(getDeadlinePressureLevel({ deadlineAt: at(-0.1), isCompleted: true, now }), "none");
    });
});
