import assert from "node:assert/strict";
import { globalLabelDisplay } from "./LabelDisplay.ts";

const snapshot = { emoji: "📜", translations: { ko: { name: "컨트랙트", description: "개발 계약" } } };
assert.deepEqual(globalLabelDisplay("Contract", "Development agreement", snapshot, "ko-KR"), { name: "📜 컨트랙트", description: "개발 계약" });
assert.deepEqual(globalLabelDisplay("Contract", "Development agreement", snapshot, "fr"), {
    name: "📜 Contract",
    description: "Development agreement",
});
assert.deepEqual(globalLabelDisplay("Local", "Board text", null, "ko"), { name: "Local", description: "Board text" });
assert.equal(globalLabelDisplay("Contract", "Development agreement", { ...snapshot, emoji: "" }, "ko").name, "컨트랙트");
console.log("Label display localization, fallback, optional emoji and local isolation passed");
