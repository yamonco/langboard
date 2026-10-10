import assert from "node:assert/strict";
import test from "node:test";
import { boardGraphViewForUser } from "./BoardGraphPreference.ts";

test("graph mode belongs to the account, not the last person using this browser", () => {
    const stored = JSON.parse(JSON.stringify({ alice: "network", bob: "columns" }));
    assert.equal(boardGraphViewForUser(stored, "alice"), "network");
    assert.equal(boardGraphViewForUser(stored, "bob"), "columns");
    assert.equal(boardGraphViewForUser(stored, "new-user"), "columns");
});

test("missing, invalid and inherited preferences use the readable column default", () => {
    for (const settings of [null, undefined, "network", { alice: "unknown" }, Object.create({ alice: "network" })]) {
        assert.equal(boardGraphViewForUser(settings, "alice"), "columns");
    }
});
