import assert from "node:assert/strict";
import { groupMembers } from "./memberGroups.ts";

assert.deepEqual(groupMembers([{ uid: "me", membership_classification: "internal" }], "me"), [
    { key: "personal", members: [{ uid: "me", membership_classification: "internal" }] },
]);
const mixed = [
    { uid: "customer", membership_classification: "external" as const },
    { uid: "me", membership_classification: "internal" as const },
    { uid: "unverified" },
];
assert.deepEqual(
    groupMembers(mixed, "me").map((group) => group.key),
    ["internal", "external", "unknown"]
);
assert.equal(groupMembers(mixed).flatMap((group) => group.members).length, mixed.length);
assert.deepEqual(groupMembers([]), []);
