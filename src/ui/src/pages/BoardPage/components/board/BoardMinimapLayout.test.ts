import assert from "node:assert/strict";
import test from "node:test";
import { MINIMAP_WIDTH, minimapColumnPath, minimapScrollAt, minimapViewport } from "./BoardMinimapLayout.ts";

test("viewport marker stays inside the fixed widget at both scroll boundaries", () => {
    const start = minimapViewport(10000, 1000, -1);
    const end = minimapViewport(10000, 1000, 20000);
    assert.equal(start.x, 0);
    assert.equal(end.x + end.width, MINIMAP_WIDTH);
    assert.equal(end.maximum, 9000);
    assert.equal(minimapViewport(200, 1000, 0).maximum, 0);
});

test("very wide boards keep a visible minimum marker and a bounded path", () => {
    const columns = Array.from({ length: 10000 }, (_, i) => ({ left: i * 320, width: 300 }));
    const marker = minimapViewport(3200000, 390, 0);
    assert.equal(marker.width, 8);
    const path = minimapColumnPath(columns, 3200000);
    assert.ok(path.split("M").length - 1 <= MINIMAP_WIDTH / 2);
    assert.ok(path.length < 4500);
});

test("click centers the real viewport and clamps out-of-range input", () => {
    assert.equal(minimapScrollAt(0.5, 4000, 1000), 1500);
    assert.equal(minimapScrollAt(-1, 4000, 1000), 0);
    assert.equal(minimapScrollAt(2, 4000, 1000), 3000);
    assert.equal(minimapScrollAt(0.5, 200, 1000), 0);
});

test("empty or hidden viewports never produce invalid SVG coordinates", () => {
    assert.deepEqual(minimapViewport(0, 0, 0), { x: 0, width: MINIMAP_WIDTH, maximum: 0 });
    assert.equal(minimapColumnPath([], 0), "");
});
