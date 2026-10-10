import assert from "node:assert/strict";
import { test } from "node:test";
import { matchesCardCreator } from "./CardCreatorFilter.ts";

test("creator filters preserve missing creators, current identity, OR, and principal type isolation", () => {
    const user = { uid: "a", type: "user" as const };
    const bot = { uid: "a", type: "bot" as const };
    assert.equal(matchesCardCreator(undefined, [], "a"), true);
    assert.equal(matchesCardCreator(undefined, ["me"], "a"), false);
    assert.equal(matchesCardCreator(user, ["me"], "a"), true);
    assert.equal(matchesCardCreator(user, ["me"], "b"), false);
    assert.equal(matchesCardCreator(user, ["user/b", "user/a"], "b"), true);
    assert.equal(matchesCardCreator(bot, ["me", "user/a"], "a"), false);
    assert.equal(matchesCardCreator(bot, ["bot/a"], "b"), true);
    assert.equal(matchesCardCreator(user, ["unknown/a"], "a"), false);
});
