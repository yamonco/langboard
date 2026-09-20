import assert from "node:assert/strict";
import test from "node:test";
import { resolveReactionActorNames, summarizeReactionActorNames } from "./reactionActorNames.ts";

test("resolves user and bot names in the reaction order", () => {
    const actors = [
        { uid: "user-1", name: "Joy Lee" },
        { uid: "bot-1", name: "Summary Bot (Bot)" },
    ];

    assert.deepEqual(resolveReactionActorNames(["bot-1", "user-1"], actors, "Unknown User"), ["Summary Bot (Bot)", "Joy Lee"]);
});

test("keeps an explicit fallback for deleted or unloaded actors", () => {
    assert.deepEqual(resolveReactionActorNames(["missing-1", "missing-2"], [], "Unknown User"), ["Unknown User", "Unknown User"]);
});

test("shows up to eight actors and reports the remaining count", () => {
    const names = Array.from({ length: 10 }, (_, index) => `Actor ${index + 1}`);

    assert.deepEqual(summarizeReactionActorNames(names), {
        visibleNames: names.slice(0, 8),
        remainingCount: 2,
    });
});
