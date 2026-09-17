import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { createSubmitGuard } from "./BoardColumnSubmitGuard.ts";

describe("board column submit guard", () => {
    it("blocks a second synchronous Enter submit and resets after completion", () => {
        const guard = createSubmitGuard();

        assert.equal(guard.tryStart(), true);
        assert.equal(guard.tryStart(), false);

        guard.finish();
        assert.equal(guard.tryStart(), true);
    });
});
